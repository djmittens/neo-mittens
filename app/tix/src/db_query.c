/*
 * db_query.c — Ticket query functions (get, list, count).
 *
 * Split from db.c to respect the 1000-line file limit.
 * Contains row_to_ticket() and all SELECT-based operations.
 */

#include "db.h"
#include "log.h"

#include <string.h>

/* Find column index by name in a prepared statement. Returns -1 if not found.
   This makes row_to_ticket() immune to column ordering changes. */
static int col_idx(sqlite3_stmt *stmt, const char *name) {
  int n = sqlite3_column_count(stmt);
  for (int i = 0; i < n; i++) {
    const char *cname = sqlite3_column_name(stmt, i);
    if (cname != NULL && strcmp(cname, name) == 0) { return i; }
  }
  return -1;
}

/* Read a TEXT column by name into a fixed buffer. No-op if column not found. */
static void col_text(sqlite3_stmt *stmt, int idx, char *out, sz out_len) {
  if (idx < 0) { return; }
  const char *v = (const char *)sqlite3_column_text(stmt, idx);
  if (v != NULL) { snprintf(out, out_len, "%s", v); }
}

static void row_to_ticket(sqlite3_stmt *stmt, tix_ticket_t *t) {
  tix_ticket_init(t);

  col_text(stmt, col_idx(stmt, "id"), t->id, TIX_MAX_ID_LEN);

  int ci;
  ci = col_idx(stmt, "type");
  if (ci >= 0) { t->type = (tix_ticket_type_e)sqlite3_column_int(stmt, ci); }
  ci = col_idx(stmt, "status");
  if (ci >= 0) { t->status = (tix_status_e)sqlite3_column_int(stmt, ci); }
  ci = col_idx(stmt, "priority");
  if (ci >= 0) { t->priority = (tix_priority_e)sqlite3_column_int(stmt, ci); }

  col_text(stmt, col_idx(stmt, "name"), t->name, TIX_MAX_NAME_LEN);
  col_text(stmt, col_idx(stmt, "spec"), t->spec, TIX_MAX_PATH_LEN);
  col_text(stmt, col_idx(stmt, "notes"), t->notes, TIX_MAX_DESC_LEN);
  col_text(stmt, col_idx(stmt, "accept"), t->accept, TIX_MAX_DESC_LEN);
  col_text(stmt, col_idx(stmt, "done_at"), t->done_at, TIX_MAX_HASH_LEN);
  col_text(stmt, col_idx(stmt, "branch"), t->branch, TIX_MAX_BRANCH_LEN);
  col_text(stmt, col_idx(stmt, "parent"), t->parent, TIX_MAX_ID_LEN);
  col_text(stmt, col_idx(stmt, "created_from"), t->created_from, TIX_MAX_ID_LEN);
  col_text(stmt, col_idx(stmt, "supersedes"), t->supersedes, TIX_MAX_ID_LEN);
  col_text(stmt, col_idx(stmt, "kill_reason"), t->kill_reason, TIX_MAX_KEYWORD_LEN);
  col_text(stmt, col_idx(stmt, "created_from_name"), t->created_from_name, TIX_MAX_NAME_LEN);
  col_text(stmt, col_idx(stmt, "supersedes_name"), t->supersedes_name, TIX_MAX_NAME_LEN);
  col_text(stmt, col_idx(stmt, "supersedes_reason"), t->supersedes_reason, TIX_MAX_KEYWORD_LEN);

  ci = col_idx(stmt, "created_at");
  if (ci >= 0) { t->created_at = sqlite3_column_int64(stmt, ci); }
  ci = col_idx(stmt, "updated_at");
  if (ci >= 0) { t->updated_at = sqlite3_column_int64(stmt, ci); }

  /* identity & attribution */
  col_text(stmt, col_idx(stmt, "author"), t->author, TIX_MAX_NAME_LEN);
  col_text(stmt, col_idx(stmt, "assigned"), t->assigned, TIX_MAX_NAME_LEN);
  col_text(stmt, col_idx(stmt, "completed_at"), t->completed_at,
           sizeof(t->completed_at));
  ci = col_idx(stmt, "cost");
  if (ci >= 0) { t->cost = sqlite3_column_double(stmt, ci); }
  ci = col_idx(stmt, "tokens_in");
  if (ci >= 0) { t->tokens_in = sqlite3_column_int64(stmt, ci); }
  ci = col_idx(stmt, "tokens_out");
  if (ci >= 0) { t->tokens_out = sqlite3_column_int64(stmt, ci); }
  ci = col_idx(stmt, "iterations");
  if (ci >= 0) { t->iterations = (i32)sqlite3_column_int(stmt, ci); }
  col_text(stmt, col_idx(stmt, "model"), t->model, TIX_MAX_NAME_LEN);
  ci = col_idx(stmt, "retries");
  if (ci >= 0) { t->retries = (i32)sqlite3_column_int(stmt, ci); }
  ci = col_idx(stmt, "kill_count");
  if (ci >= 0) { t->kill_count = (i32)sqlite3_column_int(stmt, ci); }
  ci = col_idx(stmt, "resolved_at");
  if (ci >= 0) { t->resolved_at = sqlite3_column_int64(stmt, ci); }
  ci = col_idx(stmt, "compacted_at");
  if (ci >= 0) { t->compacted_at = sqlite3_column_int64(stmt, ci); }
}

