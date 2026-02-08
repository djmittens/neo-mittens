#include "cmd.h"
#include "git.h"
#include "json.h"
#include "log.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

/*
 * tix sync - walk git history and replay plan.jsonl into the cache.
 *
 * By default syncs the current branch. Accepts an optional branch name
 * or --all to sync all branches.
 *
 * The cache is cumulative: tickets from all synced branches accumulate.
 * Only tix sync clears and rebuilds; normal operations are additive.
 *
 * History walking is changeset-aware: between consecutive commits we
 * compare the set of ticket IDs to detect compaction events (tickets
 * that disappeared without an accept/delete/reject marker). These
 * tickets have their compacted_at timestamp set.
 */

/* max commits to walk in history */
#define TIX_SYNC_MAX_COMMITS 512

/* max ticket IDs to track per snapshot for compaction detection */
#define TIX_SYNC_MAX_IDS 256

/* collect commit hashes that touched a given file path */
static u32 collect_hashes(const char *branch, const char *file_path,
                          char hashes[][48], u32 max_hashes,
                          u32 existing_count) {
  char cmd[TIX_MAX_PATH_LEN + 256];
  int n;

  if (branch != NULL) {
    n = snprintf(cmd, sizeof(cmd),
        "git log %s --format=%%H --follow -- %s", branch, file_path);
  } else {
    n = snprintf(cmd, sizeof(cmd),
        "git log --format=%%H --follow -- %s", file_path);
  }
  if (n < 0 || (sz)n >= sizeof(cmd)) { return existing_count; }

  char hash_buf[TIX_SYNC_MAX_COMMITS * 48];
  int status = tix_git_run_cmd(cmd, hash_buf, sizeof(hash_buf));
  if (status != 0) { return existing_count; }

  u32 count = existing_count;
  char *line_p = hash_buf;

  while (*line_p != '\0' && count < max_hashes) {
    char *nl = strchr(line_p, '\n');
    if (nl != NULL) { *nl = '\0'; }
    sz hlen = strlen(line_p);
    if (hlen >= 6 && hlen < 48) {
      /* check for duplicates */
      int dup = 0;
      for (u32 di = 0; di < count; di++) {
        if (strcmp(hashes[di], line_p) == 0) { dup = 1; break; }
      }
      if (!dup) {
        memcpy(hashes[count], line_p, hlen);
        hashes[count][hlen] = '\0';
        count++;
      }
    }
    line_p = (nl != NULL) ? nl + 1 : line_p + hlen;
  }

  return count;
}

/* Extract ticket IDs from plan.jsonl content.
   Returns the number of ticket IDs found.
   Only extracts IDs from task/issue/note lines (not accept/reject/delete). */
static u32 extract_ticket_ids(const char *content,
                              char ids[][TIX_MAX_ID_LEN], u32 max_ids) {
  u32 count = 0;
  const char *p = content;
  char line[TIX_MAX_LINE_LEN];

  while (*p != '\0' && count < max_ids) {
    const char *nl = strchr(p, '\n');
    sz line_len;
    if (nl != NULL) {
      line_len = (sz)(nl - p);
    } else {
      line_len = strlen(p);
    }
    if (line_len >= sizeof(line)) { line_len = sizeof(line) - 1; }
    memcpy(line, p, line_len);
    line[line_len] = '\0';
    p = (nl != NULL) ? nl + 1 : p + line_len;

    if (line[0] == '\0') { continue; }

    tix_json_obj_t obj;
    if (tix_json_parse_line(line, &obj) != TIX_OK) { continue; }

    const char *t_val = tix_json_get_str(&obj, "t");
    if (t_val == NULL) { continue; }

    /* only ticket lines (not accept/reject/delete) */
    int is_ticket = (strcmp(t_val, "task") == 0 ||
                     strcmp(t_val, "issue") == 0 ||
                     strcmp(t_val, "note") == 0);
    if (!is_ticket) { continue; }

    const char *id = tix_json_get_str(&obj, "id");
    if (id == NULL || id[0] == '\0') { continue; }

    snprintf(ids[count], TIX_MAX_ID_LEN, "%s", id);
    count++;
  }

  return count;
}

