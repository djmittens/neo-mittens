#pragma once

#include "types.h"
#include "common.h"
#include "ticket.h"
#include "db.h"

typedef struct {
  char id[TIX_MAX_ID_LEN];
  char name[TIX_MAX_NAME_LEN];
  double score;
  char keywords[8][TIX_MAX_KEYWORD_LEN];
  u32 keyword_count;
} tix_search_result_t;

tix_err_t tix_search_index_ticket(tix_db_t *db, const tix_ticket_t *ticket);
tix_err_t tix_search_query(tix_db_t *db, const char *query,
                           tix_search_result_t *results,
                           u32 *count, u32 max);
tix_err_t tix_search_keyword_cloud(tix_db_t *db, char *buf, sz buf_len);