/* Load deps and labels for a single ticket from junction tables. */
static void load_deps_labels(tix_db_t *db, tix_ticket_t *out) {
  sqlite3_stmt *stmt = NULL;
  int rc;

  const char *dep_sql =
      "SELECT dep_id FROM ticket_deps WHERE ticket_id=?";
  rc = sqlite3_prepare_v2(db->handle, dep_sql, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, out->id, -1, SQLITE_STATIC);
    while (sqlite3_step(stmt) == SQLITE_ROW && out->dep_count < TIX_MAX_DEPS) {
      const char *dep = (const char *)sqlite3_column_text(stmt, 0);
      if (dep != NULL) {
        snprintf(out->deps[out->dep_count], TIX_MAX_ID_LEN, "%s", dep);
        out->dep_count++;
      }
    }
    sqlite3_finalize(stmt);
  }

  const char *label_sql =
      "SELECT label FROM ticket_labels WHERE ticket_id=? ORDER BY label";
  rc = sqlite3_prepare_v2(db->handle, label_sql, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, out->id, -1, SQLITE_STATIC);
    while (sqlite3_step(stmt) == SQLITE_ROW &&
           out->label_count < TIX_MAX_LABELS) {
      const char *lbl = (const char *)sqlite3_column_text(stmt, 0);
      if (lbl != NULL) {
        snprintf(out->labels[out->label_count], TIX_MAX_KEYWORD_LEN,
                 "%s", lbl);
        out->label_count++;
      }
    }
    sqlite3_finalize(stmt);
  }
}

tix_err_t tix_db_get_ticket(tix_db_t *db, const char *id, tix_ticket_t *out) {
  if (db == NULL || id == NULL || out == NULL) {
    return TIX_ERR_INVALID_ARG;
  }

  const char *sql = "SELECT * FROM tickets WHERE id=?";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_ERR_DB; }

  sqlite3_bind_text(stmt, 1, id, -1, SQLITE_STATIC);
  rc = sqlite3_step(stmt);
  if (rc != SQLITE_ROW) {
    sqlite3_finalize(stmt);
    return TIX_ERR_NOT_FOUND;
  }

  row_to_ticket(stmt, out);
  sqlite3_finalize(stmt);

  load_deps_labels(db, out);
  return TIX_OK;
}

int tix_db_ticket_exists(tix_db_t *db, const char *id) {
  tix_ticket_t tmp;
  return tix_db_get_ticket(db, id, &tmp) == TIX_OK;
}

