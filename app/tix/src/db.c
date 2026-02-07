#include "db.h"
#include "git.h"
#include "json.h"
#include "validate.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

/* Bump this when the tickets table schema changes.
   On mismatch the cache is dropped and rebuilt from plan.jsonl. */
#define TIX_SCHEMA_VERSION "3"

static const char *SCHEMA_SQL =
  "CREATE TABLE IF NOT EXISTS tickets ("
  "  id TEXT PRIMARY KEY,"
  "  type INTEGER NOT NULL,"
  "  status INTEGER NOT NULL,"
  "  priority INTEGER DEFAULT 0,"
  "  name TEXT NOT NULL,"
  "  spec TEXT,"
  "  notes TEXT,"
  "  accept TEXT,"
  "  done_at TEXT,"
  "  branch TEXT,"
  "  parent TEXT,"
  "  created_from TEXT,"
  "  supersedes TEXT,"
  "  kill_reason TEXT,"
  "  created_from_name TEXT,"
  "  supersedes_name TEXT,"
  "  supersedes_reason TEXT,"
  "  created_at INTEGER,"
  "  updated_at INTEGER,"
  "  commit_hash TEXT,"
  "  author TEXT,"
  "  completed_at TEXT,"
  "  cost REAL DEFAULT 0.0,"
  "  tokens_in INTEGER DEFAULT 0,"
  "  tokens_out INTEGER DEFAULT 0,"
  "  iterations INTEGER DEFAULT 0,"
  "  model TEXT,"
  "  retries INTEGER DEFAULT 0,"
  "  kill_count INTEGER DEFAULT 0"
  ");"
  "CREATE TABLE IF NOT EXISTS ticket_deps ("
  "  ticket_id TEXT NOT NULL,"
  "  dep_id TEXT NOT NULL,"
  "  PRIMARY KEY (ticket_id, dep_id)"
  ");"
  "CREATE TABLE IF NOT EXISTS ticket_labels ("
  "  ticket_id TEXT NOT NULL,"
  "  label TEXT NOT NULL,"
  "  PRIMARY KEY (ticket_id, label)"
  ");"
  "CREATE INDEX IF NOT EXISTS idx_ticket_labels_label ON ticket_labels(label);"
  "CREATE TABLE IF NOT EXISTS tombstones ("
  "  id TEXT PRIMARY KEY,"
  "  done_at TEXT,"
  "  reason TEXT,"
  "  name TEXT,"
  "  is_accept INTEGER,"
  "  timestamp INTEGER"
  ");"
  "CREATE TABLE IF NOT EXISTS keywords ("
  "  ticket_id TEXT NOT NULL,"
  "  keyword TEXT NOT NULL,"
  "  weight REAL DEFAULT 1.0,"
  "  PRIMARY KEY (ticket_id, keyword)"
  ");"
  "CREATE INDEX IF NOT EXISTS idx_keywords_keyword ON keywords(keyword);"
  "CREATE TABLE IF NOT EXISTS cache_meta ("
  "  key TEXT PRIMARY KEY,"
  "  value TEXT"
  ");"
  ;

tix_err_t tix_db_open(tix_db_t *db, const char *path) {
  if (db == NULL || path == NULL) { return TIX_ERR_INVALID_ARG; }

  memset(db, 0, sizeof(*db));
  int pn = snprintf(db->path, sizeof(db->path), "%s", path);
  if (pn < 0 || (sz)pn >= sizeof(db->path)) { return TIX_ERR_OVERFLOW; }

  int rc = sqlite3_open(path, &db->handle);
  if (rc != SQLITE_OK) {
    TIX_ERROR("sqlite3_open(%s) failed: %s", path, sqlite3_errmsg(db->handle));
    return TIX_ERR_DB;
  }

  sqlite3_exec(db->handle, "PRAGMA journal_mode=WAL", NULL, NULL, NULL);
  sqlite3_exec(db->handle, "PRAGMA synchronous=NORMAL", NULL, NULL, NULL);

  return TIX_OK;
}

tix_err_t tix_db_close(tix_db_t *db) {
  if (db == NULL || db->handle == NULL) { return TIX_ERR_INVALID_ARG; }
  sqlite3_close(db->handle);
  db->handle = NULL;
  return TIX_OK;
}

