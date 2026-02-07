#include "cmd.h"
#include "git.h"
#include "json.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

static tix_err_t query_full(tix_ctx_t *ctx) {
  tix_ticket_t tickets[TIX_MAX_BATCH];
  u32 count = 0;

  printf("{\"tasks\":{\"pending\":[");
  tix_db_list_tickets(&ctx->db, TIX_TICKET_TASK, TIX_STATUS_PENDING,
                      tickets, &count, TIX_MAX_BATCH);
  for (u32 i = 0; i < count; i++) {
    if (i > 0) { printf(","); }
    char buf[TIX_MAX_LINE_LEN];
    tix_json_write_ticket(&tickets[i], buf, sizeof(buf));
    printf("%s", buf);
  }

  printf("],\"done\":[");
  count = 0;
  tix_db_list_tickets(&ctx->db, TIX_TICKET_TASK, TIX_STATUS_DONE,
                      tickets, &count, TIX_MAX_BATCH);
  for (u32 i = 0; i < count; i++) {
    if (i > 0) { printf(","); }
    char buf[TIX_MAX_LINE_LEN];
    tix_json_write_ticket(&tickets[i], buf, sizeof(buf));
    printf("%s", buf);
  }

  printf("]},\"issues\":[");
  count = 0;
  tix_db_list_tickets(&ctx->db, TIX_TICKET_ISSUE, TIX_STATUS_PENDING,
                      tickets, &count, TIX_MAX_BATCH);
  for (u32 i = 0; i < count; i++) {
    if (i > 0) { printf(","); }
    char buf[TIX_MAX_LINE_LEN];
    tix_json_write_ticket(&tickets[i], buf, sizeof(buf));
    printf("%s", buf);
  }

  printf("],\"notes\":[");
  count = 0;
  tix_db_list_tickets(&ctx->db, TIX_TICKET_NOTE, TIX_STATUS_PENDING,
                      tickets, &count, TIX_MAX_BATCH);
  for (u32 i = 0; i < count; i++) {
    if (i > 0) { printf(","); }
    char buf[TIX_MAX_LINE_LEN];
    tix_json_write_ticket(&tickets[i], buf, sizeof(buf));
    printf("%s", buf);
  }

  char branch[TIX_MAX_BRANCH_LEN];
  tix_git_current_branch(branch, sizeof(branch));

  char head[TIX_MAX_HASH_LEN];
  tix_git_rev_parse_head(head, sizeof(head));

  printf("],\"meta\":{\"branch\":\"%s\",\"commit\":\"%s\"}}\n",
         branch, head);

  return TIX_OK;
}

static tix_err_t query_tasks(tix_ctx_t *ctx, int show_done) {
  tix_ticket_t tickets[TIX_MAX_BATCH];
  u32 count = 0;
  tix_status_e status = show_done ? TIX_STATUS_DONE : TIX_STATUS_PENDING;

  tix_db_list_tickets(&ctx->db, TIX_TICKET_TASK, status,
                      tickets, &count, TIX_MAX_BATCH);
  printf("[");
  for (u32 i = 0; i < count; i++) {
    if (i > 0) { printf(","); }
    char buf[TIX_MAX_LINE_LEN];
    tix_json_write_ticket(&tickets[i], buf, sizeof(buf));
    printf("%s", buf);
  }
  printf("]\n");
  return TIX_OK;
}

static tix_err_t query_issues(tix_ctx_t *ctx) {
  tix_ticket_t tickets[TIX_MAX_BATCH];
  u32 count = 0;
  tix_db_list_tickets(&ctx->db, TIX_TICKET_ISSUE, TIX_STATUS_PENDING,
                      tickets, &count, TIX_MAX_BATCH);
  printf("[");
  for (u32 i = 0; i < count; i++) {
    if (i > 0) { printf(","); }
    char buf[TIX_MAX_LINE_LEN];
    tix_json_write_ticket(&tickets[i], buf, sizeof(buf));
    printf("%s", buf);
  }
  printf("]\n");
  return TIX_OK;
}

tix_err_t tix_cmd_query(tix_ctx_t *ctx, int argc, char **argv) {
  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  if (argc < 1) { return query_full(ctx); }

  const char *sub = argv[0];
  if (strcmp(sub, "tasks") == 0) {
    int show_done = (argc >= 2 && strcmp(argv[1], "--done") == 0);
    return query_tasks(ctx, show_done);
  }
  if (strcmp(sub, "issues") == 0) { return query_issues(ctx); }

  fprintf(stderr, "error: unknown query subcommand: %s\n", sub);
  return TIX_ERR_INVALID_ARG;
}
