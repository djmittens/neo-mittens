#pragma once

#include "types.h"
#include "common.h"
#include "ticket.h"
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

tix_err_t tix_db_list_tickets(tix_db_t *db, tix_ticket_type_e type,
                              tix_status_e status,
                              tix_ticket_t *out, u32 *count, u32 max);
tix_err_t tix_db_count_tickets(tix_db_t *db, tix_ticket_type_e type,
                               tix_status_e status, u32 *count);

tix_err_t tix_db_upsert_tombstone(tix_db_t *db, const tix_tombstone_t *ts);
tix_err_t tix_db_list_tombstones(tix_db_t *db, int is_accept,
                                 tix_tombstone_t *out, u32 *count, u32 max);

tix_err_t tix_db_set_meta(tix_db_t *db, const char *key, const char *value);
tix_err_t tix_db_get_meta(tix_db_t *db, const char *key,
                          char *value, sz value_len);

tix_err_t tix_db_is_stale(tix_db_t *db, int *is_stale);
tix_err_t tix_db_rebuild_from_jsonl(tix_db_t *db, const char *jsonl_path);
