#include "validate.h"
#include "ticket.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

static void add_error(tix_validation_result_t *r, const char *fmt, ...) {
  if (r->error_count >= 32) { return; }
  va_list va;
  va_start(va, fmt);
  vsnprintf(r->errors[r->error_count], TIX_MAX_NAME_LEN, fmt, va);
  va_end(va);
  r->error_count++;
  r->valid = 0;
}

static void add_warning(tix_validation_result_t *r, const char *fmt, ...) {
  if (r->warning_count >= 32) { return; }
  va_list va;
  va_start(va, fmt);
  vsnprintf(r->warnings[r->warning_count], TIX_MAX_NAME_LEN, fmt, va);
  va_end(va);
  r->warning_count++;
}

tix_err_t tix_validate_history(tix_db_t *db, const char *plan_path,
                               tix_validation_result_t *result) {
  if (db == NULL || result == NULL) { return TIX_ERR_INVALID_ARG; }
  TIX_UNUSED(plan_path);

  memset(result, 0, sizeof(*result));
  result->valid = 1;

  /* check: done tickets have done_at */
  const char *sql_done =
    "SELECT id FROM tickets WHERE status=1 AND "
    "(done_at IS NULL OR done_at='')";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql_done, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *id = (const char *)sqlite3_column_text(stmt, 0);
      if (id != NULL) {
        add_error(result, "task %s is done but has no commit hash", id);
      }
    }
    sqlite3_finalize(stmt);
  }

  /* check: dep references exist */
  const char *sql_deps =
    "SELECT d.ticket_id, d.dep_id FROM ticket_deps d "
    "LEFT JOIN tickets t ON d.dep_id = t.id "
    "WHERE t.id IS NULL";
  rc = sqlite3_prepare_v2(db->handle, sql_deps, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *tid = (const char *)sqlite3_column_text(stmt, 0);
      const char *did = (const char *)sqlite3_column_text(stmt, 1);
      if (tid != NULL && did != NULL) {
        add_error(result, "task %s depends on %s which does not exist",
                  tid, did);
      }
    }
    sqlite3_finalize(stmt);
  }

  /* check: circular deps (iterative BFS per ticket) */
  tix_ticket_t tickets[TIX_MAX_BATCH];
  u32 count = 0;
  tix_db_list_tickets(db, TIX_TICKET_TASK, TIX_STATUS_PENDING,
                      tickets, &count, TIX_MAX_BATCH);

  for (u32 i = 0; i < count; i++) {
    /* re-fetch with deps loaded (list_tickets doesn't load deps) */
    tix_ticket_t full_ticket;
    if (tix_db_get_ticket(db, tickets[i].id, &full_ticket) != TIX_OK) {
      continue;
    }
    if (full_ticket.dep_count == 0) { continue; }

    /* BFS from ticket following deps */
    char visited[TIX_MAX_BATCH][TIX_MAX_ID_LEN];
    u32 v_count = 0;
    char queue[TIX_MAX_BATCH][TIX_MAX_ID_LEN];
    u32 q_head = 0;
    u32 q_tail = 0;

    for (u32 d = 0; d < full_ticket.dep_count; d++) {
      snprintf(queue[q_tail], TIX_MAX_ID_LEN, "%s", full_ticket.deps[d]);
      q_tail++;
      if (q_tail >= TIX_MAX_BATCH) { break; }
    }

    int cycle_found = 0;
    while (q_head < q_tail && !cycle_found) {
      char current[TIX_MAX_ID_LEN];
      snprintf(current, TIX_MAX_ID_LEN, "%s", queue[q_head]);
      q_head++;

      if (strcmp(current, tickets[i].id) == 0) {
        add_error(result, "circular dependency detected: %s",
                  tickets[i].id);
        cycle_found = 1;
        break;
      }

      /* check if already visited */
      int already = 0;
      for (u32 v = 0; v < v_count; v++) {
        if (strcmp(visited[v], current) == 0) { already = 1; break; }
      }
      if (already) { continue; }
      if (v_count >= TIX_MAX_BATCH) { break; }

      snprintf(visited[v_count], TIX_MAX_ID_LEN, "%s", current);
      v_count++;

      /* enqueue deps of current */
      tix_ticket_t dep_ticket;
      if (tix_db_get_ticket(db, current, &dep_ticket) == TIX_OK) {
        for (u32 d = 0; d < dep_ticket.dep_count && q_tail < TIX_MAX_BATCH; d++) {
          snprintf(queue[q_tail], TIX_MAX_ID_LEN, "%s", dep_ticket.deps[d]);
          q_tail++;
        }
      }
    }
  }

  /* check: tickets have names */
  const char *sql_noname =
    "SELECT id FROM tickets WHERE name IS NULL OR name=''";
  rc = sqlite3_prepare_v2(db->handle, sql_noname, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *id = (const char *)sqlite3_column_text(stmt, 0);
      if (id != NULL) {
        add_warning(result, "ticket %s has no name", id);
      }
    }
    sqlite3_finalize(stmt);
  }

  return TIX_OK;
}

tix_err_t tix_validate_print(const tix_validation_result_t *r,
                             char *buf, sz buf_len) {
  if (r == NULL || buf == NULL) { return TIX_ERR_INVALID_ARG; }

  char *p = buf;
  char *end = buf + buf_len;

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "Validation %s\n",
                 r->valid ? "PASSED" : "FAILED");
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "============\n");

  for (u32 i = 0; i < r->error_count; i++) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   "ERROR: %s\n", r->errors[i]);
  }
  for (u32 i = 0; i < r->warning_count; i++) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
                   "WARN:  %s\n", r->warnings[i]);
  }

  if (r->error_count == 0 && r->warning_count == 0) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "No issues found.\n");
  }

  return TIX_OK;
}