tix_err_t tix_db_list_tickets(tix_db_t *db, tix_ticket_type_e type,
                              tix_status_e status,
                              tix_ticket_t *out, u32 *count, u32 max) {
  if (db == NULL || out == NULL || count == NULL) {
    return TIX_ERR_INVALID_ARG;
  }

  const char *sql = "SELECT * FROM tickets WHERE type=? AND status=? "
                    "ORDER BY priority DESC, created_at ASC";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_ERR_DB; }

  sqlite3_bind_int(stmt, 1, (int)type);
  sqlite3_bind_int(stmt, 2, (int)status);

  *count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW && *count < max) {
    row_to_ticket(stmt, &out[*count]);
    (*count)++;
  }
  sqlite3_finalize(stmt);
  return TIX_OK;
}

tix_err_t tix_db_list_tickets_filtered(tix_db_t *db,
                                       const tix_db_filter_t *filter,
                                       tix_ticket_t *out, u32 *count,
                                       u32 max) {
  if (db == NULL || filter == NULL || out == NULL || count == NULL) {
    return TIX_ERR_INVALID_ARG;
  }

  /* Build SQL dynamically with up to 5 filter clauses.
     Max SQL length: ~512 bytes is plenty. */
  char sql[512];
  char *p = sql;
  char *end = sql + sizeof(sql);
  int bind_idx = 0;

  /* Track bind values: type=str/int, value */
  struct { int is_int; int ival; const char *sval; } binds[8];

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
      "SELECT DISTINCT t.* FROM tickets t");

  /* join ticket_labels if filtering by label */
  if (filter->label != NULL && filter->label[0] != '\0') {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
        " INNER JOIN ticket_labels tl ON t.id = tl.ticket_id");
  }

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
      " WHERE t.type=? AND t.status=?");
  binds[bind_idx].is_int = 1;
  binds[bind_idx].ival = (int)filter->type;
  bind_idx++;
  binds[bind_idx].is_int = 1;
  binds[bind_idx].ival = (int)filter->status;
  bind_idx++;

  if (filter->label != NULL && filter->label[0] != '\0') {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, " AND tl.label=?");
    binds[bind_idx].is_int = 0;
    binds[bind_idx].sval = filter->label;
    bind_idx++;
  }

  if (filter->spec != NULL && filter->spec[0] != '\0') {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, " AND t.spec=?");
    binds[bind_idx].is_int = 0;
    binds[bind_idx].sval = filter->spec;
    bind_idx++;
  }

  if (filter->author != NULL && filter->author[0] != '\0') {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, " AND t.author=?");
    binds[bind_idx].is_int = 0;
    binds[bind_idx].sval = filter->author;
    bind_idx++;
  }

  if (filter->filter_priority) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, " AND t.priority=?");
    binds[bind_idx].is_int = 1;
    binds[bind_idx].ival = (int)filter->priority;
    bind_idx++;
  }

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW,
      " ORDER BY t.priority DESC, t.created_at ASC");

  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_ERR_DB; }

  for (int i = 0; i < bind_idx; i++) {
    if (binds[i].is_int) {
      sqlite3_bind_int(stmt, i + 1, binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, i + 1, binds[i].sval, -1, SQLITE_STATIC);
    }
  }

  *count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW && *count < max) {
    row_to_ticket(stmt, &out[*count]);
    (*count)++;
  }
  sqlite3_finalize(stmt);

  /* load deps and labels for each result */
  for (u32 i = 0; i < *count; i++) {
    load_deps_labels(db, &out[i]);
  }

  return TIX_OK;
}

tix_err_t tix_db_count_tickets(tix_db_t *db, tix_ticket_type_e type,
                               tix_status_e status, u32 *count) {
  if (db == NULL || count == NULL) { return TIX_ERR_INVALID_ARG; }

  const char *sql = "SELECT COUNT(*) FROM tickets WHERE type=? AND status=?";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_ERR_DB; }

  sqlite3_bind_int(stmt, 1, (int)type);
  sqlite3_bind_int(stmt, 2, (int)status);

  if (sqlite3_step(stmt) == SQLITE_ROW) {
    *count = (u32)sqlite3_column_int(stmt, 0);
  } else {
    *count = 0;
  }
  sqlite3_finalize(stmt);
  return TIX_OK;
}
