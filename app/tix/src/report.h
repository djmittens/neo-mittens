#pragma once

#include "types.h"
#include "common.h"
#include "db.h"

/* --- Progress report (existing) --- */

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

/* --- Summary report (executive overview for bare 'tix report') --- */

typedef struct {
  /* counts */
  u32 total_tasks;
  u32 done_tasks;
  u32 accepted_tasks;
  u32 pending_tasks;
  u32 total_issues;
  u32 total_notes;
  u32 blocked_count;

  /* velocity */
  u32 completed;            /* done + accepted with any telemetry */
  double total_cost;
  double avg_cost;
  i64 total_tokens_in;
  i64 total_tokens_out;
  double avg_cycle_secs;
  double avg_iterations;
  u32 total_retries;
  u32 total_kills;

  /* top model (highest total cost among completed tasks) */
  char top_model[TIX_MAX_NAME_LEN];
  u32 top_model_tasks;
  double top_model_cost;

  /* top author (most total tasks) */
  char top_author[TIX_MAX_NAME_LEN];
  u32 top_author_total;
  u32 top_author_done;
} tix_summary_report_t;

tix_err_t tix_report_summary(tix_db_t *db, tix_summary_report_t *report);
tix_err_t tix_report_summary_print(const tix_summary_report_t *r,
                                   char *buf, sz buf_len);

/* --- Velocity report --- */

typedef struct {
  u32 completed;           /* done + accepted tasks with telemetry */
  double total_cost;       /* sum of cost */
  double avg_cost;         /* average cost per task */
  i64 total_tokens_in;     /* sum tokens_in */
  i64 total_tokens_out;    /* sum tokens_out */
  double avg_cycle_secs;   /* average (updated_at - created_at) */
  double avg_iterations;   /* average iterations per task */
  u32 total_retries;       /* sum retries */
  u32 total_kills;         /* sum kill_count */
} tix_velocity_report_t;

tix_err_t tix_report_velocity(tix_db_t *db, tix_velocity_report_t *report);
tix_err_t tix_report_velocity_print(const tix_velocity_report_t *r,
                                    char *buf, sz buf_len);

/* --- Actors (per-author) report --- */

#define TIX_MAX_REPORT_ACTORS 64

typedef struct {
  char author[TIX_MAX_NAME_LEN];
  u32 total;               /* tasks created */
  u32 completed;           /* done + accepted */
  u32 pending;
  double total_cost;
  double avg_cost;
  double avg_iterations;
} tix_actor_entry_t;

typedef struct {
  tix_actor_entry_t actors[TIX_MAX_REPORT_ACTORS];
  u32 count;
} tix_actors_report_t;

tix_err_t tix_report_actors(tix_db_t *db, tix_actors_report_t *report);
tix_err_t tix_report_actors_print(const tix_actors_report_t *r,
                                  char *buf, sz buf_len);

/* --- Models (per-model) report --- */

#define TIX_MAX_REPORT_MODELS 32

typedef struct {
  char model[TIX_MAX_NAME_LEN];
  u32 total;
  double total_cost;
  double avg_cost;
  i64 total_tokens_in;
  i64 total_tokens_out;
  double avg_iterations;
} tix_model_entry_t;

typedef struct {
  tix_model_entry_t models[TIX_MAX_REPORT_MODELS];
  u32 count;
} tix_models_report_t;

tix_err_t tix_report_models(tix_db_t *db, tix_models_report_t *report);
tix_err_t tix_report_models_print(const tix_models_report_t *r,
                                  char *buf, sz buf_len);
