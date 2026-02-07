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

/* check if dep_id appears more than once in deps */
static int count_dep(const tix_ticket_t *t, const char *dep_id) {
  int n = 0;
  for (u32 i = 0; i < t->dep_count; i++) {
    if (strcmp(t->deps[i], dep_id) == 0) { n++; }
  }
  return n;
}

tix_err_t tix_validate_history(tix_db_t *db, const char *plan_path,
                               tix_validation_result_t *result) {
  if (db == NULL || result == NULL) { return TIX_ERR_INVALID_ARG; }
  TIX_UNUSED(plan_path);

  memset(result, 0, sizeof(*result));
  result->valid = 1;

  /* === ERROR checks === */

  /* 1. done tickets must have done_at commit hash */
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

  /* 2. dep references must exist (orphan dependencies) */
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

  /* 3. deps must point to tasks, not issues or notes */
  const char *sql_dep_type =
    "SELECT d.ticket_id, d.dep_id, t.type FROM ticket_deps d "
    "JOIN tickets t ON d.dep_id = t.id WHERE t.type != 0";
  rc = sqlite3_prepare_v2(db->handle, sql_dep_type, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *tid = (const char *)sqlite3_column_text(stmt, 0);
      const char *did = (const char *)sqlite3_column_text(stmt, 1);
      if (tid != NULL && did != NULL) {
        add_error(result,
                  "task %s depends on %s which is not a task", tid, did);
      }
    }
    sqlite3_finalize(stmt);
  }

  /* 4. parent references must exist */
  const char *sql_parent =
    "SELECT t.id, t.parent FROM tickets t "
    "WHERE t.parent IS NOT NULL AND t.parent != '' "
    "AND NOT EXISTS (SELECT 1 FROM tickets p WHERE p.id = t.parent)";
  rc = sqlite3_prepare_v2(db->handle, sql_parent, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *tid = (const char *)sqlite3_column_text(stmt, 0);
      const char *pid = (const char *)sqlite3_column_text(stmt, 1);
      if (tid != NULL && pid != NULL) {
        add_error(result,
                  "task %s has parent %s which does not exist", tid, pid);
      }
    }
    sqlite3_finalize(stmt);
  }

  /* 5. created_from references must exist */
  const char *sql_cf =
    "SELECT t.id, t.created_from FROM tickets t "
    "WHERE t.created_from IS NOT NULL AND t.created_from != '' "
    "AND NOT EXISTS (SELECT 1 FROM tickets c WHERE c.id = t.created_from)";
  rc = sqlite3_prepare_v2(db->handle, sql_cf, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *tid = (const char *)sqlite3_column_text(stmt, 0);
      const char *cid = (const char *)sqlite3_column_text(stmt, 1);
      if (tid != NULL && cid != NULL) {
        add_error(result,
                  "task %s has created_from %s which does not exist",
                  tid, cid);
      }
    }
    sqlite3_finalize(stmt);
  }

  /* 6. supersedes references must exist */
  const char *sql_ss =
    "SELECT t.id, t.supersedes FROM tickets t "
    "WHERE t.supersedes IS NOT NULL AND t.supersedes != '' "
    "AND NOT EXISTS (SELECT 1 FROM tickets s WHERE s.id = t.supersedes)";
  rc = sqlite3_prepare_v2(db->handle, sql_ss, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *tid = (const char *)sqlite3_column_text(stmt, 0);
      const char *sid = (const char *)sqlite3_column_text(stmt, 1);
      if (tid != NULL && sid != NULL) {
        add_error(result,
                  "task %s supersedes %s which does not exist", tid, sid);
      }
    }
    sqlite3_finalize(stmt);
  }

  /* 7. circular deps (iterative BFS per task) */
  tix_ticket_t tickets[TIX_MAX_BATCH];
  u32 count = 0;
  tix_db_list_tickets(db, TIX_TICKET_TASK, TIX_STATUS_PENDING,
                      tickets, &count, TIX_MAX_BATCH);

  /* also check done tasks for cycles */
  tix_ticket_t done_tickets[TIX_MAX_BATCH];
  u32 done_count = 0;
  tix_db_list_tickets(db, TIX_TICKET_TASK, TIX_STATUS_DONE,
                      done_tickets, &done_count, TIX_MAX_BATCH);

  /* merge into tickets array (up to TIX_MAX_BATCH total) */
  for (u32 d = 0; d < done_count && count < TIX_MAX_BATCH; d++) {
    tickets[count] = done_tickets[d];
    count++;
  }

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

    for (u32 d2 = 0; d2 < full_ticket.dep_count; d2++) {
      if (q_tail >= TIX_MAX_BATCH) { break; }
      snprintf(queue[q_tail], TIX_MAX_ID_LEN, "%s",
               full_ticket.deps[d2]);
      q_tail++;
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
        if (strcmp(visited[v], current) == 0) {
          already = 1;
          break;
        }
      }
      if (already) { continue; }
      if (v_count >= TIX_MAX_BATCH) { break; }

      snprintf(visited[v_count], TIX_MAX_ID_LEN, "%s", current);
      v_count++;

      /* enqueue deps of current */
      tix_ticket_t dep_ticket;
      if (tix_db_get_ticket(db, current, &dep_ticket) == TIX_OK) {
        for (u32 d2 = 0;
             d2 < dep_ticket.dep_count && q_tail < TIX_MAX_BATCH;
             d2++) {
          snprintf(queue[q_tail], TIX_MAX_ID_LEN, "%s",
                   dep_ticket.deps[d2]);
          q_tail++;
        }
      }
    }
  }

  /* 8. ticket ID format validation */
  const char *sql_ids = "SELECT id FROM tickets";
  rc = sqlite3_prepare_v2(db->handle, sql_ids, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *id = (const char *)sqlite3_column_text(stmt, 0);
      if (id != NULL && !tix_is_valid_ticket_id(id)) {
        add_error(result,
                  "ticket %s has invalid ID format "
                  "(expected {t,i,n}-{hex})", id);
      }
    }
    sqlite3_finalize(stmt);
  }

  /* 9. duplicate deps - re-fetch all tasks with deps */
  for (u32 i = 0; i < count; i++) {
    tix_ticket_t ft;
    if (tix_db_get_ticket(db, tickets[i].id, &ft) != TIX_OK) {
      continue;
    }
    for (u32 d2 = 0; d2 < ft.dep_count; d2++) {
      if (count_dep(&ft, ft.deps[d2]) > 1) {
        add_error(result, "task %s has duplicate dependency %s",
                  ft.id, ft.deps[d2]);
        break; /* one error per ticket is enough */
      }
    }
  }

  /* === WARNING checks === */

  /* 10. tickets must have names */
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

  /* 11. tasks should have acceptance criteria */
  const char *sql_noacc =
    "SELECT id FROM tickets WHERE type=0 AND "
    "(accept IS NULL OR accept='')";
  rc = sqlite3_prepare_v2(db->handle, sql_noacc, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *id = (const char *)sqlite3_column_text(stmt, 0);
      if (id != NULL) {
        add_warning(result,
                    "task %s has no acceptance criteria", id);
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
