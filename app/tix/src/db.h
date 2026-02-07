#pragma once

#include "types.h"
#include "common.h"
#include "ticket.h"
#include "tql.h"
#include "sqlite3.h"

typedef struct {
  sqlite3 *handle;
  char path[TIX_MAX_PATH_LEN];
  char last_commit[TIX_MAX_HASH_LEN];
} tix_db_t;

tix_err_t tix_db_open(tix_db_t *db, const char *path);
tix_err_t tix_db_close(tix_db_t *db);
tix_err_t tix_db_init_schema(tix_db_t *db);

tix_err_t tix_db_upsert_ticket(tix_db_t *db, const tix_ticket_t *ticket);
tix_err_t tix_db_delete_ticket(tix_db_t *db, const char *id);
tix_err_t tix_db_get_ticket(tix_db_t *db, const char *id, tix_ticket_t *out);

/* check if a ticket with the given ID exists in the cache */
int tix_db_ticket_exists(tix_db_t *db, const char *id);

tix_err_t tix_db_list_tickets(tix_db_t *db, tix_ticket_type_e type,
                              tix_status_e status,
                              tix_ticket_t *out, u32 *count, u32 max);
tix_err_t tix_db_count_tickets(tix_db_t *db, tix_ticket_type_e type,
                               tix_status_e status, u32 *count);

/* Filter criteria for flexible queries. NULL/empty fields = no filter. */
typedef struct {
  tix_ticket_type_e type;
  tix_status_e status;
  const char *label;       /* match tickets with this label */
  const char *spec;        /* match tickets with this spec (prefix match) */
  const char *author;      /* match tickets by this author */
  tix_priority_e priority; /* TIX_PRIORITY_NONE = no filter */
  int filter_priority;     /* 1 = filter by priority field, 0 = ignore */
} tix_db_filter_t;

tix_err_t tix_db_list_tickets_filtered(tix_db_t *db,
                                       const tix_db_filter_t *filter,
                                       tix_ticket_t *out, u32 *count,
                                       u32 max);

tix_err_t tix_db_upsert_tombstone(tix_db_t *db, const tix_tombstone_t *ts);
tix_err_t tix_db_list_tombstones(tix_db_t *db, int is_accept,
                                 tix_tombstone_t *out, u32 *count, u32 max);

tix_err_t tix_db_set_meta(tix_db_t *db, const char *key, const char *value);
tix_err_t tix_db_get_meta(tix_db_t *db, const char *key,
                          char *value, sz value_len);

tix_err_t tix_db_is_stale(tix_db_t *db, int *is_stale);
tix_err_t tix_db_rebuild_from_jsonl(tix_db_t *db, const char *jsonl_path);

/* Replay JSONL content (in-memory string) into DB additively.
   Handles task/issue/note lines, accept/reject tombstones, delete markers.
   Uses upsert (last-write-wins) semantics - does NOT clear the DB first. */
tix_err_t tix_db_replay_content(tix_db_t *db, const char *content);

/* Replay a plan.jsonl file into DB additively (no nuke).
   Same as replay_content but reads from a file path. */
tix_err_t tix_db_replay_jsonl_file(tix_db_t *db, const char *jsonl_path);

/* Clear all ticket data from the cache (tickets, deps, tombstones, keywords).
   Used before a full history replay (e.g. tix sync). */
tix_err_t tix_db_clear_tickets(tix_db_t *db);

/* Reference resolution states */
typedef enum {
  TIX_REF_RESOLVED = 0,  /* target exists as live ticket */
  TIX_REF_STALE    = 1,  /* target exists in tombstones (accepted/resolved) */
  TIX_REF_BROKEN   = 2,  /* target not found anywhere */
} tix_ref_state_e;

/* Resolve a reference: check tickets table, then tombstones table */
tix_ref_state_e tix_db_resolve_ref(tix_db_t *db, const char *id);

/* Count orphan references across all tickets.
   Returns counts of broken deps, parents, created_from, supersedes. */
typedef struct {
  u32 broken_deps;
  u32 broken_parents;
  u32 broken_created_from;
  u32 broken_supersedes;
  u32 stale_deps;
  u32 stale_parents;
  u32 stale_created_from;
  u32 stale_supersedes;
} tix_ref_counts_t;

tix_err_t tix_db_count_refs(tix_db_t *db, tix_ref_counts_t *counts);

/* ---- TQL execution ---- */

/* Execute a compiled TQL query and write JSON results to stdout.
   Handles both aggregate (objects with named columns) and row queries. */
tix_err_t tix_db_exec_tql(tix_db_t *db, const tql_compiled_t *compiled);

/* Execute raw SQL and write JSON results to stdout.
   Each row is a JSON object with column names as keys. */
tix_err_t tix_db_exec_raw_sql(tix_db_t *db, const char *sql);