/* Check if an ID exists in the accept/reject/delete markers of a snapshot */
static int has_resolution_marker(const char *content, const char *target_id) {
  const char *p = content;
  char line[TIX_MAX_LINE_LEN];

  while (*p != '\0') {
    const char *nl = strchr(p, '\n');
    sz line_len;
    if (nl != NULL) {
      line_len = (sz)(nl - p);
    } else {
      line_len = strlen(p);
    }
    if (line_len >= sizeof(line)) { line_len = sizeof(line) - 1; }
    memcpy(line, p, line_len);
    line[line_len] = '\0';
    p = (nl != NULL) ? nl + 1 : p + line_len;

    if (line[0] == '\0') { continue; }

    tix_json_obj_t obj;
    if (tix_json_parse_line(line, &obj) != TIX_OK) { continue; }

    const char *t_val = tix_json_get_str(&obj, "t");
    if (t_val == NULL) { continue; }

    int is_marker = (strcmp(t_val, "accept") == 0 ||
                     strcmp(t_val, "reject") == 0 ||
                     strcmp(t_val, "delete") == 0);
    if (!is_marker) { continue; }

    const char *id = tix_json_get_str(&obj, "id");
    if (id != NULL && strcmp(id, target_id) == 0) { return 1; }
  }

  return 0;
}

/* Check if an ID exists in an ID array */
static int id_in_set(char ids[][TIX_MAX_ID_LEN], u32 count,
                     const char *target) {
  for (u32 i = 0; i < count; i++) {
    if (strcmp(ids[i], target) == 0) { return 1; }
  }
  return 0;
}

/* Get commit timestamp via git show */
static i64 get_commit_timestamp(const char *hash) {
  char cmd[128];
  int n = snprintf(cmd, sizeof(cmd),
      "git show -s --format=%%ct %s", hash);
  if (n < 0 || (sz)n >= sizeof(cmd)) { return 0; }

  char buf[32];
  if (tix_git_run_cmd(cmd, buf, sizeof(buf)) != 0) { return 0; }

  return (i64)atol(buf);
}

/* Get file content at a specific commit, trying current path then legacy path */
static int get_snapshot(const char *hash, const char *rel_plan,
                        char *content, sz content_len) {
  char show_cmd[256];
  int n = snprintf(show_cmd, sizeof(show_cmd),
      "git show %s:%s 2>/dev/null", hash, rel_plan);
  if (n < 0 || (sz)n >= sizeof(show_cmd)) { return -1; }

  int status = tix_git_run_cmd(show_cmd, content, content_len);
  if (status != 0) {
    /* try legacy plan.jsonl path */
    n = snprintf(show_cmd, sizeof(show_cmd),
        "git show %s:ralph/plan.jsonl 2>/dev/null", hash);
    if (n < 0 || (sz)n >= sizeof(show_cmd)) { return -1; }
    status = tix_git_run_cmd(show_cmd, content, content_len);
  }

  return status;
}

