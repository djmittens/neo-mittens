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

  /* fallback: if configured plan file doesn't exist, try ralph/plan.jsonl */
  if (stat(ctx->plan_path, &st) != 0) {
    char legacy_path[TIX_MAX_PATH_LEN];
    n = snprintf(legacy_path, sizeof(legacy_path),
                 "%s/ralph/plan.jsonl", ctx->repo_root);
    if (n >= 0 && (sz)n < sizeof(legacy_path) &&
        stat(legacy_path, &st) == 0) {
      snprintf(ctx->plan_path, sizeof(ctx->plan_path), "%s", legacy_path);
      TIX_INFO("using legacy plan file: %s", ctx->plan_path);
    }
  }

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

  int stale = 0;
  tix_err_t err = tix_db_is_stale(&ctx->db, &stale);
  if (err != TIX_OK) { return err; }

  if (stale) {
    TIX_DEBUG("cache is stale, rebuilding from %s", ctx->plan_path);
    err = tix_db_rebuild_from_jsonl(&ctx->db, ctx->plan_path);
    if (err != TIX_OK) { return err; }
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

  /* write all live tickets sorted by ID */
  const char *sql =
    "SELECT id FROM tickets ORDER BY id ASC";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *id = (const char *)sqlite3_column_text(stmt, 0);
      if (id == NULL) { continue; }
      tix_ticket_t ticket;
      if (tix_db_get_ticket(db, id, &ticket) != TIX_OK) { continue; }
      char buf[TIX_MAX_LINE_LEN];
      sz len = tix_json_write_ticket(&ticket, buf, sizeof(buf));
      if (len > 0) { fprintf(fp, "%s\n", buf); }
    }
    sqlite3_finalize(stmt);
  }

  fclose(fp);
  return TIX_OK;
}
