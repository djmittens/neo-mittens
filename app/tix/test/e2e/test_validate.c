/*
 * E2E test: validation (orphan deps, integrity checks)
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "ticket.h"
#include "db.h"
#include "validate.h"

#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int setup(char *tmpdir, size_t tlen, char *dbp, size_t dlen,
                 char *pp, size_t plen) {
  snprintf(tmpdir, tlen, "/tmp/tix_val_XXXXXX");
  if (mkdtemp(tmpdir) == NULL) { return -1; }
  char cmd[512];
  snprintf(cmd, sizeof(cmd),
           "cd \"%s\" && git init -q && git config user.email t@t && "
           "git config user.name t && mkdir -p .tix ralph && "
           "touch ralph/plan.jsonl && git add -A && git commit -q -m i",
           tmpdir);
  if (system(cmd) != 0) { return -1; }
  snprintf(dbp, dlen, "%s/.tix/cache.db", tmpdir);
  snprintf(pp, plen, "%s/ralph/plan.jsonl", tmpdir);
  return 0;
}

static void teardown(const char *d) {
  char cmd[512];
  snprintf(cmd, sizeof(cmd), "rm -rf \"%s\"", d);
  system(cmd);
}

static void test_validate_clean(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512], plan_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path),
            plan_path, sizeof(plan_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* insert valid tasks with no deps */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-valid1");
  tix_ticket_set_name(&t, "Valid task");
  tix_db_upsert_ticket(&db, &t);

  tix_validation_result_t result;
  tix_err_t err = tix_validate_history(&db, plan_path, &result);
  ASSERT_OK(err);
  ASSERT_EQ(result.valid, 1);
  ASSERT_EQ(result.error_count, 0);

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

static void test_validate_orphan_dep(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512], plan_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path),
            plan_path, sizeof(plan_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* insert task with a dep that doesn't exist */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-orphan");
  tix_ticket_set_name(&t, "Task with missing dep");
  tix_ticket_add_dep(&t, "t-doesnotexist");
  tix_db_upsert_ticket(&db, &t);

  tix_validation_result_t result;
  tix_err_t err = tix_validate_history(&db, plan_path, &result);
  ASSERT_OK(err);
  ASSERT_EQ(result.valid, 0);
  ASSERT_GT(result.error_count, 0);

  /* check error message */
  char buf[4096];
  err = tix_validate_print(&result, buf, sizeof(buf));
  ASSERT_OK(err);
  ASSERT_STR_CONTAINS(buf, "t-doesnotexist");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  tix_testsuite_add(&suite, "validate_clean", test_validate_clean);
  tix_testsuite_add(&suite, "validate_orphan_dep", test_validate_orphan_dep);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