tix_err_t tix_cmd_sync(tix_ctx_t *ctx, int argc, char **argv) {
  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  /* determine which branch to sync */
  const char *branch = NULL;  /* NULL = current branch (no branch arg to git log) */
  int sync_all = 0;

  for (int i = 0; i < argc; i++) {
    if (strcmp(argv[i], "--all") == 0) {
      sync_all = 1;
    } else {
      if (!tix_git_is_shell_safe(argv[i])) {
        TIX_ERROR("sync: branch name contains unsafe characters: %s",
                  argv[i]);
        return TIX_ERR_INVALID_ARG;
      }
      branch = argv[i];
    }
  }

  const char *rel_plan = ctx->config.plan_file;

  /* collect commit hashes */
  char hashes[TIX_SYNC_MAX_COMMITS][48];
  u32 hash_count = 0;

  if (sync_all) {
    /* sync from all branches: use --all flag */
    char cmd[TIX_MAX_PATH_LEN + 256];
    int n = snprintf(cmd, sizeof(cmd),
        "git log --all --format=%%H --follow -- %s", rel_plan);
    if (n >= 0 && (sz)n < sizeof(cmd)) {
      char hash_buf[TIX_SYNC_MAX_COMMITS * 48];
      int status = tix_git_run_cmd(cmd, hash_buf, sizeof(hash_buf));
      if (status == 0) {
        char *line_p = hash_buf;
        while (*line_p != '\0' && hash_count < TIX_SYNC_MAX_COMMITS) {
          char *nl = strchr(line_p, '\n');
          if (nl != NULL) { *nl = '\0'; }
          sz hlen = strlen(line_p);
          if (hlen >= 6 && hlen < 48) {
            memcpy(hashes[hash_count], line_p, hlen);
            hashes[hash_count][hlen] = '\0';
            hash_count++;
          }
          line_p = (nl != NULL) ? nl + 1 : line_p + hlen;
        }
      }
    }
    /* also check legacy plan.jsonl path */
    if (strcmp(rel_plan, "ralph/plan.jsonl") != 0) {
      n = snprintf(cmd, sizeof(cmd),
          "git log --all --format=%%H --follow -- ralph/plan.jsonl");
      if (n >= 0 && (sz)n < sizeof(cmd)) {
        hash_count = collect_hashes(NULL, "ralph/plan.jsonl",
                                    hashes, TIX_SYNC_MAX_COMMITS,
                                    hash_count);
      }
    }
  } else {
    /* sync from specific branch (or current if branch is NULL) */
    hash_count = collect_hashes(branch, rel_plan,
                                hashes, TIX_SYNC_MAX_COMMITS, 0);
    /* also check legacy plan.jsonl path */
    if (strcmp(rel_plan, "ralph/plan.jsonl") != 0) {
      hash_count = collect_hashes(branch, "ralph/plan.jsonl",
                                  hashes, TIX_SYNC_MAX_COMMITS,
                                  hash_count);
    }
  }

  TIX_INFO("sync: found %u commits touching plan.jsonl", hash_count);

  /* clear database and replay history oldest-first */
  tix_db_clear_tickets(&ctx->db);
  sqlite3_exec(ctx->db.handle, "BEGIN TRANSACTION", NULL, NULL, NULL);

  /* Track ticket IDs from the previous snapshot for compaction detection.
     We use two alternating buffers (prev/curr) to avoid copying. */
  char prev_ids[TIX_SYNC_MAX_IDS][TIX_MAX_ID_LEN];
  char curr_ids[TIX_SYNC_MAX_IDS][TIX_MAX_ID_LEN];
  u32 prev_id_count = 0;

  /* replay in reverse order (oldest first - git log gives newest first) */
  u32 replayed = 0;
  for (u32 i = hash_count; i > 0; i--) {
    char content[TIX_MAX_LINE_LEN * 32];
    if (get_snapshot(hashes[i - 1], rel_plan,
                     content, sizeof(content)) != 0) {
      continue;
    }

    /* Extract ticket IDs from this snapshot */
    u32 curr_id_count = extract_ticket_ids(content,
                                           curr_ids, TIX_SYNC_MAX_IDS);

    /* Detect compaction: tickets in prev but not in curr, and no
       resolution marker in curr. These were silently removed by compact. */
    if (prev_id_count > 0 && curr_id_count > 0) {
      i64 commit_ts = get_commit_timestamp(hashes[i - 1]);

      for (u32 pi = 0; pi < prev_id_count; pi++) {
        if (id_in_set(curr_ids, curr_id_count, prev_ids[pi])) {
          continue;  /* still present */
        }
        /* Ticket disappeared. Check if there's a resolution marker. */
        if (has_resolution_marker(content, prev_ids[pi])) {
          continue;  /* resolved, not compacted */
        }
        /* This ticket was compacted out. Update the cached ticket. */
        tix_ticket_t existing;
        tix_err_t rerr = tix_db_get_ticket(&ctx->db, prev_ids[pi],
                                            &existing);
        if (rerr == TIX_OK && existing.compacted_at == 0) {
          existing.compacted_at = (commit_ts > 0) ?
              commit_ts : (i64)time(NULL);
          tix_db_upsert_ticket(&ctx->db, &existing);
        }
      }
    }

    /* Replay the snapshot content into the cache */
    tix_db_replay_content(&ctx->db, content);
    replayed++;

    /* Swap: curr becomes prev for next iteration */
    memcpy(prev_ids, curr_ids,
           curr_id_count * (sz)TIX_MAX_ID_LEN);
    prev_id_count = curr_id_count;
  }

  sqlite3_exec(ctx->db.handle, "COMMIT", NULL, NULL, NULL);

  /* replay current working tree on top (additive, not nuke) */
  err = tix_db_replay_jsonl_file(&ctx->db, ctx->plan_path);
  if (err != TIX_OK) {
    TIX_WARN("sync: failed to replay current plan.jsonl: %s",
             tix_strerror(err));
  }

  /* update meta */
  char head[TIX_MAX_HASH_LEN];
  if (tix_git_rev_parse_head(head, sizeof(head)) == TIX_OK) {
    tix_db_set_meta(&ctx->db, "last_commit", head);
  }

  /* count orphan references */
  tix_ref_counts_t refs;
  tix_db_count_refs(&ctx->db, &refs);

  u32 total_broken = refs.broken_deps + refs.broken_parents +
                     refs.broken_created_from + refs.broken_supersedes;
  u32 total_stale = refs.stale_deps + refs.stale_parents +
                    refs.stale_created_from + refs.stale_supersedes;

  printf("{\"synced\":true,\"commits\":%u,\"replayed\":%u,"
         "\"broken_refs\":%u,\"stale_refs\":%u}\n",
         hash_count, replayed, total_broken, total_stale);

  return TIX_OK;
}
