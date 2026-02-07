#include "report.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

/* ================================================================
 * Progress report (existing)
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

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "Progress Report\n");
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "===============\n");

  u32 completed = r->done_tasks + r->accepted_tasks;
  int pct = (r->total_tasks > 0) ? (int)(completed * 100 / r->total_tasks) : 0;

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                 "Tasks: %u total, %u pending, %u done, %u accepted (%d%%)\n",
                 r->total_tasks, r->pending_tasks, r->done_tasks,
                 r->accepted_tasks, pct);

  if (r->total_issues > 0) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   "Issues: %u open\n", r->total_issues);
  }
  if (r->total_notes > 0) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   "Notes: %u\n", r->total_notes);
  }
  if (r->blocked_count > 0) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   "Blocked: %u (waiting on dependencies)\n",
                   r->blocked_count);
  }

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "\nBy Priority:\n");
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                 "  High:   %u\n", r->high_priority);
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                 "  Medium: %u\n", r->medium_priority);
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                 "  Low:    %u\n", r->low_priority);

  return TIX_OK;
}

/* ================================================================
 * Velocity report
 * ================================================================ */

tix_err_t tix_report_velocity(tix_db_t *db, tix_velocity_report_t *report) {
  if (db == NULL || report == NULL) { return TIX_ERR_INVALID_ARG; }
  memset(report, 0, sizeof(*report));

  /* Aggregate over tasks that are done or accepted (status 1 or 2)
     and have type=task (type 0). Only count tasks that have at least
     some telemetry data (cost > 0 or tokens_in > 0 or iterations > 0). */
  const char *sql =
    "SELECT "
    "  COUNT(*),"
    "  COALESCE(SUM(cost), 0.0),"
    "  COALESCE(SUM(tokens_in), 0),"
    "  COALESCE(SUM(tokens_out), 0),"
    "  COALESCE(AVG(CASE WHEN updated_at > created_at AND created_at > 0 "
    "    THEN updated_at - created_at ELSE NULL END), 0.0),"
    "  COALESCE(AVG(CASE WHEN iterations > 0 "
    "    THEN iterations ELSE NULL END), 0.0),"
    "  COALESCE(SUM(retries), 0),"
    "  COALESCE(SUM(kill_count), 0)"
    " FROM tickets"
    " WHERE type=0 AND status IN (1,2)";

  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    TIX_ERROR("velocity query failed: %s", sqlite3_errmsg(db->handle));
    return TIX_ERR_DB;
  }

  if (sqlite3_step(stmt) == SQLITE_ROW) {
    report->completed = (u32)sqlite3_column_int(stmt, 0);
    report->total_cost = sqlite3_column_double(stmt, 1);
    report->total_tokens_in = sqlite3_column_int64(stmt, 2);
    report->total_tokens_out = sqlite3_column_int64(stmt, 3);
    report->avg_cycle_secs = sqlite3_column_double(stmt, 4);
    report->avg_iterations = sqlite3_column_double(stmt, 5);
    report->total_retries = (u32)sqlite3_column_int(stmt, 6);
    report->total_kills = (u32)sqlite3_column_int(stmt, 7);
  }
  sqlite3_finalize(stmt);

  if (report->completed > 0) {
    report->avg_cost = report->total_cost / (double)report->completed;
  }

  return TIX_OK;
}

