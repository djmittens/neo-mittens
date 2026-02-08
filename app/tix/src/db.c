/*
 * db.c — Core SQLite operations: schema, open/close, upsert/delete,
 *         tombstones, and cache metadata.
 *
 * Query functions are in db_query.c.
 * JSONL replay is in db_replay.c.
 * Ref resolution is in db_refs.c.
 */

#include "db.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

/* Bump this when the tickets table schema changes.
   On mismatch the cache is dropped and rebuilt from plan.jsonl. */
#define TIX_SCHEMA_VERSION "6"

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
  "  assigned TEXT,"
  "  completed_at TEXT,"
  "  resolved_at INTEGER DEFAULT 0,"
  "  compacted_at INTEGER DEFAULT 0"
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
  "CREATE TABLE IF NOT EXISTS ticket_meta ("
  "  ticket_id TEXT NOT NULL,"
  "  key TEXT NOT NULL,"
  "  value_text TEXT,"
  "  value_num REAL,"
  "  PRIMARY KEY (ticket_id, key)"
  ");"
  "CREATE INDEX IF NOT EXISTS idx_ticket_meta_key ON ticket_meta(key);"
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
    sqlite3_exec(db->handle, "DROP TABLE IF EXISTS ticket_meta",
                 NULL, NULL, NULL);
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
    "author,assigned,completed_at,"
    "resolved_at,compacted_at) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)";

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
  sqlite3_bind_text(stmt, 21, t->assigned, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 22, t->completed_at, -1, SQLITE_STATIC);
  sqlite3_bind_int64(stmt, 23, t->resolved_at);
  sqlite3_bind_int64(stmt, 24, t->compacted_at);

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

  sqlite3_stmt *stmt = NULL;
  int rc;

  const char *sql = "DELETE FROM tickets WHERE id=?";
  rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
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

  const char *del_meta = "DELETE FROM ticket_meta WHERE ticket_id=?";
  rc = sqlite3_prepare_v2(db->handle, del_meta, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, id, -1, SQLITE_STATIC);
    sqlite3_step(stmt);
    sqlite3_finalize(stmt);
  }

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

/* ---- Ticket metadata (generic key-value store per ticket) ---- */

tix_err_t tix_db_set_ticket_meta(tix_db_t *db, const char *ticket_id,
                                 const char *key, const char *value_text,
                                 double value_num) {
  if (db == NULL || ticket_id == NULL || key == NULL) {
    return TIX_ERR_INVALID_ARG;
  }

  const char *sql =
    "INSERT OR REPLACE INTO ticket_meta "
    "(ticket_id,key,value_text,value_num) VALUES (?,?,?,?)";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_ERR_DB; }

  sqlite3_bind_text(stmt, 1, ticket_id, -1, SQLITE_STATIC);
  sqlite3_bind_text(stmt, 2, key, -1, SQLITE_STATIC);
  if (value_text != NULL) {
    sqlite3_bind_text(stmt, 3, value_text, -1, SQLITE_STATIC);
  } else {
    sqlite3_bind_null(stmt, 3);
  }
  sqlite3_bind_double(stmt, 4, value_num);

  rc = sqlite3_step(stmt);
  sqlite3_finalize(stmt);
  return (rc == SQLITE_DONE) ? TIX_OK : TIX_ERR_DB;
}

tix_err_t tix_db_set_ticket_meta_num(tix_db_t *db, const char *ticket_id,
                                     const char *key, double value) {
  return tix_db_set_ticket_meta(db, ticket_id, key, NULL, value);
}

tix_err_t tix_db_set_ticket_meta_str(tix_db_t *db, const char *ticket_id,
                                     const char *key, const char *value) {
  return tix_db_set_ticket_meta(db, ticket_id, key, value, 0.0);
}

tix_err_t tix_db_delete_ticket_meta(tix_db_t *db, const char *ticket_id) {
  if (db == NULL || ticket_id == NULL) { return TIX_ERR_INVALID_ARG; }

  const char *sql = "DELETE FROM ticket_meta WHERE ticket_id=?";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_ERR_DB; }

  sqlite3_bind_text(stmt, 1, ticket_id, -1, SQLITE_STATIC);
  sqlite3_step(stmt);
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
