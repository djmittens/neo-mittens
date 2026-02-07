/*
 * E2E test: report generation (progress, velocity, actors, models)
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "ticket.h"
#include "db.h"
#include "report.h"

#include <math.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int setup(char *tmpdir, size_t tlen, char *dbp, size_t dlen) {
  snprintf(tmpdir, tlen, "/tmp/tix_rpt_XXXXXX");
  if (mkdtemp(tmpdir) == NULL) { return -1; }
  char cmd[512];
  snprintf(cmd, sizeof(cmd),
           "cd \"%s\" && git init -q && git config user.email t@t && "
           "git config user.name t && mkdir -p .tix && "
           "touch x && git add -A && git commit -q -m i", tmpdir);
  if (system(cmd) != 0) { return -1; }
  snprintf(dbp, dlen, "%s/.tix/cache.db", tmpdir);
  return 0;
}

static void teardown(const char *d) {
  char cmd[512];
  snprintf(cmd, sizeof(cmd), "rm -rf \"%s\"", d);
  system(cmd);
}

static void test_report_empty(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_report_t report;
  tix_err_t err = tix_report_generate(&db, &report);
  ASSERT_OK(err);
  ASSERT_EQ(report.total_tasks, 0);
  ASSERT_EQ(report.pending_tasks, 0);
  ASSERT_EQ(report.done_tasks, 0);

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

static void test_report_with_data(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* insert some tickets */
  for (int i = 0; i < 3; i++) {
    tix_ticket_t t;
    tix_ticket_init(&t);
    t.type = TIX_TICKET_TASK;
    t.status = TIX_STATUS_PENDING;
    t.priority = TIX_PRIORITY_HIGH;
    tix_ticket_gen_id(TIX_TICKET_TASK, t.id, sizeof(t.id));
    tix_ticket_set_name(&t, "pending task");
    tix_db_upsert_ticket(&db, &t);
  }

  for (int i = 0; i < 2; i++) {
    tix_ticket_t t;
    tix_ticket_init(&t);
    t.type = TIX_TICKET_TASK;
    t.status = TIX_STATUS_DONE;
    tix_ticket_gen_id(TIX_TICKET_TASK, t.id, sizeof(t.id));
    tix_ticket_set_name(&t, "done task");
    tix_db_upsert_ticket(&db, &t);
  }

  /* issue */
  {
    tix_ticket_t t;
    tix_ticket_init(&t);
    t.type = TIX_TICKET_ISSUE;
    tix_ticket_gen_id(TIX_TICKET_ISSUE, t.id, sizeof(t.id));
    tix_ticket_set_name(&t, "test issue");
    tix_db_upsert_ticket(&db, &t);
  }

  tix_report_t report;
  tix_err_t err = tix_report_generate(&db, &report);
  ASSERT_OK(err);
  ASSERT_EQ(report.total_tasks, 5);
  ASSERT_EQ(report.pending_tasks, 3);
  ASSERT_EQ(report.done_tasks, 2);
  ASSERT_EQ(report.high_priority, 3);
  ASSERT_EQ(report.total_issues, 1);

  /* test print output */
  char buf[4096];
  err = tix_report_print(&report, buf, sizeof(buf));
  ASSERT_OK(err);
  ASSERT_GT(strlen(buf), 0);
  ASSERT_STR_CONTAINS(buf, "Tasks:");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

/* Helper: insert a done task with telemetry fields */
static void insert_done_task(tix_db_t *db, const char *id,
                             const char *author, const char *model,
                             double cost, i64 tokens_in, i64 tokens_out,
                             i32 iterations, i32 retries, i32 kill_count,
                             i64 created_at, i64 updated_at) {
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  t.status = TIX_STATUS_DONE;
  snprintf(t.id, sizeof(t.id), "%s", id);
  tix_ticket_set_name(&t, "done task");
  snprintf(t.author, sizeof(t.author), "%s", author);
  snprintf(t.model, sizeof(t.model), "%s", model);
  t.cost = cost;
  t.tokens_in = tokens_in;
  t.tokens_out = tokens_out;
  t.iterations = iterations;
  t.retries = retries;
  t.kill_count = kill_count;
  t.created_at = created_at;
  t.updated_at = updated_at;
  tix_db_upsert_ticket(db, &t);
}