tix_err_t tix_db_init_schema(tix_db_t *db) {
  if (db == NULL || db->handle == NULL) { return TIX_ERR_INVALID_ARG; }

  /* Ensure cache_meta exists first so we can check schema version */
  sqlite3_exec(db->handle,
    "CREATE TABLE IF NOT EXISTS cache_meta "
    "(key TEXT PRIMARY KEY, value TEXT)", NULL, NULL, NULL);

  /* Check schema version - if outdated, nuke all tables and recreate */
  char ver[32] = {0};
  tix_db_get_meta(db, "schema_version", ver, sizeof(ver));
  if (ver[0] != '\0' && strcmp(ver, TIX_SCHEMA_VERSION) != 0) {
    TIX_INFO("schema version %s -> %s, rebuilding cache", ver,
             TIX_SCHEMA_VERSION);
    sqlite3_exec(db->handle, "DROP TABLE IF EXISTS tickets", NULL, NULL, NULL);
    sqlite3_exec(db->handle, "DROP TABLE IF EXISTS ticket_deps",
                 NULL, NULL, NULL);
    sqlite3_exec(db->handle, "DROP TABLE IF EXISTS ticket_labels",
                 NULL, NULL, NULL);
    sqlite3_exec(db->handle, "DROP TABLE IF EXISTS tombstones",
                 NULL, NULL, NULL);
    sqlite3_exec(db->handle, "DROP TABLE IF EXISTS keywords", NULL, NULL, NULL);
  }

  char *err_msg = NULL;
  int rc = sqlite3_exec(db->handle, SCHEMA_SQL, NULL, NULL, &err_msg);
  if (rc != SQLITE_OK) {
    TIX_ERROR("schema init failed: %s", err_msg ? err_msg : "unknown");
    sqlite3_free(err_msg);
    return TIX_ERR_DB;
  }

  tix_db_set_meta(db, "schema_version", TIX_SCHEMA_VERSION);
  return TIX_OK;
}

tix_err_t tix_db_upsert_ticket(tix_db_t *db, const tix_ticket_t *t) {
  if (db == NULL || t == NULL) { return TIX_ERR_INVALID_ARG; }

  const char *sql =
    "INSERT OR REPLACE INTO tickets "
    "(id,type,status,priority,name,spec,notes,accept,done_at,branch,"
    "parent,created_from,supersedes,kill_reason,"
    "created_from_name,supersedes_name,supersedes_reason,"
    "created_at,updated_at,"
    "author,completed_at,cost,tokens_in,tokens_out,"
    "iterations,model,retries,kill_count) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)";

  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_ERR_DB; }

  sqlite3_bind_text(stmt, 1, t->id, -1, SQLITE_STATIC);
  sqlite3_bind_int(stmt, 2, (int)t->type);
  sqlite3_bind_int(stmt, 3, (int)t->status);
  sqlite3_bind_int(stmt, 4, (int)t->priority);
  sqlite3_bind_text(stmt, 5, t->name, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 6, t->spec, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 7, t->notes, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 8, t->accept, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 9, t->done_at, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 10, t->branch, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 11, t->parent, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 12, t->created_from, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 13, t->supersedes, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 14, t->kill_reason, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 15, t->created_from_name, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 16, t->supersedes_name, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 17, t->supersedes_reason, -1, SQLITE_STATIC);
  sqlite3_bind_int64(stmt, 18, t->created_at);
  sqlite3_bind_int64(stmt, 19, t->updated_at);
  sqlite3_bind_text(stmt, 20, t->author, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 21, t->completed_at, -1, SQLITE_STATIC);
  sqlite3_bind_double(stmt, 22, t->cost);
  sqlite3_bind_int64(stmt, 23, t->tokens_in);
  sqlite3_bind_int64(stmt, 24, t->tokens_out);
  sqlite3_bind_int(stmt, 25, t->iterations);
  sqlite3_bind_text(stmt, 26, t->model, -1, SQLITE_STATIC);
  sqlite3_bind_int(stmt, 27, t->retries);
  sqlite3_bind_int(stmt, 28, t->kill_count);

  rc = sqlite3_step(stmt);
  sqlite3_finalize(stmt);
  if (rc != SQLITE_DONE) { return TIX_ERR_DB; }

  /* upsert deps */
  const char *del_deps = "DELETE FROM ticket_deps WHERE ticket_id=?";
  rc = sqlite3_prepare_v2(db->handle, del_deps, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, t->id, -1, SQLITE_STATIC);
    sqlite3_step(stmt);
    sqlite3_finalize(stmt);
  }

  if (t->dep_count > 0) {
    const char *ins_dep =
      "INSERT OR IGNORE INTO ticket_deps (ticket_id,dep_id) VALUES (?,?)";
    for (u32 i = 0; i < t->dep_count; i++) {
      rc = sqlite3_prepare_v2(db->handle, ins_dep, -1, &stmt, NULL);
      if (rc != SQLITE_OK) { continue; }
      sqlite3_bind_text(stmt, 1, t->id, -1, SQLITE_STATIC);
      sqlite3_bind_text(stmt, 2, t->deps[i], -1, SQLITE_STATIC);
      sqlite3_step(stmt);
      sqlite3_finalize(stmt);
    }
  }

  /* upsert labels */
  const char *del_labels = "DELETE FROM ticket_labels WHERE ticket_id=?";
  rc = sqlite3_prepare_v2(db->handle, del_labels, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, t->id, -1, SQLITE_STATIC);
    sqlite3_step(stmt);
    sqlite3_finalize(stmt);
  }

  if (t->label_count > 0) {
    const char *ins_label =
      "INSERT OR IGNORE INTO ticket_labels (ticket_id,label) VALUES (?,?)";
    for (u32 i = 0; i < t->label_count; i++) {
      rc = sqlite3_prepare_v2(db->handle, ins_label, -1, &stmt, NULL);
      if (rc != SQLITE_OK) { continue; }
      sqlite3_bind_text(stmt, 1, t->id, -1, SQLITE_STATIC);
      sqlite3_bind_text(stmt, 2, t->labels[i], -1, SQLITE_STATIC);
      sqlite3_step(stmt);
      sqlite3_finalize(stmt);
    }
  }

  return TIX_OK;
}

