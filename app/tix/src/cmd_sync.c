#include "cmd.h"
#include "git.h"
#include "json.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

/*
 * tix sync - walk git history and replay plan.jsonl into the cache.
 *
 * By default syncs the current branch. Accepts an optional branch name
 * or --all to sync all branches.
 *
 * The cache is cumulative: tickets from all synced branches accumulate.
 * Only tix sync clears and rebuilds; normal operations are additive.
 */

/* max commits to walk in history */
#define TIX_SYNC_MAX_COMMITS 512

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
    /* also check legacy path */
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
    /* also check legacy path */
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

  /* replay in reverse order (oldest first - git log gives newest first) */
  u32 replayed = 0;
  for (u32 i = hash_count; i > 0; i--) {
    /* try current plan path first */
    char show_cmd[256];
    int n = snprintf(show_cmd, sizeof(show_cmd),
        "git show %s:%s 2>/dev/null", hashes[i - 1], rel_plan);
    if (n < 0 || (sz)n >= sizeof(show_cmd)) { continue; }

    char content[TIX_MAX_LINE_LEN * 32];
    int status = tix_git_run_cmd(show_cmd, content, sizeof(content));
    if (status != 0) {
      /* try legacy path */
      n = snprintf(show_cmd, sizeof(show_cmd),
          "git show %s:ralph/plan.jsonl 2>/dev/null", hashes[i - 1]);
      if (n < 0 || (sz)n >= sizeof(show_cmd)) { continue; }
      status = tix_git_run_cmd(show_cmd, content, sizeof(content));
      if (status != 0) { continue; }
    }

    tix_db_replay_content(&ctx->db, content);
    replayed++;
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
