#include "cmd.h"
#include "git.h"
#include "json.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

/*
 * tix compact - rebuild SQLite from full git history of plan.jsonl,
 * then rewrite plan.jsonl with only live tickets sorted by ID.
 *
 * This walks every commit that touched plan.jsonl, replaying each
 * version into the database. The current working tree version is
 * applied last. The result is the complete picture of all tickets
 * that ever existed, with last-write-wins semantics.
 *
 * The rewritten plan.jsonl contains only live (non-deleted,
 * non-accepted) tickets, one per line, sorted by ID for stable
 * git diffs.
 */

/* max commits to walk in history */
#define TIX_COMPACT_MAX_COMMITS 256

/* replay a single version of plan.jsonl content into the database */
static tix_err_t replay_content(tix_db_t *db, const char *content) {
  if (content == NULL || content[0] == '\0') { return TIX_OK; }

  /* process line by line */
  const char *p = content;
  char line[TIX_MAX_LINE_LEN];

  while (*p != '\0') {
    /* extract one line */
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

    if (strcmp(t_val, "task") == 0 || strcmp(t_val, "issue") == 0 ||
        strcmp(t_val, "note") == 0) {
      /* this duplicates the rebuild logic from db.c but operates
         on in-memory content rather than a file */
      tix_ticket_t ticket;
      tix_ticket_init(&ticket);

      if (strcmp(t_val, "task") == 0)  { ticket.type = TIX_TICKET_TASK; }
      if (strcmp(t_val, "issue") == 0) { ticket.type = TIX_TICKET_ISSUE; }
      if (strcmp(t_val, "note") == 0)  { ticket.type = TIX_TICKET_NOTE; }

      const char *id = tix_json_get_str(&obj, "id");
      if (id != NULL) { snprintf(ticket.id, TIX_MAX_ID_LEN, "%s", id); }

      const char *name = tix_json_get_str(&obj, "name");
      if (name != NULL) {
        snprintf(ticket.name, TIX_MAX_NAME_LEN, "%s", name);
      }

      const char *desc = tix_json_get_str(&obj, "desc");
      if (desc != NULL && ticket.name[0] == '\0') {
        snprintf(ticket.name, TIX_MAX_NAME_LEN, "%s", desc);
      }

      const char *s = tix_json_get_str(&obj, "s");
      if (s != NULL) {
        if (strcmp(s, "d") == 0)      { ticket.status = TIX_STATUS_DONE; }
        else if (strcmp(s, "a") == 0) { ticket.status = TIX_STATUS_ACCEPTED; }
      }

      const char *spec = tix_json_get_str(&obj, "spec");
      if (spec != NULL) { snprintf(ticket.spec, TIX_MAX_PATH_LEN, "%s", spec); }

      const char *notes = tix_json_get_str(&obj, "notes");
      if (notes != NULL) { snprintf(ticket.notes, TIX_MAX_DESC_LEN, "%s", notes); }

      const char *accept = tix_json_get_str(&obj, "accept");
      if (accept != NULL) { snprintf(ticket.accept, TIX_MAX_DESC_LEN, "%s", accept); }

      const char *done_at = tix_json_get_str(&obj, "done_at");
      if (done_at != NULL) { snprintf(ticket.done_at, TIX_MAX_HASH_LEN, "%s", done_at); }

      const char *priority = tix_json_get_str(&obj, "priority");
      ticket.priority = tix_priority_from_str(priority);

      const char *parent = tix_json_get_str(&obj, "parent");
      if (parent != NULL) { snprintf(ticket.parent, TIX_MAX_ID_LEN, "%s", parent); }

      const char *cf = tix_json_get_str(&obj, "created_from");
      if (cf != NULL) { snprintf(ticket.created_from, TIX_MAX_ID_LEN, "%s", cf); }

      const char *ss = tix_json_get_str(&obj, "supersedes");
      if (ss != NULL) { snprintf(ticket.supersedes, TIX_MAX_ID_LEN, "%s", ss); }

      const char *kr = tix_json_get_str(&obj, "kill_reason");
      if (kr != NULL) { snprintf(ticket.kill_reason, TIX_MAX_KEYWORD_LEN, "%s", kr); }

      for (u32 fi = 0; fi < obj.field_count; fi++) {
        if (strcmp(obj.fields[fi].key, "deps") != 0) { continue; }
        if (obj.fields[fi].type != TIX_JSON_ARRAY) { continue; }
        for (u32 ai = 0; ai < obj.fields[fi].arr_count &&
             ticket.dep_count < TIX_MAX_DEPS; ai++) {
          snprintf(ticket.deps[ticket.dep_count], TIX_MAX_ID_LEN,
                   "%s", obj.fields[fi].arr_vals[ai]);
          ticket.dep_count++;
        }
        break;
      }

      tix_db_upsert_ticket(db, &ticket);
    } else if (strcmp(t_val, "accept") == 0 ||
               strcmp(t_val, "reject") == 0) {
      tix_tombstone_t ts;
      memset(&ts, 0, sizeof(ts));
      ts.is_accept = (strcmp(t_val, "accept") == 0) ? 1 : 0;

      const char *id = tix_json_get_str(&obj, "id");
      if (id != NULL) { snprintf(ts.id, TIX_MAX_ID_LEN, "%s", id); }

      const char *done_at = tix_json_get_str(&obj, "done_at");
      if (done_at != NULL) { snprintf(ts.done_at, TIX_MAX_HASH_LEN, "%s", done_at); }

      const char *reason = tix_json_get_str(&obj, "reason");
      if (reason != NULL) { snprintf(ts.reason, TIX_MAX_DESC_LEN, "%s", reason); }

      const char *name = tix_json_get_str(&obj, "name");
      if (name != NULL) { snprintf(ts.name, TIX_MAX_NAME_LEN, "%s", name); }

      tix_db_upsert_tombstone(db, &ts);

      if (ts.is_accept && ts.id[0] != '\0') {
        tix_db_delete_ticket(db, ts.id);
      }
    } else if (strcmp(t_val, "delete") == 0) {
      const char *id = tix_json_get_str(&obj, "id");
      if (id != NULL) {
        tix_db_delete_ticket(db, id);
      }
    }
  }

  return TIX_OK;
}

