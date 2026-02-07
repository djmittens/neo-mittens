#pragma once

#include "types.h"
#include "common.h"
#include "db.h"
#include "config.h"

typedef struct {
  tix_db_t db;
  tix_config_t config;
  char tix_dir[TIX_MAX_PATH_LEN];
  char plan_path[TIX_MAX_PATH_LEN];
  char repo_root[TIX_MAX_PATH_LEN];
  int initialized;
} tix_ctx_t;

tix_err_t tix_ctx_init(tix_ctx_t *ctx);
tix_err_t tix_ctx_close(tix_ctx_t *ctx);
tix_err_t tix_ctx_ensure_cache(tix_ctx_t *ctx);

/* command handlers - each returns TIX_OK or error */
tix_err_t tix_cmd_init(int argc, char **argv);
tix_err_t tix_cmd_task(tix_ctx_t *ctx, int argc, char **argv);
tix_err_t tix_cmd_issue(tix_ctx_t *ctx, int argc, char **argv);
tix_err_t tix_cmd_note(tix_ctx_t *ctx, int argc, char **argv);
tix_err_t tix_cmd_query(tix_ctx_t *ctx, int argc, char **argv);
tix_err_t tix_cmd_status(tix_ctx_t *ctx, int argc, char **argv);
tix_err_t tix_cmd_log(tix_ctx_t *ctx, int argc, char **argv);
tix_err_t tix_cmd_tree(tix_ctx_t *ctx, int argc, char **argv);
tix_err_t tix_cmd_report(tix_ctx_t *ctx, int argc, char **argv);
tix_err_t tix_cmd_search(tix_ctx_t *ctx, int argc, char **argv);
tix_err_t tix_cmd_validate(tix_ctx_t *ctx, int argc, char **argv);
tix_err_t tix_cmd_batch(tix_ctx_t *ctx, int argc, char **argv);

/* command handlers - sync and compact */
tix_err_t tix_cmd_sync(tix_ctx_t *ctx, int argc, char **argv);
tix_err_t tix_cmd_compact(tix_ctx_t *ctx, int argc, char **argv);

/* plan.jsonl I/O (append-only) */
tix_err_t tix_plan_append_ticket(const char *plan_path,
                                 const tix_ticket_t *ticket);
tix_err_t tix_plan_append_tombstone(const char *plan_path,
                                    const tix_tombstone_t *ts);
tix_err_t tix_plan_append_delete(const char *plan_path, const char *id);

/* plan.jsonl compaction (called by tix compact) */
tix_err_t tix_plan_compact(const char *plan_path, tix_db_t *db);
