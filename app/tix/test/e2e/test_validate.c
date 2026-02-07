/*
 * E2E test: validation (orphan deps, integrity checks, consistency)
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
           "git config user.name t && mkdir -p .tix && "
           "touch .tix/plan.jsonl && git add -A && git commit -q -m i",
           tmpdir);
  if (system(cmd) != 0) { return -1; }
  snprintf(dbp, dlen, "%s/.tix/cache.db", tmpdir);
  snprintf(pp, plen, "%s/.tix/plan.jsonl", tmpdir);
  return 0;
}

static void teardown(const char *d) {
  char cmd[512];
  snprintf(cmd, sizeof(cmd), "rm -rf \"%s\"", d);
  system(cmd);
}

/* --- test: clean state passes validation --- */

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

  /* insert valid task with acceptance criteria */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-aabbcc01");
  tix_ticket_set_name(&t, "Valid task");
  snprintf(t.accept, sizeof(t.accept), "tests pass");
  tix_db_upsert_ticket(&db, &t);

  tix_validation_result_t result;
  tix_err_t err = tix_validate_history(&db, plan_path, &result);
  ASSERT_OK(err);
  ASSERT_EQ(result.valid, 1);
  ASSERT_EQ(result.error_count, 0);
  ASSERT_EQ(result.warning_count, 0);

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

/* --- test: orphan dependency detected --- */

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
  snprintf(t.id, sizeof(t.id), "t-000a0b01");
  tix_ticket_set_name(&t, "Task with missing dep");
  snprintf(t.accept, sizeof(t.accept), "criterion");
  tix_ticket_add_dep(&t, "t-deed0000");
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
  ASSERT_STR_CONTAINS(buf, "t-deed0000");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

/* --- test: orphan parent reference detected --- */

