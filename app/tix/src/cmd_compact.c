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
 *
 * Safety: resolved tickets that have never been committed to git
 * are preserved in the compacted output. This prevents data loss
 * when compact is run before committing accept/reject/delete events.
 * These tickets will be compacted out on a subsequent run after
 * they have been committed.
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

/* Identify resolved tickets that have never been committed to git.
   These must be preserved during compaction to prevent data loss.

   Approach: get the last committed version of plan.jsonl via
   git show HEAD:<path>, replay it to find which tickets were already
   resolved. Any ticket resolved in the current cache but NOT in the
   committed version has never been committed and must be protected.

   Populates a temp table _compact_uncommitted(id TEXT) with the IDs
   of resolved tickets that should NOT be compacted out. */
static u32 mark_uncommitted_resolved(tix_ctx_t *ctx) {
  /* create temp table for protected IDs */
  sqlite3_exec(ctx->db.handle,
      "CREATE TEMP TABLE IF NOT EXISTS "
      "_compact_uncommitted(id TEXT PRIMARY KEY)",
      NULL, NULL, NULL);
  sqlite3_exec(ctx->db.handle,
      "DELETE FROM _compact_uncommitted",
      NULL, NULL, NULL);

  /* get the committed plan.jsonl content */
  const char *rel_plan = ctx->config.plan_file;
  char show_cmd[TIX_MAX_PATH_LEN + 64];
  int n = snprintf(show_cmd, sizeof(show_cmd),
      "git show HEAD:%s 2>/dev/null", rel_plan);
  if (n < 0 || (sz)n >= sizeof(show_cmd)) { return 0; }

  char committed[TIX_MAX_LINE_LEN * 32];
  int status = tix_git_run_cmd(show_cmd, committed, sizeof(committed));
  if (status != 0) {
    /* no committed version exists - all resolved tickets are uncommitted */
    const char *sql =
      "INSERT INTO _compact_uncommitted(id) "
      "SELECT id FROM tickets WHERE status >= 2";
    sqlite3_exec(ctx->db.handle, sql, NULL, NULL, NULL);
    int changes = sqlite3_changes(ctx->db.handle);
    if (changes > 0) {
      TIX_INFO("compact: %d resolved tickets never committed, preserving",
               changes);
    }
    return (u32)changes;
  }

  /* replay committed content into a temp table to find committed-resolved IDs.
     We parse the committed JSONL looking for accept/reject/delete markers
     and tickets with terminal status (s=a/r/x). */
  sqlite3_exec(ctx->db.handle,
      "CREATE TEMP TABLE IF NOT EXISTS "
      "_compact_committed_resolved(id TEXT PRIMARY KEY)",
      NULL, NULL, NULL);
  sqlite3_exec(ctx->db.handle,
      "DELETE FROM _compact_committed_resolved",
      NULL, NULL, NULL);

  /* scan committed content for resolution markers and terminal statuses */
  {
    sqlite3_stmt *ins_stmt = NULL;
    sqlite3_prepare_v2(ctx->db.handle,
        "INSERT OR IGNORE INTO _compact_committed_resolved(id) VALUES(?)",
        -1, &ins_stmt, NULL);

    const char *p = committed;
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

      tix_json_obj_t obj;
      if (tix_json_parse_line(line, &obj) != TIX_OK) { continue; }

      const char *t_val = tix_json_get_str(&obj, "t");
      if (t_val == NULL) { continue; }

      const char *id = tix_json_get_str(&obj, "id");
      if (id == NULL || id[0] == '\0') { continue; }

      /* accept/reject/delete markers indicate committed resolution */
      int is_resolved = (strcmp(t_val, "accept") == 0 ||
                         strcmp(t_val, "reject") == 0 ||
                         strcmp(t_val, "delete") == 0);

      /* ticket lines with terminal status also indicate committed resolution */
      if (!is_resolved &&
          (strcmp(t_val, "task") == 0 || strcmp(t_val, "issue") == 0 ||
           strcmp(t_val, "note") == 0)) {
        const char *s = tix_json_get_str(&obj, "s");
        if (s != NULL && (strcmp(s, "a") == 0 || strcmp(s, "r") == 0 ||
                          strcmp(s, "x") == 0)) {
          is_resolved = 1;
        }
      }

      if (is_resolved) {
        sqlite3_bind_text(ins_stmt, 1, id, -1, SQLITE_STATIC);
        sqlite3_step(ins_stmt);
        sqlite3_reset(ins_stmt);
      }
    }

    sqlite3_finalize(ins_stmt);
  }

  /* uncommitted resolved = resolved in cache but NOT in committed content */
  const char *ins_sql =
    "INSERT INTO _compact_uncommitted(id) "
    "SELECT t.id FROM tickets t "
    "WHERE t.status >= 2 "
    "AND t.id NOT IN (SELECT id FROM _compact_committed_resolved)";
  sqlite3_exec(ctx->db.handle, ins_sql, NULL, NULL, NULL);
  int changes = sqlite3_changes(ctx->db.handle);

  /* clean up temp table */
  sqlite3_exec(ctx->db.handle,
      "DROP TABLE IF EXISTS _compact_committed_resolved",
      NULL, NULL, NULL);

  if (changes > 0) {
    TIX_INFO("compact: %d resolved tickets never committed, preserving",
             changes);
  }

  return (u32)changes;
}

tix_err_t tix_cmd_compact(tix_ctx_t *ctx, int argc, char **argv) {
  /* step 1: sync from git history (implicit) */
  tix_err_t err = tix_cmd_sync(ctx, argc, argv);
  if (err != TIX_OK) { return err; }

  /* step 2: denormalize references before compaction */
  denormalize_refs(&ctx->db);

  /* step 2b: identify resolved tickets that have never been committed.
     These are protected from compaction to prevent data loss. */
  u32 protected_count = mark_uncommitted_resolved(ctx);

  /* step 3: mark resolved tickets with compacted_at timestamp.
     Tickets with terminal status (accepted/rejected/deleted) that don't
     already have compacted_at set will be stamped now so we know when
     they were physically removed from plan.jsonl.
     Skip uncommitted-resolved tickets (they stay in plan.jsonl). */
  {
    const char *mark_sql =
      "SELECT id FROM tickets WHERE status >= 2 AND compacted_at = 0"
      " AND id NOT IN (SELECT id FROM _compact_uncommitted)";
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

  /* step 4: rewrite plan.jsonl with only live tickets, sorted by ID.
     Uncommitted-resolved tickets and their tombstones are preserved. */
  err = tix_plan_compact(ctx->plan_path, &ctx->db);
  if (err != TIX_OK) {
    sqlite3_exec(ctx->db.handle,
        "DROP TABLE IF EXISTS _compact_uncommitted", NULL, NULL, NULL);
    return err;
  }

  /* clean up temp table */
  sqlite3_exec(ctx->db.handle,
      "DROP TABLE IF EXISTS _compact_uncommitted", NULL, NULL, NULL);
  (void)protected_count;

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