tix_err_t tix_db_delete_ticket(tix_db_t *db, const char *id) {
  if (db == NULL || id == NULL) { return TIX_ERR_INVALID_ARG; }

  const char *sql = "DELETE FROM tickets WHERE id=?";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_ERR_DB; }

  sqlite3_bind_text(stmt, 1, id, -1, SQLITE_STATIC);
  sqlite3_step(stmt);
  sqlite3_finalize(stmt);

  const char *del_deps = "DELETE FROM ticket_deps WHERE ticket_id=?";
  rc = sqlite3_prepare_v2(db->handle, del_deps, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, id, -1, SQLITE_STATIC);
    sqlite3_step(stmt);
    sqlite3_finalize(stmt);
  }

  const char *del_labels = "DELETE FROM ticket_labels WHERE ticket_id=?";
  rc = sqlite3_prepare_v2(db->handle, del_labels, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, id, -1, SQLITE_STATIC);
    sqlite3_step(stmt);
    sqlite3_finalize(stmt);
  }

  const char *del_kw = "DELETE FROM keywords WHERE ticket_id=?";
  rc = sqlite3_prepare_v2(db->handle, del_kw, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, id, -1, SQLITE_STATIC);
    sqlite3_step(stmt);
    sqlite3_finalize(stmt);
  }

  return TIX_OK;
}

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

  /* new fields — gracefully absent if reading an older schema */
  col_text(stmt, col_idx(stmt, "author"), t->author, TIX_MAX_NAME_LEN);
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

  /* load deps */
  const char *dep_sql =
      "SELECT dep_id FROM ticket_deps WHERE ticket_id=?";
  rc = sqlite3_prepare_v2(db->handle, dep_sql, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, id, -1, SQLITE_STATIC);
    while (sqlite3_step(stmt) == SQLITE_ROW && out->dep_count < TIX_MAX_DEPS) {
      const char *dep = (const char *)sqlite3_column_text(stmt, 0);
      if (dep != NULL) {
        snprintf(out->deps[out->dep_count], TIX_MAX_ID_LEN, "%s", dep);
        out->dep_count++;
      }
    }
    sqlite3_finalize(stmt);
  }

  /* load labels */
  const char *label_sql =
      "SELECT label FROM ticket_labels WHERE ticket_id=? ORDER BY label";
  rc = sqlite3_prepare_v2(db->handle, label_sql, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, id, -1, SQLITE_STATIC);
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
    const char *tid = out[i].id;

    const char *dep_sql2 =
        "SELECT dep_id FROM ticket_deps WHERE ticket_id=?";
    rc = sqlite3_prepare_v2(db->handle, dep_sql2, -1, &stmt, NULL);
    if (rc == SQLITE_OK) {
      sqlite3_bind_text(stmt, 1, tid, -1, SQLITE_STATIC);
      while (sqlite3_step(stmt) == SQLITE_ROW &&
             out[i].dep_count < TIX_MAX_DEPS) {
        const char *dep = (const char *)sqlite3_column_text(stmt, 0);
        if (dep != NULL) {
          snprintf(out[i].deps[out[i].dep_count], TIX_MAX_ID_LEN,
                   "%s", dep);
          out[i].dep_count++;
        }
      }
      sqlite3_finalize(stmt);
    }

    const char *lbl_sql =
        "SELECT label FROM ticket_labels WHERE ticket_id=? ORDER BY label";
    rc = sqlite3_prepare_v2(db->handle, lbl_sql, -1, &stmt, NULL);
    if (rc == SQLITE_OK) {
      sqlite3_bind_text(stmt, 1, tid, -1, SQLITE_STATIC);
      while (sqlite3_step(stmt) == SQLITE_ROW &&
             out[i].label_count < TIX_MAX_LABELS) {
        const char *lbl = (const char *)sqlite3_column_text(stmt, 0);
        if (lbl != NULL) {
          snprintf(out[i].labels[out[i].label_count], TIX_MAX_KEYWORD_LEN,
                   "%s", lbl);
          out[i].label_count++;
        }
      }
      sqlite3_finalize(stmt);
    }
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

