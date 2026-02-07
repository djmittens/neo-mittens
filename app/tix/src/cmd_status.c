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

  u32 completed = report.done_tasks + report.accepted_tasks;
  int pct = (report.total_tasks > 0)
              ? (int)(completed * 100 / report.total_tasks) : 0;
  printf("Tasks: %u total, %u pending, %u done, %u accepted (%d%%)\n",
         report.total_tasks, report.pending_tasks, report.done_tasks,
         report.accepted_tasks, pct);

  if (report.total_issues > 0) {
    printf("Issues: %u open\n", report.total_issues);
  }
  if (report.total_notes > 0) {
    printf("Notes: %u\n", report.total_notes);
  }
  if (report.blocked_count > 0) {
    printf("Blocked: %u (waiting on dependencies)\n", report.blocked_count);
  }

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

  /* show broken reference summary */
  tix_ref_counts_t refs;
  if (tix_db_count_refs(&ctx->db, &refs) == TIX_OK) {
    u32 total_broken = refs.broken_deps + refs.broken_parents +
                       refs.broken_created_from + refs.broken_supersedes;
    u32 total_stale = refs.stale_deps + refs.stale_parents +
                      refs.stale_created_from + refs.stale_supersedes;
    if (total_broken > 0 || total_stale > 0) {
      printf("\nReferences:\n");
      if (total_broken > 0) {
        printf("  %u broken (run tix sync to search history)\n",
               total_broken);
      }
      if (total_stale > 0) {
        printf("  %u stale (target accepted/resolved)\n", total_stale);
      }
    }
  }

  return TIX_OK;
}