/* ---- Velocity report tests ---- */

static void test_velocity_empty(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_velocity_report_t report;
  tix_err_t err = tix_report_velocity(&db, &report);
  ASSERT_OK(err);
  ASSERT_EQ(report.completed, 0);
  ASSERT_TRUE(fabs(report.total_cost) < 0.0001);
  ASSERT_EQ(report.total_tokens_in, 0);

  /* print should mention no data */
  char buf[4096];
  err = tix_report_velocity_print(&report, buf, sizeof(buf));
  ASSERT_OK(err);
  ASSERT_STR_CONTAINS(buf, "No completed tasks");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

static void test_velocity_with_data(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* task 1: cost=0.50, 10000 in, 2000 out, 3 iters, 1 retry, 0 kills
     cycle: 100s */
  insert_done_task(&db, "t-vel001", "Alice", "model-a",
                   0.50, 10000, 2000, 3, 1, 0, 1000, 1100);

  /* task 2: cost=1.25, 20000 in, 5000 out, 5 iters, 0 retries, 1 kill
     cycle: 200s */
  insert_done_task(&db, "t-vel002", "Bob", "model-b",
                   1.25, 20000, 5000, 5, 0, 1, 1000, 1200);

  /* pending task should NOT be counted */
  {
    tix_ticket_t t;
    tix_ticket_init(&t);
    t.type = TIX_TICKET_TASK;
    t.status = TIX_STATUS_PENDING;
    snprintf(t.id, sizeof(t.id), "t-vel003");
    tix_ticket_set_name(&t, "pending");
    t.cost = 99.0;
    tix_db_upsert_ticket(&db, &t);
  }

  tix_velocity_report_t report;
  tix_err_t err = tix_report_velocity(&db, &report);
  ASSERT_OK(err);

  ASSERT_EQ(report.completed, 2);
  ASSERT_TRUE(fabs(report.total_cost - 1.75) < 0.01);
  ASSERT_TRUE(fabs(report.avg_cost - 0.875) < 0.01);
  ASSERT_EQ(report.total_tokens_in, 30000);
  ASSERT_EQ(report.total_tokens_out, 7000);
  /* avg cycle: (100 + 200) / 2 = 150 */
  ASSERT_TRUE(fabs(report.avg_cycle_secs - 150.0) < 1.0);
  /* avg iterations: (3 + 5) / 2 = 4 */
  ASSERT_TRUE(fabs(report.avg_iterations - 4.0) < 0.1);
  ASSERT_EQ(report.total_retries, 1);
  ASSERT_EQ(report.total_kills, 1);

  /* print should contain cost and token info */
  char buf[4096];
  err = tix_report_velocity_print(&report, buf, sizeof(buf));
  ASSERT_OK(err);
  ASSERT_STR_CONTAINS(buf, "Velocity Report");
  ASSERT_STR_CONTAINS(buf, "Completed tasks: 2");
  ASSERT_STR_CONTAINS(buf, "$");
  ASSERT_STR_CONTAINS(buf, "Input:");
  ASSERT_STR_CONTAINS(buf, "Output:");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

/* ---- Actors report tests ---- */

static void test_actors_empty(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_actors_report_t report;
  tix_err_t err = tix_report_actors(&db, &report);
  ASSERT_OK(err);
  ASSERT_EQ(report.count, 0);

  char buf[4096];
  err = tix_report_actors_print(&report, buf, sizeof(buf));
  ASSERT_OK(err);
  ASSERT_STR_CONTAINS(buf, "No tasks with author");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

static void test_actors_with_data(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* Alice: 2 done tasks */
  insert_done_task(&db, "t-act001", "Alice", "m",
                   0.50, 10000, 2000, 3, 0, 0, 1000, 1100);
  insert_done_task(&db, "t-act002", "Alice", "m",
                   0.75, 15000, 3000, 4, 0, 0, 1000, 1200);

  /* Bob: 1 done + 1 pending */
  insert_done_task(&db, "t-act003", "Bob", "m",
                   1.00, 20000, 5000, 5, 0, 0, 1000, 1300);
  {
    tix_ticket_t t;
    tix_ticket_init(&t);
    t.type = TIX_TICKET_TASK;
    t.status = TIX_STATUS_PENDING;
    snprintf(t.id, sizeof(t.id), "t-act004");
    tix_ticket_set_name(&t, "Bob pending");
    snprintf(t.author, sizeof(t.author), "Bob");
    tix_db_upsert_ticket(&db, &t);
  }

  /* no-author task should NOT appear */
  {
    tix_ticket_t t;
    tix_ticket_init(&t);
    t.type = TIX_TICKET_TASK;
    t.status = TIX_STATUS_DONE;
    snprintf(t.id, sizeof(t.id), "t-act005");
    tix_ticket_set_name(&t, "no author");
    tix_db_upsert_ticket(&db, &t);
  }

  tix_actors_report_t report;
  tix_err_t err = tix_report_actors(&db, &report);
  ASSERT_OK(err);
  ASSERT_EQ(report.count, 2);

  /* sorted by total DESC: Alice=2, Bob=2 (2 total each) or Bob=2 */
  /* actually Alice has 2, Bob has 2 total too; order is stable by SQL */
  /* let's find each by name */
  const tix_actor_entry_t *alice = NULL;
  const tix_actor_entry_t *bob = NULL;
  for (u32 i = 0; i < report.count; i++) {
    if (strcmp(report.actors[i].author, "Alice") == 0) {
      alice = &report.actors[i];
    }
    if (strcmp(report.actors[i].author, "Bob") == 0) {
      bob = &report.actors[i];
    }
  }

  ASSERT_NOT_NULL(alice);
  ASSERT_EQ(alice->total, 2);
  ASSERT_EQ(alice->completed, 2);
  ASSERT_EQ(alice->pending, 0);
  ASSERT_TRUE(fabs(alice->total_cost - 1.25) < 0.01);

  ASSERT_NOT_NULL(bob);
  ASSERT_EQ(bob->total, 2);
  ASSERT_EQ(bob->completed, 1);
  ASSERT_EQ(bob->pending, 1);
  ASSERT_TRUE(fabs(bob->total_cost - 1.00) < 0.01);

  /* print should have table header */
  char buf[8192];
  err = tix_report_actors_print(&report, buf, sizeof(buf));
  ASSERT_OK(err);
  ASSERT_STR_CONTAINS(buf, "Actors Report");
  ASSERT_STR_CONTAINS(buf, "Author");
  ASSERT_STR_CONTAINS(buf, "Alice");
  ASSERT_STR_CONTAINS(buf, "Bob");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

/* ---- Models report tests ---- */

static void test_models_empty(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_models_report_t report;
  tix_err_t err = tix_report_models(&db, &report);
  ASSERT_OK(err);
  ASSERT_EQ(report.count, 0);

  char buf[4096];
  err = tix_report_models_print(&report, buf, sizeof(buf));
  ASSERT_OK(err);
  ASSERT_STR_CONTAINS(buf, "No completed tasks with model");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

static void test_models_with_data(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* claude-sonnet: 2 tasks, cost 0.50 + 0.75 = 1.25 */
  insert_done_task(&db, "t-mod001", "A", "claude-sonnet-4-20250514",
                   0.50, 10000, 2000, 3, 0, 0, 1000, 1100);
  insert_done_task(&db, "t-mod002", "B", "claude-sonnet-4-20250514",
                   0.75, 15000, 3000, 5, 0, 0, 1000, 1200);

  /* claude-opus: 1 task, cost 2.00 */
  insert_done_task(&db, "t-mod003", "A", "claude-opus-4-20250514",
                   2.00, 50000, 10000, 8, 0, 0, 1000, 1300);

  /* pending task with model should NOT appear */
  {
    tix_ticket_t t;
    tix_ticket_init(&t);
    t.type = TIX_TICKET_TASK;
    t.status = TIX_STATUS_PENDING;
    snprintf(t.id, sizeof(t.id), "t-mod004");
    tix_ticket_set_name(&t, "pending");
    snprintf(t.model, sizeof(t.model), "should-not-appear");
    tix_db_upsert_ticket(&db, &t);
  }

  /* done task with no model should NOT appear */
  insert_done_task(&db, "t-mod005", "A", "",
                   0.10, 1000, 200, 1, 0, 0, 1000, 1050);

  tix_models_report_t report;
  tix_err_t err = tix_report_models(&db, &report);
  ASSERT_OK(err);
  ASSERT_EQ(report.count, 2);

  /* sorted by total cost DESC: opus (2.00) first, then sonnet (1.25) */
  const tix_model_entry_t *opus = NULL;
  const tix_model_entry_t *sonnet = NULL;
  for (u32 i = 0; i < report.count; i++) {
    if (strstr(report.models[i].model, "opus") != NULL) {
      opus = &report.models[i];
    }
    if (strstr(report.models[i].model, "sonnet") != NULL) {
      sonnet = &report.models[i];
    }
  }

  ASSERT_NOT_NULL(opus);
  ASSERT_EQ(opus->total, 1);
  ASSERT_TRUE(fabs(opus->total_cost - 2.00) < 0.01);
  ASSERT_TRUE(fabs(opus->avg_cost - 2.00) < 0.01);
  ASSERT_EQ(opus->total_tokens_in, 50000);
  ASSERT_EQ(opus->total_tokens_out, 10000);

  ASSERT_NOT_NULL(sonnet);
  ASSERT_EQ(sonnet->total, 2);
  ASSERT_TRUE(fabs(sonnet->total_cost - 1.25) < 0.01);
  ASSERT_TRUE(fabs(sonnet->avg_cost - 0.625) < 0.01);
  ASSERT_EQ(sonnet->total_tokens_in, 25000);

  /* print should have table header */
  char buf[8192];
  err = tix_report_models_print(&report, buf, sizeof(buf));
  ASSERT_OK(err);
  ASSERT_STR_CONTAINS(buf, "Models Report");
  ASSERT_STR_CONTAINS(buf, "Model");
  ASSERT_STR_CONTAINS(buf, "opus");
  ASSERT_STR_CONTAINS(buf, "sonnet");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

/* ---- Null argument tests ---- */

static void test_report_null_args(TIX_TEST_ARGS()) {
  TIX_TEST();

  ASSERT_ERR(tix_report_velocity(NULL, NULL));
  ASSERT_ERR(tix_report_actors(NULL, NULL));
  ASSERT_ERR(tix_report_models(NULL, NULL));

  ASSERT_ERR(tix_report_velocity_print(NULL, NULL, 0));
  ASSERT_ERR(tix_report_actors_print(NULL, NULL, 0));
  ASSERT_ERR(tix_report_models_print(NULL, NULL, 0));

  TIX_PASS();
}

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  /* progress (existing) */
  tix_testsuite_add(&suite, "report_empty", test_report_empty);
  tix_testsuite_add(&suite, "report_with_data", test_report_with_data);

  /* velocity */
  tix_testsuite_add(&suite, "velocity_empty", test_velocity_empty);
  tix_testsuite_add(&suite, "velocity_with_data", test_velocity_with_data);

  /* actors */
  tix_testsuite_add(&suite, "actors_empty", test_actors_empty);
  tix_testsuite_add(&suite, "actors_with_data", test_actors_with_data);

  /* models */
  tix_testsuite_add(&suite, "models_empty", test_models_empty);
  tix_testsuite_add(&suite, "models_with_data", test_models_with_data);

  /* null args */
  tix_testsuite_add(&suite, "report_null_args", test_report_null_args);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