tix_err_t tix_cmd_compact(tix_ctx_t *ctx, int argc, char **argv) {
  TIX_UNUSED(argc);
  TIX_UNUSED(argv);

  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  /* get the relative plan path for git log */
  const char *rel_plan = ctx->config.plan_file;

  /* step 1: get commit hashes that touched plan.jsonl */
  char cmd[TIX_MAX_PATH_LEN + 128];
  int n = snprintf(cmd, sizeof(cmd),
      "git log --format=%%H --follow -- '%s'", rel_plan);
  if (n < 0 || (sz)n >= sizeof(cmd)) { return TIX_ERR_OVERFLOW; }

  /* also check the legacy path */
  char cmd2[TIX_MAX_PATH_LEN + 128];
  n = snprintf(cmd2, sizeof(cmd2),
      "git log --format=%%H --follow -- 'ralph/plan.jsonl'");
  if (n < 0 || (sz)n >= sizeof(cmd2)) { return TIX_ERR_OVERFLOW; }

  /* collect commit hashes */
  char hash_buf[TIX_COMPACT_MAX_COMMITS * 48];
  tix_git_run_cmd(cmd, hash_buf, sizeof(hash_buf));

  /* also collect from legacy path if different */
  if (strcmp(rel_plan, "ralph/plan.jsonl") != 0) {
    sz used = strlen(hash_buf);
    if (used > 0 && used < sizeof(hash_buf) - 1) {
      hash_buf[used] = '\n';
      used++;
    }
    tix_git_run_cmd(cmd2, hash_buf + used, sizeof(hash_buf) - used);
  }

  /* parse hashes into array (reversed - oldest first) */
  char hashes[TIX_COMPACT_MAX_COMMITS][48];
  u32 hash_count = 0;

  char *line_p = hash_buf;
  while (*line_p != '\0' && hash_count < TIX_COMPACT_MAX_COMMITS) {
    char *nl = strchr(line_p, '\n');
    if (nl != NULL) { *nl = '\0'; }
    sz hlen = strlen(line_p);
    if (hlen >= 6 && hlen < 48) {
      /* check for duplicates */
      int dup = 0;
      for (u32 di = 0; di < hash_count; di++) {
        if (strcmp(hashes[di], line_p) == 0) { dup = 1; break; }
      }
      if (!dup) {
        memcpy(hashes[hash_count], line_p, hlen);
        hashes[hash_count][hlen] = '\0';
        hash_count++;
      }
    }
    line_p = (nl != NULL) ? nl + 1 : line_p + hlen;
  }

  TIX_INFO("compact: found %u commits touching plan.jsonl", hash_count);

  /* step 2: clear database and replay history oldest-first */
  sqlite3_exec(ctx->db.handle, "DELETE FROM tickets", NULL, NULL, NULL);
  sqlite3_exec(ctx->db.handle, "DELETE FROM ticket_deps", NULL, NULL, NULL);
  sqlite3_exec(ctx->db.handle, "DELETE FROM tombstones", NULL, NULL, NULL);
  sqlite3_exec(ctx->db.handle, "DELETE FROM keywords", NULL, NULL, NULL);
  sqlite3_exec(ctx->db.handle, "BEGIN TRANSACTION", NULL, NULL, NULL);

  /* replay in reverse order (oldest first - git log gives newest first) */
  for (u32 i = hash_count; i > 0; i--) {
    char show_cmd[128];
    n = snprintf(show_cmd, sizeof(show_cmd),
        "git show %s:%s 2>/dev/null", hashes[i - 1], rel_plan);
    if (n < 0 || (sz)n >= (int)sizeof(show_cmd)) { continue; }

    /* read file content at that commit */
    char content[TIX_MAX_LINE_LEN * 32];
    int status = tix_git_run_cmd(show_cmd, content, sizeof(content));
    if (status != 0) {
      /* try legacy path */
      n = snprintf(show_cmd, sizeof(show_cmd),
          "git show %s:ralph/plan.jsonl 2>/dev/null", hashes[i - 1]);
      if (n < 0 || (sz)n >= (int)sizeof(show_cmd)) { continue; }
      status = tix_git_run_cmd(show_cmd, content, sizeof(content));
      if (status != 0) { continue; }
    }

    replay_content(&ctx->db, content);
  }

  sqlite3_exec(ctx->db.handle, "COMMIT", NULL, NULL, NULL);

  /* step 3: replay current working tree version on top */
  err = tix_db_rebuild_from_jsonl(&ctx->db, ctx->plan_path);
  if (err != TIX_OK) {
    TIX_WARN("compact: failed to replay current plan.jsonl: %s",
             tix_strerror(err));
  }

  /* step 4: rewrite plan.jsonl with only live tickets, sorted by ID */
  err = tix_plan_compact(ctx->plan_path, &ctx->db);
  if (err != TIX_OK) { return err; }

  /* count what we wrote */
  u32 task_count = 0;
  u32 issue_count = 0;
  u32 note_count = 0;
  tix_db_count_tickets(&ctx->db, TIX_TICKET_TASK, TIX_STATUS_PENDING,
                       &task_count);
  u32 done_count = 0;
  tix_db_count_tickets(&ctx->db, TIX_TICKET_TASK, TIX_STATUS_DONE,
                       &done_count);
  task_count += done_count;
  tix_db_count_tickets(&ctx->db, TIX_TICKET_ISSUE, TIX_STATUS_PENDING,
                       &issue_count);
  tix_db_count_tickets(&ctx->db, TIX_TICKET_NOTE, TIX_STATUS_PENDING,
                       &note_count);

  printf("{\"compacted\":true,\"commits\":%u,"
         "\"tasks\":%u,\"issues\":%u,\"notes\":%u}\n",
         hash_count, task_count, issue_count, note_count);
  return TIX_OK;
}
