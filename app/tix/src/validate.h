#pragma once

#include "types.h"
#include "common.h"
#include "db.h"

typedef struct {
  int valid;
  u32 error_count;
  u32 warning_count;
  char errors[32][TIX_MAX_NAME_LEN];
  char warnings[32][TIX_MAX_NAME_LEN];
} tix_validation_result_t;

tix_err_t tix_validate_history(tix_db_t *db, const char *plan_path,
                               tix_validation_result_t *result);
tix_err_t tix_validate_print(const tix_validation_result_t *result,
                             char *buf, sz buf_len);