tix_err_t tix_db_upsert_tombstone(tix_db_t *db, const tix_tombstone_t *ts) {
  if (db == NULL || ts == NULL) { return TIX_ERR_INVALID_ARG; }

  const char *sql =
    "INSERT OR REPLACE INTO tombstones "
    "(id,done_at,reason,name,is_accept,timestamp) VALUES (?,?,?,?,?,?)";

  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_ERR_DB; }

  sqlite3_bind_text(stmt, 1, ts->id, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 2, ts->done_at, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 3, ts->reason, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 4, ts->name, -1, SQLITE_STATIC);
  sqlite3_bind_int(stmt, 5, ts->is_accept);
  sqlite3_bind_int64(stmt, 6, ts->timestamp);

  rc = sqlite3_step(stmt);
  sqlite3_finalize(stmt);
  return (rc == SQLITE_DONE) ? TIX_OK : TIX_ERR_DB;
}

tix_err_t tix_db_list_tombstones(tix_db_t *db, int is_accept,
                                 tix_tombstone_t *out, u32 *count, u32 max) {
  if (db == NULL || out == NULL || count == NULL) {
    return TIX_ERR_INVALID_ARG;
  }

  const char *sql =
    "SELECT id,done_at,reason,name,is_accept,timestamp "
    "FROM tombstones WHERE is_accept=? ORDER BY timestamp DESC";

  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_ERR_DB; }

  sqlite3_bind_int(stmt, 1, is_accept);
  *count = 0;

  while (sqlite3_step(stmt) == SQLITE_ROW && *count < max) {
    tix_tombstone_t *t = &out[*count];
    memset(t, 0, sizeof(*t));
    const char *id = (const char *)sqlite3_column_text(stmt, 0);
    if (id != NULL) { snprintf(t->id, TIX_MAX_ID_LEN, "%s", id); }
    const char *da = (const char *)sqlite3_column_text(stmt, 1);
    if (da != NULL) { snprintf(t->done_at, TIX_MAX_HASH_LEN, "%s", da); }
    const char *r = (const char *)sqlite3_column_text(stmt, 2);
    if (r != NULL) { snprintf(t->reason, TIX_MAX_DESC_LEN, "%s", r); }
    const char *n = (const char *)sqlite3_column_text(stmt, 3);
    if (n != NULL) { snprintf(t->name, TIX_MAX_NAME_LEN, "%s", n); }
    t->is_accept = sqlite3_column_int(stmt, 4);
    t->timestamp = sqlite3_column_int64(stmt, 5);
    (*count)++;
  }
  sqlite3_finalize(stmt);
  return TIX_OK;
}

tix_err_t tix_db_set_meta(tix_db_t *db, const char *key, const char *value) {
  if (db == NULL || key == NULL || value == NULL) {
    return TIX_ERR_INVALID_ARG;
  }

  const char *sql =
    "INSERT OR REPLACE INTO cache_meta (key,value) VALUES (?,?)";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_ERR_DB; }

  sqlite3_bind_text(stmt, 1, key, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 2, value, -1, SQLITE_STATIC);
  rc = sqlite3_step(stmt);
  sqlite3_finalize(stmt);
  return (rc == SQLITE_DONE) ? TIX_OK : TIX_ERR_DB;
}

