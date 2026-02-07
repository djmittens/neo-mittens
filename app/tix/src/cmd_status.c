#include "cmd.h"
#include "git.h"
#include "report.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

tix_err_t tix_cmd_status(tix_ctx_t *ctx, int argc, char **argv) {
  TIX_UNUSED(argc);
  TIX_UNUSED(argv);

  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  char branch[TIX_MAX_BRANCH_LEN];
  tix_git_current_branch(branch, sizeof(branch));

  char head[TIX_MAX_HASH_LEN];
  tix_git_rev_parse_head(head, sizeof(head));

  tix_report_t report;
  err = tix_report_generate(&ctx->db, &report);
  if (err != TIX_OK) { return err; }

  printf("tix status\n");
  printf("==========\n");
  printf("Branch: %s (%s)\n", branch, head);
  printf("Main:   %s\n\n", ctx->config.main_branch);

  char buf[TIX_MAX_LINE_LEN * 2];
  err = tix_report_print(&report, buf, sizeof(buf));
  if (err == TIX_OK) { printf("%s", buf); }

  /* show recent pending tasks */
  tix_ticket_t tasks[5];
  u32 count = 0;
  tix_db_list_tickets(&ctx->db, TIX_TICKET_TASK, TIX_STATUS_PENDING,
                      tasks, &count, 5);

  if (count > 0) {
    printf("\nPending Tasks:\n");
    for (u32 i = 0; i < count; i++) {
      const char *prio = "";
      if (tasks[i].priority == TIX_PRIORITY_HIGH) { prio = " [HIGH]"; }
      if (tasks[i].priority == TIX_PRIORITY_MEDIUM) { prio = " [MED]"; }
      printf("  %s %s%s\n", tasks[i].id, tasks[i].name, prio);
    }
  }

  /* show issues */
  tix_ticket_t issues[5];
  count = 0;
  tix_db_list_tickets(&ctx->db, TIX_TICKET_ISSUE, TIX_STATUS_PENDING,
                      issues, &count, 5);

  if (count > 0) {
    printf("\nOpen Issues:\n");
    for (u32 i = 0; i < count; i++) {
      printf("  %s %s\n", issues[i].id, issues[i].name);
    }
  }

  return TIX_OK;
}
