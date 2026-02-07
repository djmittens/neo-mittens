#pragma once

#include "types.h"
#include "common.h"

typedef enum {
  TIX_TICKET_TASK  = 0,
  TIX_TICKET_ISSUE = 1,
  TIX_TICKET_NOTE  = 2,
} tix_ticket_type_e;

typedef enum {
  TIX_STATUS_PENDING  = 0,
  TIX_STATUS_DONE     = 1,
  TIX_STATUS_ACCEPTED = 2,
} tix_status_e;

typedef enum {
  TIX_PRIORITY_NONE   = 0,
  TIX_PRIORITY_LOW    = 1,
  TIX_PRIORITY_MEDIUM = 2,
  TIX_PRIORITY_HIGH   = 3,
} tix_priority_e;

typedef struct {
  char id[TIX_MAX_ID_LEN];
  tix_ticket_type_e type;
  tix_status_e status;
  tix_priority_e priority;
  char name[TIX_MAX_NAME_LEN];
  char spec[TIX_MAX_PATH_LEN];
  char notes[TIX_MAX_DESC_LEN];
  char accept[TIX_MAX_DESC_LEN];
  char done_at[TIX_MAX_HASH_LEN];
  char branch[TIX_MAX_BRANCH_LEN];
  char parent[TIX_MAX_ID_LEN];
  char created_from[TIX_MAX_ID_LEN];
  char supersedes[TIX_MAX_ID_LEN];
  char deps[TIX_MAX_DEPS][TIX_MAX_ID_LEN];
  u32 dep_count;
  char kill_reason[TIX_MAX_KEYWORD_LEN];
  i64 created_at;
  i64 updated_at;
} tix_ticket_t;

typedef struct {
  char id[TIX_MAX_ID_LEN];
  char done_at[TIX_MAX_HASH_LEN];
  char reason[TIX_MAX_DESC_LEN];
  char name[TIX_MAX_NAME_LEN];
  int is_accept;
  i64 timestamp;
} tix_tombstone_t;

tix_err_t tix_ticket_gen_id(tix_ticket_type_e type, char *out, sz out_len);

const char *tix_ticket_type_str(tix_ticket_type_e type);
const char *tix_status_str(tix_status_e status);
const char *tix_priority_str(tix_priority_e prio);

tix_priority_e tix_priority_from_str(const char *s);

void tix_ticket_init(tix_ticket_t *t);
tix_err_t tix_ticket_set_name(tix_ticket_t *t, const char *name);
tix_err_t tix_ticket_set_spec(tix_ticket_t *t, const char *spec);
tix_err_t tix_ticket_add_dep(tix_ticket_t *t, const char *dep_id);

/* validation helpers (shared by cmd_task, batch, validate) */
int tix_is_valid_ticket_id(const char *id);
int tix_has_duplicate_dep(const tix_ticket_t *t, const char *dep_id);
