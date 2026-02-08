#include "report.h"
#include "color.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

/* ================================================================
 * Progress report — generic ticket counts and priority breakdown.
 * This is the only report tix provides natively.  Domain-specific
 * reports (velocity, models, actors) belong in the orchestrator
 * (e.g. Ralph) and use TQL queries against ticket_meta.
 * ================================================================ */

tix_err_t tix_report_generate(tix_db_t *db, tix_report_t *report) {
  if (db == NULL || report == NULL) { return TIX_ERR_INVALID_ARG; }
  memset(report, 0, sizeof(*report));

  tix_db_count_tickets(db, TIX_TICKET_TASK, TIX_STATUS_PENDING,
                       &report->pending_tasks);
  tix_db_count_tickets(db, TIX_TICKET_TASK, TIX_STATUS_DONE,
                       &report->done_tasks);
  tix_db_count_tickets(db, TIX_TICKET_TASK, TIX_STATUS_ACCEPTED,
                       &report->accepted_tasks);
  report->total_tasks = report->pending_tasks + report->done_tasks +
                        report->accepted_tasks;

  tix_db_count_tickets(db, TIX_TICKET_ISSUE, TIX_STATUS_PENDING,
                       &report->total_issues);
  tix_db_count_tickets(db, TIX_TICKET_NOTE, TIX_STATUS_PENDING,
                       &report->total_notes);

  /* count by priority */
  const char *prio_sql =
    "SELECT priority, COUNT(*) FROM tickets "
    "WHERE type=0 AND status=0 GROUP BY priority";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, prio_sql, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      int prio = sqlite3_column_int(stmt, 0);
      u32 cnt = (u32)sqlite3_column_int(stmt, 1);
      if (prio == 3) { report->high_priority = cnt; }
      if (prio == 2) { report->medium_priority = cnt; }
      if (prio == 1) { report->low_priority = cnt; }
    }
    sqlite3_finalize(stmt);
  }

  /* count blocked (has deps where dep status != done/accepted) */
  const char *blocked_sql =
    "SELECT COUNT(DISTINCT d.ticket_id) FROM ticket_deps d "
    "JOIN tickets t ON d.dep_id = t.id "
    "WHERE t.status = 0";
  rc = sqlite3_prepare_v2(db->handle, blocked_sql, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      report->blocked_count = (u32)sqlite3_column_int(stmt, 0);
    }
    sqlite3_finalize(stmt);
  }

  return TIX_OK;
}

tix_err_t tix_report_print(const tix_report_t *r, char *buf, sz buf_len) {
  if (r == NULL || buf == NULL) { return TIX_ERR_INVALID_ARG; }

  char *p = buf;
  char *end = buf + buf_len;

  TIX_BUF_COLOR(p, end, TIX_ERR_OVERFLOW, TIX_BOLD TIX_CYAN,
                "Progress Report\n");
  TIX_BUF_COLOR(p, end, TIX_ERR_OVERFLOW, TIX_DIM, "===============\n");

  u32 completed = r->done_tasks + r->accepted_tasks;
  int pct = (r->total_tasks > 0) ? (int)(completed * 100 / r->total_tasks) : 0;

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "Tasks: ");
  TIX_BUF_COLOR(p, end, TIX_ERR_OVERFLOW, TIX_BOLD, "%u", r->total_tasks);
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, " total, ");
  TIX_BUF_COLOR(p, end, TIX_ERR_OVERFLOW, TIX_YELLOW, "%u pending",
                r->pending_tasks);
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, ", ");
  TIX_BUF_COLOR(p, end, TIX_ERR_OVERFLOW, TIX_GREEN, "%u done",
                r->done_tasks);
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, ", ");
  TIX_BUF_COLOR(p, end, TIX_ERR_OVERFLOW, TIX_BRIGHT_GREEN, "%u accepted",
                r->accepted_tasks);
  TIX_BUF_COLOR(p, end, TIX_ERR_OVERFLOW, TIX_DIM, " (%d%%)", pct);
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "\n");

  if (r->total_issues > 0) {
    TIX_BUF_COLOR(p, end, TIX_ERR_OVERFLOW, TIX_MAGENTA,
                  "Issues: %u open", r->total_issues);
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "\n");
  }
  if (r->total_notes > 0) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   "Notes: %u\n", r->total_notes);
  }
  if (r->blocked_count > 0) {
    TIX_BUF_COLOR(p, end, TIX_ERR_OVERFLOW, TIX_BOLD TIX_RED,
                  "Blocked: %u", r->blocked_count);
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   " (waiting on dependencies)\n");
  }

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "\nBy Priority:\n");
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "  ");
  TIX_BUF_COLOR(p, end, TIX_ERR_OVERFLOW, TIX_BRIGHT_RED,
                "High:   %u", r->high_priority);
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "\n  ");
  TIX_BUF_COLOR(p, end, TIX_ERR_OVERFLOW, TIX_YELLOW,
                "Medium: %u", r->medium_priority);
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "\n  ");
  TIX_BUF_COLOR(p, end, TIX_ERR_OVERFLOW, TIX_DIM,
                "Low:    %u", r->low_priority);
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "\n");

  return TIX_OK;
}
