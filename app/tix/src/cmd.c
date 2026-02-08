#include "cmd.h"
#include "git.h"
#include "json.h"
#include "log.h"

#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

tix_err_t tix_ctx_init(tix_ctx_t *ctx) {
  if (ctx == NULL) { return TIX_ERR_INVALID_ARG; }
  memset(ctx, 0, sizeof(*ctx));

  tix_err_t err = tix_git_toplevel(ctx->repo_root, sizeof(ctx->repo_root));
  if (err != TIX_OK) {
    fprintf(stderr, "error: not in a git repository\n");
    return err;
  }

  int n;
  n = snprintf(ctx->tix_dir, sizeof(ctx->tix_dir), "%s/.tix", ctx->repo_root);
  if (n < 0 || (sz)n >= sizeof(ctx->tix_dir)) { return TIX_ERR_OVERFLOW; }

  char config_path[TIX_MAX_PATH_LEN];
  n = snprintf(config_path, sizeof(config_path), "%s/config.toml", ctx->tix_dir);
  if (n < 0 || (sz)n >= sizeof(config_path)) { return TIX_ERR_OVERFLOW; }

  tix_config_defaults(&ctx->config);
  tix_config_load(&ctx->config, config_path);

  n = snprintf(ctx->plan_path, sizeof(ctx->plan_path),
               "%s/%s", ctx->repo_root, ctx->config.plan_file);
  if (n < 0 || (sz)n >= sizeof(ctx->plan_path)) { return TIX_ERR_OVERFLOW; }

  struct stat st;

  char db_path[TIX_MAX_PATH_LEN];
  n = snprintf(db_path, sizeof(db_path), "%s/cache.db", ctx->tix_dir);
  if (n < 0 || (sz)n >= sizeof(db_path)) { return TIX_ERR_OVERFLOW; }

  if (stat(ctx->tix_dir, &st) != 0) {
    fprintf(stderr, "error: .tix/ not found. Run 'tix init' first.\n");
    return TIX_ERR_NOT_FOUND;
  }

  err = tix_db_open(&ctx->db, db_path);
  if (err != TIX_OK) { return err; }

  err = tix_db_init_schema(&ctx->db);
  if (err != TIX_OK) { return err; }

  ctx->initialized = 1;
  return TIX_OK;
}

tix_err_t tix_ctx_close(tix_ctx_t *ctx) {
  if (ctx == NULL) { return TIX_ERR_INVALID_ARG; }
  if (ctx->initialized) {
    tix_db_close(&ctx->db);
    ctx->initialized = 0;
  }
  return TIX_OK;
}

tix_err_t tix_ctx_ensure_cache(tix_ctx_t *ctx) {
  if (ctx == NULL) { return TIX_ERR_INVALID_ARG; }

  /* check if plan.jsonl has changed since last replay (mtime-based) */
  struct stat st;
  if (stat(ctx->plan_path, &st) != 0) {
    /* file doesn't exist yet - nothing to replay */
    return TIX_OK;
  }

  char mtime_str[32];
  snprintf(mtime_str, sizeof(mtime_str), "%ld", (long)st.st_mtime);

  char cached_mtime[32];
  tix_db_get_meta(&ctx->db, "plan_mtime", cached_mtime, sizeof(cached_mtime));

  char size_str[32];
  snprintf(size_str, sizeof(size_str), "%ld", (long)st.st_size);

  char cached_size[32];
  tix_db_get_meta(&ctx->db, "plan_size", cached_size, sizeof(cached_size));

  if (strcmp(mtime_str, cached_mtime) != 0 ||
      strcmp(size_str, cached_size) != 0) {
    TIX_DEBUG("plan.jsonl changed, replaying from %s", ctx->plan_path);
    tix_err_t err = tix_db_replay_jsonl_file(&ctx->db, ctx->plan_path);
    if (err != TIX_OK) { return err; }
    tix_db_set_meta(&ctx->db, "plan_mtime", mtime_str);
    tix_db_set_meta(&ctx->db, "plan_size", size_str);
  }

  return TIX_OK;
}

tix_err_t tix_plan_append_ticket(const char *plan_path,
                                 const tix_ticket_t *ticket) {
  if (plan_path == NULL || ticket == NULL) { return TIX_ERR_INVALID_ARG; }

  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(ticket, buf, sizeof(buf));
  if (len == 0) { return TIX_ERR_OVERFLOW; }

  FILE *fp = fopen(plan_path, "a");
  if (fp == NULL) { return TIX_ERR_IO; }

  fprintf(fp, "%s\n", buf);
  fclose(fp);
  return TIX_OK;
}

tix_err_t tix_plan_append_tombstone(const char *plan_path,
                                    const tix_tombstone_t *ts) {
  if (plan_path == NULL || ts == NULL) { return TIX_ERR_INVALID_ARG; }

  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_tombstone(ts, buf, sizeof(buf));
  if (len == 0) { return TIX_ERR_OVERFLOW; }

  FILE *fp = fopen(plan_path, "a");
  if (fp == NULL) { return TIX_ERR_IO; }

  fprintf(fp, "%s\n", buf);
  fclose(fp);
  return TIX_OK;
}

