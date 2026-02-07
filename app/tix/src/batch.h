#pragma once

#include "types.h"
#include "common.h"
#include "db.h"

typedef struct {
  u32 success_count;
  u32 error_count;
  char last_error[TIX_MAX_NAME_LEN];
} tix_batch_result_t;

tix_err_t tix_batch_execute(tix_db_t *db, const char *plan_path,
                            const char *batch_file,
                            tix_batch_result_t *result);
tix_err_t tix_batch_execute_json(tix_db_t *db, const char *plan_path,
                                 const char *json_array,
                                 tix_batch_result_t *result);