tix_err_t tix_report_velocity_print(const tix_velocity_report_t *r,
                                    char *buf, sz buf_len) {
  if (r == NULL || buf == NULL) { return TIX_ERR_INVALID_ARG; }

  char *p = buf;
  char *end = buf + buf_len;

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "Velocity Report\n");
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "===============\n");

  if (r->completed == 0) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   "No completed tasks with telemetry data.\n");
    return TIX_OK;
  }

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                 "Completed tasks: %u\n", r->completed);

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "\nCost:\n");
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                 "  Total:   $%.4f\n", r->total_cost);
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                 "  Average: $%.4f/task\n", r->avg_cost);

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "\nTokens:\n");
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                 "  Input:  %lld\n", (long long)r->total_tokens_in);
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                 "  Output: %lld\n", (long long)r->total_tokens_out);

  if (r->avg_cycle_secs > 0.0) {
    /* display as human-readable duration */
    double secs = r->avg_cycle_secs;
    if (secs < 60.0) {
      TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                     "\nAvg cycle time: %.0fs\n", secs);
    } else if (secs < 3600.0) {
      TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                     "\nAvg cycle time: %.1fm\n", secs / 60.0);
    } else {
      TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                     "\nAvg cycle time: %.1fh\n", secs / 3600.0);
    }
  }

  if (r->avg_iterations > 0.0) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   "Avg iterations: %.1f\n", r->avg_iterations);
  }

  if (r->total_retries > 0) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   "Total retries:  %u\n", r->total_retries);
  }
  if (r->total_kills > 0) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   "Total kills:    %u\n", r->total_kills);
  }

  return TIX_OK;
}

/* ================================================================
 * Actors (per-author) report
 * ================================================================ */

tix_err_t tix_report_actors(tix_db_t *db, tix_actors_report_t *report) {
  if (db == NULL || report == NULL) { return TIX_ERR_INVALID_ARG; }
  memset(report, 0, sizeof(*report));

  const char *sql =
    "SELECT "
    "  author,"
    "  COUNT(*),"
    "  SUM(CASE WHEN status IN (1,2) THEN 1 ELSE 0 END),"
    "  SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END),"
    "  COALESCE(SUM(cost), 0.0),"
    "  COALESCE(AVG(CASE WHEN iterations > 0 "
    "    THEN iterations ELSE NULL END), 0.0)"
    " FROM tickets"
    " WHERE type=0 AND author IS NOT NULL AND author != ''"
    " GROUP BY author"
    " ORDER BY COUNT(*) DESC";

  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    TIX_ERROR("actors query failed: %s", sqlite3_errmsg(db->handle));
    return TIX_ERR_DB;
  }

  while (sqlite3_step(stmt) == SQLITE_ROW &&
         report->count < TIX_MAX_REPORT_ACTORS) {
    tix_actor_entry_t *a = &report->actors[report->count];
    memset(a, 0, sizeof(*a));

    const char *name = (const char *)sqlite3_column_text(stmt, 0);
    if (name != NULL) {
      snprintf(a->author, sizeof(a->author), "%s", name);
    }
    a->total = (u32)sqlite3_column_int(stmt, 1);
    a->completed = (u32)sqlite3_column_int(stmt, 2);
    a->pending = (u32)sqlite3_column_int(stmt, 3);
    a->total_cost = sqlite3_column_double(stmt, 4);
    a->avg_iterations = sqlite3_column_double(stmt, 5);

    if (a->completed > 0) {
      a->avg_cost = a->total_cost / (double)a->completed;
    }

    report->count++;
  }
  sqlite3_finalize(stmt);

  return TIX_OK;
}

tix_err_t tix_report_actors_print(const tix_actors_report_t *r,
                                  char *buf, sz buf_len) {
  if (r == NULL || buf == NULL) { return TIX_ERR_INVALID_ARG; }

  char *p = buf;
  char *end = buf + buf_len;

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "Actors Report\n");
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "=============\n");

  if (r->count == 0) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   "No tasks with author information.\n");
    return TIX_OK;
  }

  /* header */
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                 "%-20s %5s %5s %5s %10s %10s %6s\n",
                 "Author", "Total", "Done", "Pend",
                 "Cost", "Avg Cost", "Iters");
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                 "%-20s %5s %5s %5s %10s %10s %6s\n",
                 "--------------------", "-----", "-----", "-----",
                 "----------", "----------", "------");

  for (u32 i = 0; i < r->count; i++) {
    const tix_actor_entry_t *a = &r->actors[i];
    /* truncate long author names for display (truncation intended) */
    char display_name[21];
    memset(display_name, 0, sizeof(display_name));
    memcpy(display_name, a->author,
           strlen(a->author) < 20 ? strlen(a->author) : 20);

    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   "%-20s %5u %5u %5u %10.4f %10.4f %6.1f\n",
                   display_name, a->total, a->completed, a->pending,
                   a->total_cost, a->avg_cost, a->avg_iterations);
  }

  return TIX_OK;
}