/* Check if a JSONL line type is owned by tix (vs external orchestrator) */
static int is_tix_owned_type(const char *line) {
  /* Quick check: find "t":" pattern and extract type value.
     tix owns: task, issue, note, accept, reject.
     Everything else (spec, stage, config) is preserved as-is. */
  const char *p = line;
  while (*p != '\0') {
    if (*p == '"' && *(p + 1) == 't' && *(p + 2) == '"') {
      /* found "t" key, skip to value */
      p += 3;
      while (*p == ' ' || *p == ':') { p++; }
      if (*p != '"') { return 0; }
      p++; /* skip opening quote */
      if (strncmp(p, "task\"", 5) == 0) { return 1; }
      if (strncmp(p, "issue\"", 6) == 0) { return 1; }
      if (strncmp(p, "note\"", 5) == 0) { return 1; }
      if (strncmp(p, "accept\"", 7) == 0) { return 1; }
      if (strncmp(p, "reject\"", 7) == 0) { return 1; }
      if (strncmp(p, "delete\"", 7) == 0) { return 1; }
      return 0;
    }
    p++;
  }
  return 0;
}

/* Max bytes for preserved (non-tix) lines from plan.jsonl */
#define TIX_PRESERVED_BUF_LEN (TIX_MAX_LINE_LEN * 16)

static sz collect_preserved_lines(const char *plan_path,
                                  char *buf, sz buf_len) {
  FILE *fp = fopen(plan_path, "r");
  if (fp == NULL) { return 0; }

  sz used = 0;
  char line[TIX_MAX_LINE_LEN];
  while (fgets(line, (int)sizeof(line), fp) != NULL) {
    if (line[0] == '\0' || line[0] == '\n') { continue; }
    if (is_tix_owned_type(line)) { continue; }

    /* preserve this line */
    sz line_len = strlen(line);
    if (used + line_len < buf_len) {
      memcpy(buf + used, line, line_len);
      used += line_len;
    }
  }
  buf[used] = '\0';
  fclose(fp);
  return used;
}

tix_err_t tix_plan_append_delete(const char *plan_path, const char *id) {
  if (plan_path == NULL || id == NULL) { return TIX_ERR_INVALID_ARG; }

  FILE *fp = fopen(plan_path, "a");
  if (fp == NULL) { return TIX_ERR_IO; }

  fprintf(fp, "{\"t\":\"delete\",\"id\":\"%s\"}\n", id);
  fclose(fp);
  return TIX_OK;
}

/* Write a ticket JSON line to a file, appending ticket_meta as "meta":{...}.
   The ticket JSON ends with "}", so we replace it with ","meta":{...}}".
   If no metadata exists, writes the ticket JSON as-is. */
static void write_ticket_with_meta(FILE *fp, tix_db_t *db,
                                   const tix_ticket_t *ticket) {
  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(ticket, buf, sizeof(buf));
  if (len == 0) { return; }

  /* query ticket_meta for this ticket */
  const char *sql =
    "SELECT key, value_text, value_num FROM ticket_meta "
    "WHERE ticket_id=? ORDER BY key";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    fprintf(fp, "%s\n", buf);
    return;
  }
  sqlite3_bind_text(stmt, 1, ticket->id, -1, SQLITE_STATIC);

  /* collect meta entries */
  char meta_buf[TIX_MAX_LINE_LEN / 2];
  char *mp = meta_buf;
  char *mend = meta_buf + sizeof(meta_buf);
  int meta_count = 0;

  while (sqlite3_step(stmt) == SQLITE_ROW) {
    const char *key = (const char *)sqlite3_column_text(stmt, 0);
    const char *vtext = (const char *)sqlite3_column_text(stmt, 1);
    if (key == NULL) { continue; }

    if (meta_count > 0 && mp < mend - 1) {
      *mp++ = ',';
    }
    char esc_key[TIX_MAX_KEYWORD_LEN * 2];
    tix_json_escape(key, esc_key, sizeof(esc_key));

    if (vtext != NULL && vtext[0] != '\0') {
      char esc_val[TIX_MAX_NAME_LEN * 2];
      tix_json_escape(vtext, esc_val, sizeof(esc_val));
      int n = snprintf(mp, (sz)(mend - mp), "\"%s\":\"%s\"",
                       esc_key, esc_val);
      if (n > 0 && mp + n < mend) { mp += n; }
    } else {
      double vnum = sqlite3_column_double(stmt, 2);
      /* write integer if it's a whole number */
      if (vnum == (double)(i64)vnum && vnum >= -1e15 && vnum <= 1e15) {
        int n = snprintf(mp, (sz)(mend - mp), "\"%s\":%lld",
                         esc_key, (long long)(i64)vnum);
        if (n > 0 && mp + n < mend) { mp += n; }
      } else {
        int n = snprintf(mp, (sz)(mend - mp), "\"%s\":%.6g",
                         esc_key, vnum);
        if (n > 0 && mp + n < mend) { mp += n; }
      }
    }
    meta_count++;
  }
  sqlite3_finalize(stmt);

  if (meta_count == 0) {
    fprintf(fp, "%s\n", buf);
    return;
  }

  /* replace trailing "}" with ","meta":{...}}" */
  if (len > 0 && buf[len - 1] == '}') {
    buf[len - 1] = '\0';
    fprintf(fp, "%s,\"meta\":{%s}}\n", buf, meta_buf);
  } else {
    fprintf(fp, "%s\n", buf);
  }
}

