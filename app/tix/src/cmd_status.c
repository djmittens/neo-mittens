#include "cmd.h"
#include "color.h"
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

  /* Header */
  printf("%s%stix status%s\n", tix_c(TIX_BOLD), tix_c(TIX_CYAN),
         tix_c(TIX_RESET));
  printf("%s==========%s\n", tix_c(TIX_DIM), tix_c(TIX_RESET));

  /* Branch info */
  printf("Branch: %s%s%s %s(%s)%s\n",
         tix_c(TIX_BRIGHT_CYAN), branch, tix_c(TIX_RESET),
         tix_c(TIX_DIM), head, tix_c(TIX_RESET));
  printf("Main:   %s\n\n", ctx->config.main_branch);

  /* Task summary with progress bar */
  u32 completed = report.done_tasks + report.accepted_tasks;
  int pct = (report.total_tasks > 0)
              ? (int)(completed * 100 / report.total_tasks) : 0;

  printf("Tasks: %s%s%u%s total, %s%u pending%s, "
         "%s%u done%s, %s%s%u accepted%s %s(%d%%)%s\n",
         tix_c(TIX_BOLD), tix_c(TIX_WHITE),
         report.total_tasks, tix_c(TIX_RESET),
         tix_c(TIX_YELLOW), report.pending_tasks, tix_c(TIX_RESET),
         tix_c(TIX_GREEN), report.done_tasks, tix_c(TIX_RESET),
         tix_c(TIX_BOLD), tix_c(TIX_BRIGHT_GREEN),
         report.accepted_tasks, tix_c(TIX_RESET),
         tix_c(TIX_DIM), pct, tix_c(TIX_RESET));

  /* Progress bar */
  if (report.total_tasks > 0) {
    char bar[128];
    tix_progress_bar(bar, sizeof(bar), pct, 30);
    printf("       %s %d%%\n", bar, pct);
  }

  if (report.total_issues > 0) {
    printf("%s%sIssues: %u open%s\n",
           tix_c(TIX_BOLD), tix_c(TIX_MAGENTA),
           report.total_issues, tix_c(TIX_RESET));
  }
  if (report.total_notes > 0) {
    printf("Notes: %u\n", report.total_notes);
  }
  if (report.blocked_count > 0) {
    printf("%s%sBlocked: %u%s (waiting on dependencies)\n",
           tix_c(TIX_BOLD), tix_c(TIX_RED),
           report.blocked_count, tix_c(TIX_RESET));
  }

  /* show recent pending tasks */
  tix_ticket_t tasks[5];
  u32 count = 0;
  tix_db_list_tickets(&ctx->db, TIX_TICKET_TASK, TIX_STATUS_PENDING,
                      tasks, &count, 5);

  if (count > 0) {
    printf("\n%s%sPending Tasks:%s\n", tix_c(TIX_BOLD),
           tix_c(TIX_YELLOW), tix_c(TIX_RESET));
    for (u32 i = 0; i < count; i++) {
      const char *prio_str = "";
      const char *prio_color = "";
      const char *reset = tix_c(TIX_RESET);
      if (tasks[i].priority == TIX_PRIORITY_HIGH) {
        prio_str = " [HIGH]";
        prio_color = tix_c(TIX_BRIGHT_RED);
      } else if (tasks[i].priority == TIX_PRIORITY_MEDIUM) {
        prio_str = " [MED]";
        prio_color = tix_c(TIX_YELLOW);
      }
      printf("  %s%s%s %s%s%s%s",
             tix_c(TIX_DIM), tasks[i].id, tix_c(TIX_RESET),
             tasks[i].name,
             prio_color, prio_str, reset);
      if (tasks[i].label_count > 0) {
        printf(" %s[", tix_c(TIX_DIM));
        for (u32 li = 0; li < tasks[i].label_count; li++) {
          if (li > 0) { printf(","); }
          printf("%s", tasks[i].labels[li]);
        }
        printf("]%s", tix_c(TIX_RESET));
      }
      printf("\n");
    }
  }

  /* show issues */
  tix_ticket_t issues[5];
  count = 0;
  tix_db_list_tickets(&ctx->db, TIX_TICKET_ISSUE, TIX_STATUS_PENDING,
                      issues, &count, 5);

  if (count > 0) {
    printf("\n%s%sOpen Issues:%s\n", tix_c(TIX_BOLD),
           tix_c(TIX_MAGENTA), tix_c(TIX_RESET));
    for (u32 i = 0; i < count; i++) {
      printf("  %s%s%s %s\n",
             tix_c(TIX_DIM), issues[i].id, tix_c(TIX_RESET),
             issues[i].name);
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
      printf("\n%sReferences:%s\n", tix_c(TIX_BOLD), tix_c(TIX_RESET));
      if (total_broken > 0) {
        printf("  %s%s%u broken%s (run tix sync to search history)\n",
               tix_c(TIX_BOLD), tix_c(TIX_RED),
               total_broken, tix_c(TIX_RESET));
      }
      if (total_stale > 0) {
        printf("  %s%u stale%s (target accepted/resolved)\n",
               tix_c(TIX_YELLOW), total_stale, tix_c(TIX_RESET));
      }
    }
  }

  return TIX_OK;
}
