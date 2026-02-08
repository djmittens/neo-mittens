/*
 * db_refs.c — Reference resolution and orphan counting.
 *
 * Split from db.c to respect the 1000-line file limit.
 * Used by validate.c, cmd_status.c, and cmd_sync.c.
 */

#include "db.h"
#include "log.h"

#include <string.h>

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

  sqlite3_stmt *stmt = NULL;
  int rc;

  /* check deps */
  const char *sql_deps =
    "SELECT d.dep_id FROM ticket_deps d "
    "LEFT JOIN tickets t ON d.dep_id = t.id "
    "WHERE t.id IS NULL";
  rc = sqlite3_prepare_v2(db->handle, sql_deps, -1, &stmt, NULL);
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