tix_err_t tix_plan_compact(const char *plan_path, tix_db_t *db) {
  if (plan_path == NULL || db == NULL) { return TIX_ERR_INVALID_ARG; }

  /* first pass: collect non-tix lines to preserve */
  char preserved[TIX_PRESERVED_BUF_LEN];
  sz preserved_len = collect_preserved_lines(plan_path,
                                             preserved, sizeof(preserved));

  FILE *fp = fopen(plan_path, "w");
  if (fp == NULL) { return TIX_ERR_IO; }

  /* write preserved orchestration records first */
  if (preserved_len > 0) {
    fwrite(preserved, 1, preserved_len, fp);
  }

  /* write only live tickets (pending + done) sorted by ID.
     Resolved tickets (accepted/rejected/deleted) stay in the cache
     but are not written to the compacted plan.jsonl.
     Exception: resolved tickets that have never been committed are
     preserved to prevent data loss (populated by cmd_compact.c). */
  const char *sql =
    "SELECT id FROM tickets WHERE status < 2 ORDER BY id ASC";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *id = (const char *)sqlite3_column_text(stmt, 0);
      if (id == NULL) { continue; }
      tix_ticket_t ticket;
      if (tix_db_get_ticket(db, id, &ticket) != TIX_OK) { continue; }
      write_ticket_with_meta(fp, db, &ticket);
    }
    sqlite3_finalize(stmt);
  }

  /* write uncommitted-resolved tickets and their tombstones.
     The _compact_uncommitted temp table is populated by cmd_compact.c
     before calling this function. If the table doesn't exist (e.g.
     tix_plan_compact called directly), this is a no-op. */
  const char *uncommitted_sql =
    "SELECT id FROM _compact_uncommitted ORDER BY id ASC";
  stmt = NULL;
  rc = sqlite3_prepare_v2(db->handle, uncommitted_sql, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *id = (const char *)sqlite3_column_text(stmt, 0);
      if (id == NULL) { continue; }

      /* write the ticket line (with its current resolved status) */
      tix_ticket_t ticket;
      if (tix_db_get_ticket(db, id, &ticket) != TIX_OK) { continue; }
      write_ticket_with_meta(fp, db, &ticket);

      /* write the corresponding tombstone (accept/reject) if it exists */
      tix_tombstone_t ts;
      memset(&ts, 0, sizeof(ts));
      const char *ts_sql =
        "SELECT id, done_at, reason, name, is_accept, timestamp "
        "FROM tombstones WHERE id=?";
      sqlite3_stmt *ts_stmt = NULL;
      int trc = sqlite3_prepare_v2(db->handle, ts_sql, -1, &ts_stmt, NULL);
      if (trc == SQLITE_OK) {
        sqlite3_bind_text(ts_stmt, 1, id, -1, SQLITE_STATIC);
        if (sqlite3_step(ts_stmt) == SQLITE_ROW) {
          const char *ts_id = (const char *)sqlite3_column_text(ts_stmt, 0);
          const char *ts_done = (const char *)sqlite3_column_text(ts_stmt, 1);
          const char *ts_reason = (const char *)sqlite3_column_text(ts_stmt, 2);
          const char *ts_name = (const char *)sqlite3_column_text(ts_stmt, 3);
          int ts_is_accept = sqlite3_column_int(ts_stmt, 4);
          if (ts_id != NULL) {
            snprintf(ts.id, TIX_MAX_ID_LEN, "%s", ts_id);
          }
          if (ts_done != NULL) {
            snprintf(ts.done_at, TIX_MAX_HASH_LEN, "%s", ts_done);
          }
          if (ts_reason != NULL) {
            snprintf(ts.reason, TIX_MAX_DESC_LEN, "%s", ts_reason);
          }
          if (ts_name != NULL) {
            snprintf(ts.name, TIX_MAX_NAME_LEN, "%s", ts_name);
          }
          ts.is_accept = ts_is_accept;
          ts.timestamp = sqlite3_column_int64(ts_stmt, 5);

          char ts_buf[TIX_MAX_LINE_LEN];
          sz ts_len = tix_json_write_tombstone(&ts, ts_buf, sizeof(ts_buf));
          if (ts_len > 0) { fprintf(fp, "%s\n", ts_buf); }
        }
        sqlite3_finalize(ts_stmt);
      }

      /* for deleted tickets (no tombstone), write a delete marker */
      if (ticket.status == TIX_STATUS_DELETED) {
        fprintf(fp, "{\"t\":\"delete\",\"id\":\"%s\"}\n", id);
      }
    }
    sqlite3_finalize(stmt);
  }

  fclose(fp);
  return TIX_OK;
}
