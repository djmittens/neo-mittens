/*
 * E2E test: progress report generation
 *
 * Only tests the generic progress report (ticket counts, priority
 * breakdown, blocked deps).  Domain-specific reports (velocity, models,
 * actors) have been moved to the orchestrator (Ralph) and tested there.
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "ticket.h"
#include "db.h"
#include "report.h"

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

/* ---- Null argument tests ---- */

static void test_report_null_args(TIX_TEST_ARGS()) {
  TIX_TEST();

  ASSERT_ERR(tix_report_generate(NULL, NULL));
  ASSERT_ERR(tix_report_print(NULL, NULL, 0));

  TIX_PASS();
}

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  /* progress report */
  tix_testsuite_add(&suite, "report_empty", test_report_empty);
  tix_testsuite_add(&suite, "report_with_data", test_report_with_data);

  /* null args */
  tix_testsuite_add(&suite, "report_null_args", test_report_null_args);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