tix_err_t tix_db_get_meta(tix_db_t *db, const char *key,
                          char *value, sz value_len) {
  if (db == NULL || key == NULL || value == NULL) {
    return TIX_ERR_INVALID_ARG;
  }

  const char *sql = "SELECT value FROM cache_meta WHERE key=?";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_ERR_DB; }

  sqlite3_bind_text(stmt, 1, key, -1, SQLITE_STATIC);
  if (sqlite3_step(stmt) == SQLITE_ROW) {
    const char *v = (const char *)sqlite3_column_text(stmt, 0);
    if (v != NULL) { snprintf(value, value_len, "%s", v); }
    else { value[0] = '\0'; }
  } else {
    value[0] = '\0';
  }
  sqlite3_finalize(stmt);
  return TIX_OK;
}

tix_err_t tix_db_is_stale(tix_db_t *db, int *is_stale) {
  if (db == NULL || is_stale == NULL) { return TIX_ERR_INVALID_ARG; }

  char cached_commit[TIX_MAX_HASH_LEN];
  tix_err_t err = tix_db_get_meta(db, "last_commit",
                                   cached_commit, sizeof(cached_commit));
  if (err != TIX_OK || cached_commit[0] == '\0') {
    *is_stale = 1;
    return TIX_OK;
  }

  char head[TIX_MAX_HASH_LEN];
  err = tix_git_rev_parse_head(head, sizeof(head));
  if (err != TIX_OK) {
    *is_stale = 1;
    return TIX_OK;
  }

  *is_stale = (strcmp(cached_commit, head) != 0) ? 1 : 0;
  return TIX_OK;
}

static tix_ticket_type_e type_from_jsonl(const char *t_val) {
  if (strcmp(t_val, "task") == 0)  { return TIX_TICKET_TASK; }
  if (strcmp(t_val, "issue") == 0) { return TIX_TICKET_ISSUE; }
  if (strcmp(t_val, "note") == 0)  { return TIX_TICKET_NOTE; }
  return TIX_TICKET_TASK;
}

static tix_status_e status_from_jsonl(const char *s_val) {
  if (s_val == NULL) { return TIX_STATUS_PENDING; }
  if (strcmp(s_val, "d") == 0) { return TIX_STATUS_DONE; }
  if (strcmp(s_val, "a") == 0) { return TIX_STATUS_ACCEPTED; }
  return TIX_STATUS_PENDING;
}

/* Parse a single JSONL line and apply it to the DB (upsert/delete).
   This is the shared core used by replay_content and replay_jsonl_file. */