static void test_validate_orphan_parent(TIX_TEST_ARGS()) {
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

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-00c01de1");
  snprintf(t.parent, sizeof(t.parent), "t-0060e5a1");
  tix_ticket_set_name(&t, "Child with missing parent");
  snprintf(t.accept, sizeof(t.accept), "criterion");
  tix_db_upsert_ticket(&db, &t);

  tix_validation_result_t result;
  tix_err_t err = tix_validate_history(&db, plan_path, &result);
  ASSERT_OK(err);
  ASSERT_EQ(result.valid, 0);

  char buf[4096];
  tix_validate_print(&result, buf, sizeof(buf));
  ASSERT_STR_CONTAINS(buf, "t-0060e5a1");
  ASSERT_STR_CONTAINS(buf, "parent");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

/* --- test: orphan created_from reference detected --- */

static void test_validate_orphan_created_from(TIX_TEST_ARGS()) {
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

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-00f0cf01");
  snprintf(t.created_from, sizeof(t.created_from), "i-0060e5a2");
  tix_ticket_set_name(&t, "Task from missing issue");
  snprintf(t.accept, sizeof(t.accept), "criterion");
  tix_db_upsert_ticket(&db, &t);

  tix_validation_result_t result;
  tix_err_t err = tix_validate_history(&db, plan_path, &result);
  ASSERT_OK(err);
  ASSERT_EQ(result.valid, 0);

  char buf[4096];
  tix_validate_print(&result, buf, sizeof(buf));
  ASSERT_STR_CONTAINS(buf, "i-0060e5a2");
  ASSERT_STR_CONTAINS(buf, "created_from");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

/* --- test: orphan supersedes reference detected --- */

static void test_validate_orphan_supersedes(TIX_TEST_ARGS()) {
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

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-005ebe01");
  snprintf(t.supersedes, sizeof(t.supersedes), "t-0060e5a3");
  tix_ticket_set_name(&t, "Task superseding ghost");
  snprintf(t.accept, sizeof(t.accept), "criterion");
  tix_db_upsert_ticket(&db, &t);

  tix_validation_result_t result;
  tix_err_t err = tix_validate_history(&db, plan_path, &result);
  ASSERT_OK(err);
  ASSERT_EQ(result.valid, 0);

  char buf[4096];
  tix_validate_print(&result, buf, sizeof(buf));
  ASSERT_STR_CONTAINS(buf, "t-0060e5a3");
  ASSERT_STR_CONTAINS(buf, "supersedes");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

/* --- test: dep pointing to non-task (issue) detected --- */

static void test_validate_dep_on_non_task(TIX_TEST_ARGS()) {
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

  /* insert an issue */
  tix_ticket_t issue;
  tix_ticket_init(&issue);
  issue.type = TIX_TICKET_ISSUE;
  snprintf(issue.id, sizeof(issue.id), "i-00155e01");
  tix_ticket_set_name(&issue, "Some issue");
  tix_db_upsert_ticket(&db, &issue);

  /* insert task that depends on the issue */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-00de0155");
  tix_ticket_set_name(&t, "Task depending on issue");
  snprintf(t.accept, sizeof(t.accept), "criterion");
  tix_ticket_add_dep(&t, "i-00155e01");
  tix_db_upsert_ticket(&db, &t);

  tix_validation_result_t result;
  tix_err_t err = tix_validate_history(&db, plan_path, &result);
  ASSERT_OK(err);
  ASSERT_EQ(result.valid, 0);

  char buf[4096];
  tix_validate_print(&result, buf, sizeof(buf));
  ASSERT_STR_CONTAINS(buf, "not a task");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

/* --- test: missing acceptance criteria generates warning --- */

static void test_validate_no_accept(TIX_TEST_ARGS()) {
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

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-0000acc1");
  tix_ticket_set_name(&t, "Task without acceptance");
  /* intentionally no accept criteria */
  tix_db_upsert_ticket(&db, &t);

  tix_validation_result_t result;
  tix_err_t err = tix_validate_history(&db, plan_path, &result);
  ASSERT_OK(err);
  /* no acceptance criteria is a warning, not an error */
  ASSERT_EQ(result.valid, 1);
  ASSERT_GT(result.warning_count, 0);

  char buf[4096];
  tix_validate_print(&result, buf, sizeof(buf));
  ASSERT_STR_CONTAINS(buf, "acceptance criteria");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

/* --- test: done task without commit hash detected --- */

static void test_validate_done_no_hash(TIX_TEST_ARGS()) {
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

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  t.status = TIX_STATUS_DONE;
  snprintf(t.id, sizeof(t.id), "t-00d0eba0");
  tix_ticket_set_name(&t, "Done but no hash");
  snprintf(t.accept, sizeof(t.accept), "criterion");
  /* done_at left empty */
  tix_db_upsert_ticket(&db, &t);

  tix_validation_result_t result;
  tix_err_t err = tix_validate_history(&db, plan_path, &result);
  ASSERT_OK(err);
  ASSERT_EQ(result.valid, 0);

  char buf[4096];
  tix_validate_print(&result, buf, sizeof(buf));
  ASSERT_STR_CONTAINS(buf, "commit hash");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

/* --- test: invalid ID format detected --- */

static void test_validate_bad_id_format(TIX_TEST_ARGS()) {
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

  /* insert with a bad ID (no prefix) */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "bad-format");
  tix_ticket_set_name(&t, "Bad ID task");
  snprintf(t.accept, sizeof(t.accept), "criterion");
  tix_db_upsert_ticket(&db, &t);

  tix_validation_result_t result;
  tix_err_t err = tix_validate_history(&db, plan_path, &result);
  ASSERT_OK(err);
  ASSERT_EQ(result.valid, 0);

  char buf[4096];
  tix_validate_print(&result, buf, sizeof(buf));
  ASSERT_STR_CONTAINS(buf, "invalid ID format");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

/* --- test: circular dependency detected --- */

static void test_validate_circular_dep(TIX_TEST_ARGS()) {
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

  /* A depends on B, B depends on A */
  tix_ticket_t a;
  tix_ticket_init(&a);
  a.type = TIX_TICKET_TASK;
  snprintf(a.id, sizeof(a.id), "t-00aaaa01");
  tix_ticket_set_name(&a, "Task A");
  snprintf(a.accept, sizeof(a.accept), "criterion");
  tix_ticket_add_dep(&a, "t-00bbbb01");
  tix_db_upsert_ticket(&db, &a);

  tix_ticket_t b;
  tix_ticket_init(&b);
  b.type = TIX_TICKET_TASK;
  snprintf(b.id, sizeof(b.id), "t-00bbbb01");
  tix_ticket_set_name(&b, "Task B");
  snprintf(b.accept, sizeof(b.accept), "criterion");
  tix_ticket_add_dep(&b, "t-00aaaa01");
  tix_db_upsert_ticket(&db, &b);

  tix_validation_result_t result;
  tix_err_t err = tix_validate_history(&db, plan_path, &result);
  ASSERT_OK(err);
  ASSERT_EQ(result.valid, 0);

  char buf[4096];
  tix_validate_print(&result, buf, sizeof(buf));
  ASSERT_STR_CONTAINS(buf, "circular dependency");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

/* --- test: missing name generates warning --- */

static void test_validate_no_name(TIX_TEST_ARGS()) {
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

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-0000aae0");
  snprintf(t.accept, sizeof(t.accept), "criterion");
  /* intentionally no name set */
  tix_db_upsert_ticket(&db, &t);

  tix_validation_result_t result;
  tix_err_t err = tix_validate_history(&db, plan_path, &result);
  ASSERT_OK(err);
  /* missing name is a warning */
  ASSERT_GT(result.warning_count, 0);

  char buf[4096];
  tix_validate_print(&result, buf, sizeof(buf));
  ASSERT_STR_CONTAINS(buf, "no name");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  tix_testsuite_add(&suite, "validate_clean", test_validate_clean);
  tix_testsuite_add(&suite, "validate_orphan_dep",
                    test_validate_orphan_dep);
  tix_testsuite_add(&suite, "validate_orphan_parent",
                    test_validate_orphan_parent);
  tix_testsuite_add(&suite, "validate_orphan_created_from",
                    test_validate_orphan_created_from);
  tix_testsuite_add(&suite, "validate_orphan_supersedes",
                    test_validate_orphan_supersedes);
  tix_testsuite_add(&suite, "validate_dep_on_non_task",
                    test_validate_dep_on_non_task);
  tix_testsuite_add(&suite, "validate_no_accept",
                    test_validate_no_accept);
  tix_testsuite_add(&suite, "validate_done_no_hash",
                    test_validate_done_no_hash);
  tix_testsuite_add(&suite, "validate_bad_id_format",
                    test_validate_bad_id_format);
  tix_testsuite_add(&suite, "validate_circular_dep",
                    test_validate_circular_dep);
  tix_testsuite_add(&suite, "validate_no_name",
                    test_validate_no_name);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
