#include "cmd.h"
#include "git.h"
#include "json.h"
#include "log.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

/*
 * tix compact - sync from git history, denormalize references,
 * then rewrite plan.jsonl with only live tickets sorted by ID.
 *
 * Compact implicitly calls sync first to ensure the cache has
 * the full picture from git history. Then it denormalizes
 * created_from and supersedes references (baking in the name
 * and reason so they survive if the referenced ticket is removed).
 * Finally it rewrites plan.jsonl with only live tickets.
 */

/* Denormalize created_from and supersedes references on all tickets.
   For each reference, if the target exists (in tickets or tombstones),
   copy its name (and kill_reason for supersedes) onto the referencing
   ticket so the context survives if the target is later removed. */
static tix_err_t denormalize_refs(tix_db_t *db) {
  /* get all tickets with created_from set */
  const char *sql_cf =
    "SELECT id, created_from FROM tickets "
    "WHERE created_from IS NOT NULL AND created_from != '' "
    "AND (created_from_name IS NULL OR created_from_name = '')";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql_cf, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    /* collect IDs first to avoid modifying while iterating */
    char ids[TIX_MAX_BATCH][TIX_MAX_ID_LEN];
    char refs[TIX_MAX_BATCH][TIX_MAX_ID_LEN];
    u32 count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW && count < TIX_MAX_BATCH) {
      const char *id = (const char *)sqlite3_column_text(stmt, 0);
      const char *cf = (const char *)sqlite3_column_text(stmt, 1);
      if (id != NULL && cf != NULL) {
        snprintf(ids[count], TIX_MAX_ID_LEN, "%s", id);
        snprintf(refs[count], TIX_MAX_ID_LEN, "%s", cf);
        count++;
      }
    }
    sqlite3_finalize(stmt);

    for (u32 i = 0; i < count; i++) {
      /* look up the referenced ticket */
      tix_ticket_t ref_ticket;
      if (tix_db_get_ticket(db, refs[i], &ref_ticket) == TIX_OK) {
        /* update the referencing ticket */
        tix_ticket_t ticket;
        if (tix_db_get_ticket(db, ids[i], &ticket) == TIX_OK) {
          snprintf(ticket.created_from_name, TIX_MAX_NAME_LEN,
                   "%s", ref_ticket.name);
          tix_db_upsert_ticket(db, &ticket);
        }
      } else {
        /* check tombstones */
        const char *ts_sql =
          "SELECT name FROM tombstones WHERE id=?";
        sqlite3_stmt *ts_stmt = NULL;
        rc = sqlite3_prepare_v2(db->handle, ts_sql, -1, &ts_stmt, NULL);
        if (rc == SQLITE_OK) {
          sqlite3_bind_text(ts_stmt, 1, refs[i], -1, SQLITE_STATIC);
          if (sqlite3_step(ts_stmt) == SQLITE_ROW) {
            const char *tname =
              (const char *)sqlite3_column_text(ts_stmt, 0);
            if (tname != NULL) {
              tix_ticket_t ticket;
              if (tix_db_get_ticket(db, ids[i], &ticket) == TIX_OK) {
                snprintf(ticket.created_from_name, TIX_MAX_NAME_LEN,
                         "%s", tname);
                tix_db_upsert_ticket(db, &ticket);
              }
            }
          }
          sqlite3_finalize(ts_stmt);
        }
      }
    }
  }

  /* get all tickets with supersedes set */
  const char *sql_ss =
    "SELECT id, supersedes FROM tickets "
    "WHERE supersedes IS NOT NULL AND supersedes != '' "
    "AND (supersedes_name IS NULL OR supersedes_name = '')";
  rc = sqlite3_prepare_v2(db->handle, sql_ss, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    char ids[TIX_MAX_BATCH][TIX_MAX_ID_LEN];
    char refs[TIX_MAX_BATCH][TIX_MAX_ID_LEN];
    u32 count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW && count < TIX_MAX_BATCH) {
      const char *id = (const char *)sqlite3_column_text(stmt, 0);
      const char *ss = (const char *)sqlite3_column_text(stmt, 1);
      if (id != NULL && ss != NULL) {
        snprintf(ids[count], TIX_MAX_ID_LEN, "%s", id);
        snprintf(refs[count], TIX_MAX_ID_LEN, "%s", ss);
        count++;
      }
    }
    sqlite3_finalize(stmt);

    for (u32 i = 0; i < count; i++) {
      tix_ticket_t ref_ticket;
      if (tix_db_get_ticket(db, refs[i], &ref_ticket) == TIX_OK) {
        tix_ticket_t ticket;
        if (tix_db_get_ticket(db, ids[i], &ticket) == TIX_OK) {
          snprintf(ticket.supersedes_name, TIX_MAX_NAME_LEN,
                   "%s", ref_ticket.name);
          if (ref_ticket.kill_reason[0] != '\0') {
            snprintf(ticket.supersedes_reason, TIX_MAX_KEYWORD_LEN,
                     "%s", ref_ticket.kill_reason);
          }
          tix_db_upsert_ticket(db, &ticket);
        }
      } else {
        /* check tombstones for name + reason */
        const char *ts_sql =
          "SELECT name, reason FROM tombstones WHERE id=?";
        sqlite3_stmt *ts_stmt = NULL;
        rc = sqlite3_prepare_v2(db->handle, ts_sql, -1, &ts_stmt, NULL);
        if (rc == SQLITE_OK) {
          sqlite3_bind_text(ts_stmt, 1, refs[i], -1, SQLITE_STATIC);
          if (sqlite3_step(ts_stmt) == SQLITE_ROW) {
            const char *tname =
              (const char *)sqlite3_column_text(ts_stmt, 0);
            const char *treason =
              (const char *)sqlite3_column_text(ts_stmt, 1);
            tix_ticket_t ticket;
            if (tix_db_get_ticket(db, ids[i], &ticket) == TIX_OK) {
              if (tname != NULL) {
                snprintf(ticket.supersedes_name, TIX_MAX_NAME_LEN,
                         "%s", tname);
              }
              if (treason != NULL && treason[0] != '\0') {
                snprintf(ticket.supersedes_reason, TIX_MAX_KEYWORD_LEN,
                         "%s", treason);
              }
              tix_db_upsert_ticket(db, &ticket);
            }
          }
          sqlite3_finalize(ts_stmt);
        }
      }
    }
  }

  return TIX_OK;
}