static void replay_one_line(tix_db_t *db, const char *line) {
  tix_json_obj_t obj;
  if (tix_json_parse_line(line, &obj) != TIX_OK) { return; }

  const char *t_val = tix_json_get_str(&obj, "t");
  if (t_val == NULL) { return; }

  if (strcmp(t_val, "task") == 0 || strcmp(t_val, "issue") == 0 ||
      strcmp(t_val, "note") == 0) {
    tix_ticket_t ticket;
    tix_ticket_init(&ticket);
    ticket.type = type_from_jsonl(t_val);

    const char *id = tix_json_get_str(&obj, "id");
    if (id != NULL) { snprintf(ticket.id, TIX_MAX_ID_LEN, "%s", id); }

    const char *name = tix_json_get_str(&obj, "name");
    if (name != NULL) { snprintf(ticket.name, TIX_MAX_NAME_LEN, "%s", name); }

    /* issues use "desc" instead of "name" */
    const char *desc = tix_json_get_str(&obj, "desc");
    if (desc != NULL && ticket.name[0] == '\0') {
      snprintf(ticket.name, TIX_MAX_NAME_LEN, "%s", desc);
    }

    const char *s = tix_json_get_str(&obj, "s");
    ticket.status = status_from_jsonl(s);

    const char *spec = tix_json_get_str(&obj, "spec");
    if (spec != NULL) { snprintf(ticket.spec, TIX_MAX_PATH_LEN, "%s", spec); }

    const char *notes = tix_json_get_str(&obj, "notes");
    if (notes != NULL) { snprintf(ticket.notes, TIX_MAX_DESC_LEN, "%s", notes); }

    const char *accept = tix_json_get_str(&obj, "accept");
    if (accept != NULL) { snprintf(ticket.accept, TIX_MAX_DESC_LEN, "%s", accept); }

    const char *done_at = tix_json_get_str(&obj, "done_at");
    if (done_at != NULL) { snprintf(ticket.done_at, TIX_MAX_HASH_LEN, "%s", done_at); }

    const char *priority = tix_json_get_str(&obj, "priority");
    ticket.priority = tix_priority_from_str(priority);

    const char *parent = tix_json_get_str(&obj, "parent");
    if (parent != NULL) { snprintf(ticket.parent, TIX_MAX_ID_LEN, "%s", parent); }

    const char *cf = tix_json_get_str(&obj, "created_from");
    if (cf != NULL) { snprintf(ticket.created_from, TIX_MAX_ID_LEN, "%s", cf); }

    const char *ss = tix_json_get_str(&obj, "supersedes");
    if (ss != NULL) { snprintf(ticket.supersedes, TIX_MAX_ID_LEN, "%s", ss); }

    const char *kr = tix_json_get_str(&obj, "kill_reason");
    if (kr != NULL) { snprintf(ticket.kill_reason, TIX_MAX_KEYWORD_LEN, "%s", kr); }

    /* denormalized reference names */
    const char *cfn = tix_json_get_str(&obj, "created_from_name");
    if (cfn != NULL) {
      snprintf(ticket.created_from_name, TIX_MAX_NAME_LEN, "%s", cfn);
    }
    const char *ssn = tix_json_get_str(&obj, "supersedes_name");
    if (ssn != NULL) {
      snprintf(ticket.supersedes_name, TIX_MAX_NAME_LEN, "%s", ssn);
    }
    const char *ssr = tix_json_get_str(&obj, "supersedes_reason");
    if (ssr != NULL) {
      snprintf(ticket.supersedes_reason, TIX_MAX_KEYWORD_LEN, "%s", ssr);
    }

    const char *branch = tix_json_get_str(&obj, "branch");
    if (branch != NULL) {
      snprintf(ticket.branch, TIX_MAX_BRANCH_LEN, "%s", branch);
    }

    /* identity & attribution */
    const char *author = tix_json_get_str(&obj, "author");
    if (author != NULL) {
      snprintf(ticket.author, TIX_MAX_NAME_LEN, "%s", author);
    }

    /* completion timing */
    const char *completed_at = tix_json_get_str(&obj, "completed_at");
    if (completed_at != NULL) {
      snprintf(ticket.completed_at, sizeof(ticket.completed_at),
               "%s", completed_at);
    }

    /* agent telemetry */
    ticket.cost = tix_json_get_double(&obj, "cost", 0.0);
    ticket.tokens_in = tix_json_get_num(&obj, "tokens_in", 0);
    ticket.tokens_out = tix_json_get_num(&obj, "tokens_out", 0);
    ticket.iterations = (i32)tix_json_get_num(&obj, "iterations", 0);
    const char *model = tix_json_get_str(&obj, "model");
    if (model != NULL) {
      snprintf(ticket.model, TIX_MAX_NAME_LEN, "%s", model);
    }
    ticket.retries = (i32)tix_json_get_num(&obj, "retries", 0);
    ticket.kill_count = (i32)tix_json_get_num(&obj, "kill_count", 0);

    /* load deps from JSON array */
    for (u32 fi = 0; fi < obj.field_count; fi++) {
      if (strcmp(obj.fields[fi].key, "deps") == 0 &&
          obj.fields[fi].type == TIX_JSON_ARRAY) {
        for (u32 ai = 0; ai < obj.fields[fi].arr_count &&
             ticket.dep_count < TIX_MAX_DEPS; ai++) {
          const char *dval = obj.fields[fi].arr_vals[ai];
          sz dlen = strlen(dval);
          if (dlen >= TIX_MAX_ID_LEN) { dlen = TIX_MAX_ID_LEN - 1; }
          memcpy(ticket.deps[ticket.dep_count], dval, dlen);
          ticket.deps[ticket.dep_count][dlen] = '\0';
          ticket.dep_count++;
        }
        break;
      }
    }

    /* load labels from JSON array */
    for (u32 fi = 0; fi < obj.field_count; fi++) {
      if (strcmp(obj.fields[fi].key, "labels") == 0 &&
          obj.fields[fi].type == TIX_JSON_ARRAY) {
        for (u32 ai = 0; ai < obj.fields[fi].arr_count &&
             ticket.label_count < TIX_MAX_LABELS; ai++) {
          snprintf(ticket.labels[ticket.label_count], TIX_MAX_KEYWORD_LEN,
                   "%s", obj.fields[fi].arr_vals[ai]);
          ticket.label_count++;
        }
        break;
      }
    }

    tix_db_upsert_ticket(db, &ticket);
  } else if (strcmp(t_val, "accept") == 0 || strcmp(t_val, "reject") == 0) {
    tix_tombstone_t ts;
    memset(&ts, 0, sizeof(ts));
    ts.is_accept = (strcmp(t_val, "accept") == 0) ? 1 : 0;

    const char *id = tix_json_get_str(&obj, "id");
    if (id != NULL) { snprintf(ts.id, TIX_MAX_ID_LEN, "%s", id); }

    const char *done_at = tix_json_get_str(&obj, "done_at");
    if (done_at != NULL) { snprintf(ts.done_at, TIX_MAX_HASH_LEN, "%s", done_at); }

    const char *reason = tix_json_get_str(&obj, "reason");
    if (reason != NULL) { snprintf(ts.reason, TIX_MAX_DESC_LEN, "%s", reason); }

    const char *name = tix_json_get_str(&obj, "name");
    if (name != NULL) { snprintf(ts.name, TIX_MAX_NAME_LEN, "%s", name); }

    tix_db_upsert_tombstone(db, &ts);

    /* accept removes the ticket; reject is handled by a subsequent
       updated ticket line that resets status to pending */
    if (ts.is_accept && ts.id[0] != '\0') {
      tix_db_delete_ticket(db, ts.id);
    }
  } else if (strcmp(t_val, "delete") == 0) {
    const char *id = tix_json_get_str(&obj, "id");
    if (id != NULL) {
      tix_db_delete_ticket(db, id);
    }
  }
}