/* ================================================================
 * Models (per-model) report
 * ================================================================ */

tix_err_t tix_report_models(tix_db_t *db, tix_models_report_t *report) {
  if (db == NULL || report == NULL) { return TIX_ERR_INVALID_ARG; }
  memset(report, 0, sizeof(*report));

  const char *sql =
    "SELECT "
    "  model,"
    "  COUNT(*),"
    "  COALESCE(SUM(cost), 0.0),"
    "  COALESCE(SUM(tokens_in), 0),"
    "  COALESCE(SUM(tokens_out), 0),"
    "  COALESCE(AVG(CASE WHEN iterations > 0 "
    "    THEN iterations ELSE NULL END), 0.0)"
    " FROM tickets"
    " WHERE type=0 AND status IN (1,2)"
    "   AND model IS NOT NULL AND model != ''"
    " GROUP BY model"
    " ORDER BY SUM(cost) DESC";

  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    TIX_ERROR("models query failed: %s", sqlite3_errmsg(db->handle));
    return TIX_ERR_DB;
  }

  while (sqlite3_step(stmt) == SQLITE_ROW &&
         report->count < TIX_MAX_REPORT_MODELS) {
    tix_model_entry_t *m = &report->models[report->count];
    memset(m, 0, sizeof(*m));

    const char *name = (const char *)sqlite3_column_text(stmt, 0);
    if (name != NULL) {
      snprintf(m->model, sizeof(m->model), "%s", name);
    }
    m->total = (u32)sqlite3_column_int(stmt, 1);
    m->total_cost = sqlite3_column_double(stmt, 2);
    m->total_tokens_in = sqlite3_column_int64(stmt, 3);
    m->total_tokens_out = sqlite3_column_int64(stmt, 4);
    m->avg_iterations = sqlite3_column_double(stmt, 5);

    if (m->total > 0) {
      m->avg_cost = m->total_cost / (double)m->total;
    }

    report->count++;
  }
  sqlite3_finalize(stmt);

  return TIX_OK;
}

tix_err_t tix_report_models_print(const tix_models_report_t *r,
                                  char *buf, sz buf_len) {
  if (r == NULL || buf == NULL) { return TIX_ERR_INVALID_ARG; }

  char *p = buf;
  char *end = buf + buf_len;

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "Models Report\n");
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "=============\n");

  if (r->count == 0) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   "No completed tasks with model information.\n");
    return TIX_OK;
  }

  /* header */
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                 "%-30s %5s %10s %10s %10s %10s %6s\n",
                 "Model", "Tasks", "Cost", "Avg Cost",
                 "Tokens In", "Tokens Out", "Iters");
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                 "%-30s %5s %10s %10s %10s %10s %6s\n",
                 "------------------------------", "-----",
                 "----------", "----------",
                 "----------", "----------", "------");

  for (u32 i = 0; i < r->count; i++) {
    const tix_model_entry_t *m = &r->models[i];
    /* truncate long model names for display (truncation intended) */
    char display_model[31];
    memset(display_model, 0, sizeof(display_model));
    memcpy(display_model, m->model,
           strlen(m->model) < 30 ? strlen(m->model) : 30);

    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   "%-30s %5u %10.4f %10.4f %10lld %10lld %6.1f\n",
                   display_model, m->total, m->total_cost, m->avg_cost,
                   (long long)m->total_tokens_in,
                   (long long)m->total_tokens_out,
                   m->avg_iterations);
  }

  return TIX_OK;
}