tix_err_t tix_cmd_compact(tix_ctx_t *ctx, int argc, char **argv) {
  /* step 1: sync from git history (implicit) */
  tix_err_t err = tix_cmd_sync(ctx, argc, argv);
  if (err != TIX_OK) { return err; }

  /* step 2: denormalize references before compaction */
  denormalize_refs(&ctx->db);

  /* step 3: mark resolved tickets with compacted_at timestamp.
     Tickets with terminal status (accepted/rejected/deleted) that don't
     already have compacted_at set will be stamped now so we know when
     they were physically removed from plan.jsonl. */
  {
    const char *mark_sql =
      "SELECT id FROM tickets WHERE status >= 2 AND compacted_at = 0";
    sqlite3_stmt *mark_stmt = NULL;
    int rc = sqlite3_prepare_v2(ctx->db.handle, mark_sql, -1,
                                &mark_stmt, NULL);
    if (rc == SQLITE_OK) {
      char mark_ids[TIX_MAX_BATCH][TIX_MAX_ID_LEN];
      u32 mark_count = 0;
      while (sqlite3_step(mark_stmt) == SQLITE_ROW &&
             mark_count < TIX_MAX_BATCH) {
        const char *mid = (const char *)sqlite3_column_text(mark_stmt, 0);
        if (mid != NULL) {
          snprintf(mark_ids[mark_count], TIX_MAX_ID_LEN, "%s", mid);
          mark_count++;
        }
      }
      sqlite3_finalize(mark_stmt);

      i64 now = (i64)time(NULL);
      for (u32 mi = 0; mi < mark_count; mi++) {
        tix_ticket_t ticket;
        if (tix_db_get_ticket(&ctx->db, mark_ids[mi], &ticket) == TIX_OK) {
          ticket.compacted_at = now;
          tix_db_upsert_ticket(&ctx->db, &ticket);
        }
      }

      if (mark_count > 0) {
        TIX_INFO("compact: marked %u resolved tickets with compacted_at",
                 mark_count);
      }
    }
  }

  /* step 4: rewrite plan.jsonl with only live tickets, sorted by ID */
  err = tix_plan_compact(ctx->plan_path, &ctx->db);
  if (err != TIX_OK) { return err; }

  /* count what we wrote */
  u32 task_count = 0;
  u32 issue_count = 0;
  u32 note_count = 0;
  tix_db_count_tickets(&ctx->db, TIX_TICKET_TASK, TIX_STATUS_PENDING,
                       &task_count);
  u32 done_count = 0;
  tix_db_count_tickets(&ctx->db, TIX_TICKET_TASK, TIX_STATUS_DONE,
                       &done_count);
  task_count += done_count;
  tix_db_count_tickets(&ctx->db, TIX_TICKET_ISSUE, TIX_STATUS_PENDING,
                       &issue_count);
  tix_db_count_tickets(&ctx->db, TIX_TICKET_NOTE, TIX_STATUS_PENDING,
                       &note_count);

  printf("{\"compacted\":true,"
         "\"tasks\":%u,\"issues\":%u,\"notes\":%u}\n",
         task_count, issue_count, note_count);
  return TIX_OK;
}
