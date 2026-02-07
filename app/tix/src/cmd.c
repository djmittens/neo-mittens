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

  char db_path[TIX_MAX_PATH_LEN];
  n = snprintf(db_path, sizeof(db_path), "%s/cache.db", ctx->tix_dir);
  if (n < 0 || (sz)n >= sizeof(db_path)) { return TIX_ERR_OVERFLOW; }

  struct stat st;
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

tix_err_t tix_plan_rewrite(const char *plan_path, tix_db_t *db) {
  if (plan_path == NULL || db == NULL) { return TIX_ERR_INVALID_ARG; }

  FILE *fp = fopen(plan_path, "w");
  if (fp == NULL) { return TIX_ERR_IO; }

  /* write all tickets */
  tix_ticket_t tickets[TIX_MAX_BATCH];
  u32 count = 0;

  tix_ticket_type_e types[] = {
    TIX_TICKET_TASK, TIX_TICKET_ISSUE, TIX_TICKET_NOTE
  };
  tix_status_e statuses[] = {
    TIX_STATUS_PENDING, TIX_STATUS_DONE, TIX_STATUS_ACCEPTED
  };

  for (int ti = 0; ti < 3; ti++) {
    for (int si = 0; si < 3; si++) {
      count = 0;
      tix_db_list_tickets(db, types[ti], statuses[si],
                          tickets, &count, TIX_MAX_BATCH);
      for (u32 i = 0; i < count; i++) {
        char buf[TIX_MAX_LINE_LEN];
        sz len = tix_json_write_ticket(&tickets[i], buf, sizeof(buf));
        if (len > 0) { fprintf(fp, "%s\n", buf); }
      }
    }
  }

  /* write tombstones */
  tix_tombstone_t tombstones[TIX_MAX_BATCH];
  for (int accept = 0; accept <= 1; accept++) {
    count = 0;
    tix_db_list_tombstones(db, accept, tombstones, &count, TIX_MAX_BATCH);
    for (u32 i = 0; i < count; i++) {
      char buf[TIX_MAX_LINE_LEN];
      sz len = tix_json_write_tombstone(&tombstones[i], buf, sizeof(buf));
      if (len > 0) { fprintf(fp, "%s\n", buf); }
    }
  }

  fclose(fp);
  return TIX_OK;
}