tix_err_t tix_db_clear_tickets(tix_db_t *db) {
  if (db == NULL || db->handle == NULL) { return TIX_ERR_INVALID_ARG; }

  sqlite3_exec(db->handle, "DELETE FROM tickets", NULL, NULL, NULL);
  sqlite3_exec(db->handle, "DELETE FROM ticket_deps", NULL, NULL, NULL);
  sqlite3_exec(db->handle, "DELETE FROM ticket_labels", NULL, NULL, NULL);
  sqlite3_exec(db->handle, "DELETE FROM tombstones", NULL, NULL, NULL);
  sqlite3_exec(db->handle, "DELETE FROM keywords", NULL, NULL, NULL);
  return TIX_OK;
}

tix_err_t tix_db_replay_content(tix_db_t *db, const char *content) {
  if (db == NULL) { return TIX_ERR_INVALID_ARG; }
  if (content == NULL || content[0] == '\0') { return TIX_OK; }

  const char *p = content;
  char line[TIX_MAX_LINE_LEN];

  while (*p != '\0') {
    const char *nl = strchr(p, '\n');
    sz line_len;
    if (nl != NULL) {
      line_len = (sz)(nl - p);
    } else {
      line_len = strlen(p);
    }
    if (line_len >= sizeof(line)) { line_len = sizeof(line) - 1; }
    memcpy(line, p, line_len);
    line[line_len] = '\0';

    p = (nl != NULL) ? nl + 1 : p + line_len;

    if (line[0] == '\0') { continue; }
    replay_one_line(db, line);
  }

  return TIX_OK;
}

tix_err_t tix_db_replay_jsonl_file(tix_db_t *db, const char *jsonl_path) {
  if (db == NULL || jsonl_path == NULL) { return TIX_ERR_INVALID_ARG; }

  FILE *fp = fopen(jsonl_path, "r");
  if (fp == NULL) {
    TIX_DEBUG("plan.jsonl not found at %s, skipping", jsonl_path);
    return TIX_OK;
  }

  sqlite3_exec(db->handle, "BEGIN TRANSACTION", NULL, NULL, NULL);

  char line[TIX_MAX_LINE_LEN];
  while (fgets(line, (int)sizeof(line), fp) != NULL) {
    replay_one_line(db, line);
  }

  sqlite3_exec(db->handle, "COMMIT", NULL, NULL, NULL);
  fclose(fp);

  TIX_INFO("replayed %s into cache", jsonl_path);
  return TIX_OK;
}

tix_err_t tix_db_rebuild_from_jsonl(tix_db_t *db, const char *jsonl_path) {
  if (db == NULL || jsonl_path == NULL) { return TIX_ERR_INVALID_ARG; }

  FILE *fp = fopen(jsonl_path, "r");
  if (fp == NULL) {
    TIX_DEBUG("plan.jsonl not found at %s, starting fresh", jsonl_path);
    return TIX_OK;
  }
  fclose(fp);

  tix_db_clear_tickets(db);

  tix_err_t err = tix_db_replay_jsonl_file(db, jsonl_path);
  if (err != TIX_OK) { return err; }

  /* update cache commit */
  char head[TIX_MAX_HASH_LEN];
  if (tix_git_rev_parse_head(head, sizeof(head)) == TIX_OK) {
    tix_db_set_meta(db, "last_commit", head);
  }

  TIX_INFO("rebuilt cache from %s", jsonl_path);

  /* run validation after rebuild to surface data issues from JSONL */
  tix_validation_result_t vresult;
  tix_err_t verr = tix_validate_history(db, jsonl_path, &vresult);
  if (verr == TIX_OK) {
    for (u32 vi = 0; vi < vresult.error_count; vi++) {
      TIX_WARN("rebuild validation: %s", vresult.errors[vi]);
    }
    for (u32 vi = 0; vi < vresult.warning_count; vi++) {
      TIX_DEBUG("rebuild validation: %s", vresult.warnings[vi]);
    }
  }

  return TIX_OK;
}

