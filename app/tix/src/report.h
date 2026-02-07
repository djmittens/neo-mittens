#pragma once

#include "types.h"
#include "common.h"
#include "db.h"

typedef struct {
  u32 total_tasks;
  u32 pending_tasks;
  u32 done_tasks;
  u32 accepted_tasks;
  u32 total_issues;
  u32 total_notes;
  u32 blocked_count;
  u32 high_priority;
  u32 medium_priority;
  u32 low_priority;
} tix_report_t;

tix_err_t tix_report_generate(tix_db_t *db, tix_report_t *report);
tix_err_t tix_report_print(const tix_report_t *report, char *buf, sz buf_len);