tix_ref_state_e tix_db_resolve_ref(tix_db_t *db, const char *id) {
  if (db == NULL || id == NULL || id[0] == '\0') { return TIX_REF_BROKEN; }

  /* check live tickets first */
  if (tix_db_ticket_exists(db, id)) { return TIX_REF_RESOLVED; }

  /* check tombstones */
  const char *sql = "SELECT COUNT(*) FROM tombstones WHERE id=?";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_REF_BROKEN; }

  sqlite3_bind_text(stmt, 1, id, -1, SQLITE_STATIC);
  int found = 0;
  if (sqlite3_step(stmt) == SQLITE_ROW) {
    found = sqlite3_column_int(stmt, 0);
  }
  sqlite3_finalize(stmt);

  return (found > 0) ? TIX_REF_STALE : TIX_REF_BROKEN;
}

tix_err_t tix_db_count_refs(tix_db_t *db, tix_ref_counts_t *counts) {
  if (db == NULL || counts == NULL) { return TIX_ERR_INVALID_ARG; }
  memset(counts, 0, sizeof(*counts));

  /* check deps */
  const char *sql_deps =
    "SELECT d.dep_id FROM ticket_deps d "
    "LEFT JOIN tickets t ON d.dep_id = t.id "
    "WHERE t.id IS NULL";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql_deps, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *did = (const char *)sqlite3_column_text(stmt, 0);
      tix_ref_state_e state = tix_db_resolve_ref(db, did);
      if (state == TIX_REF_STALE) { counts->stale_deps++; }
      if (state == TIX_REF_BROKEN) { counts->broken_deps++; }
    }
    sqlite3_finalize(stmt);
  }

  /* check parent refs */
  const char *sql_parent =
    "SELECT t.parent FROM tickets t "
    "WHERE t.parent IS NOT NULL AND t.parent != '' "
    "AND NOT EXISTS (SELECT 1 FROM tickets p WHERE p.id = t.parent)";
  rc = sqlite3_prepare_v2(db->handle, sql_parent, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *pid = (const char *)sqlite3_column_text(stmt, 0);
      tix_ref_state_e state = tix_db_resolve_ref(db, pid);
      if (state == TIX_REF_STALE) { counts->stale_parents++; }
      if (state == TIX_REF_BROKEN) { counts->broken_parents++; }
    }
    sqlite3_finalize(stmt);
  }

  /* check created_from refs */
  const char *sql_cf =
    "SELECT t.created_from FROM tickets t "
    "WHERE t.created_from IS NOT NULL AND t.created_from != '' "
    "AND NOT EXISTS (SELECT 1 FROM tickets c WHERE c.id = t.created_from)";
  rc = sqlite3_prepare_v2(db->handle, sql_cf, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *cid = (const char *)sqlite3_column_text(stmt, 0);
      tix_ref_state_e state = tix_db_resolve_ref(db, cid);
      if (state == TIX_REF_STALE) { counts->stale_created_from++; }
      if (state == TIX_REF_BROKEN) { counts->broken_created_from++; }
    }
    sqlite3_finalize(stmt);
  }

  /* check supersedes refs */
  const char *sql_ss =
    "SELECT t.supersedes FROM tickets t "
    "WHERE t.supersedes IS NOT NULL AND t.supersedes != '' "
    "AND NOT EXISTS (SELECT 1 FROM tickets s WHERE s.id = t.supersedes)";
  rc = sqlite3_prepare_v2(db->handle, sql_ss, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    while (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *sid = (const char *)sqlite3_column_text(stmt, 0);
      tix_ref_state_e state = tix_db_resolve_ref(db, sid);
      if (state == TIX_REF_STALE) { counts->stale_supersedes++; }
      if (state == TIX_REF_BROKEN) { counts->broken_supersedes++; }
    }
    sqlite3_finalize(stmt);
  }

  return TIX_OK;
}
