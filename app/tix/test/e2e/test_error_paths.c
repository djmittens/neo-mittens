/*
 * Tests for error paths: NULL args, overflow conditions, boundary cases.
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "ticket.h"
#include "db.h"
#include "json.h"
#include "validate.h"
#include "cmd.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int setup_db(char *tmpdir, size_t tmpdir_len,
                    char *db_path, size_t db_path_len) {
  snprintf(tmpdir, tmpdir_len, "/tmp/tix_test_XXXXXX");
  if (mkdtemp(tmpdir) == NULL) { return -1; }

  char cmd[512];
  snprintf(cmd, sizeof(cmd),
           "cd \"%s\" && git init -q && git config user.email test@test && "
           "git config user.name test && "
           "mkdir -p .tix && "
           "touch file && git add -A && git commit -q -m init", tmpdir);
  if (system(cmd) != 0) { return -1; }

  snprintf(db_path, db_path_len, "%s/.tix/cache.db", tmpdir);
  return 0;
}

static void cleanup_env(const char *tmpdir) {
  char cmd[512];
  snprintf(cmd, sizeof(cmd), "rm -rf \"%s\"", tmpdir);
  system(cmd);
}

/* --- ticket error paths --- */

static void test_ticket_set_name_null(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_ticket_t t;
  tix_ticket_init(&t);
  ASSERT_ERR(tix_ticket_set_name(NULL, "test"));
  ASSERT_ERR(tix_ticket_set_name(&t, NULL));
  TIX_PASS();
}

static void test_ticket_set_name_overflow(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_ticket_t t;
  tix_ticket_init(&t);

  /* create a string that's exactly TIX_MAX_NAME_LEN chars (too long) */
  char long_name[TIX_MAX_NAME_LEN + 1];
  memset(long_name, 'A', TIX_MAX_NAME_LEN);
  long_name[TIX_MAX_NAME_LEN] = '\0';

  tix_err_t err = tix_ticket_set_name(&t, long_name);
  ASSERT_ERR(err);
  TIX_PASS();
}

static void test_ticket_add_dep_overflow(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_ticket_t t;
  tix_ticket_init(&t);

  /* fill all dep slots */
  for (u32 i = 0; i < TIX_MAX_DEPS; i++) {
    char dep[TIX_MAX_ID_LEN];
    snprintf(dep, sizeof(dep), "t-%08x", i);
    tix_err_t err = tix_ticket_add_dep(&t, dep);
    ASSERT_OK(err);
  }
  ASSERT_EQ(t.dep_count, TIX_MAX_DEPS);

  /* one more should fail */
  tix_err_t err = tix_ticket_add_dep(&t, "t-overflow");
  ASSERT_ERR(err);
  ASSERT_EQ(t.dep_count, TIX_MAX_DEPS);  /* count unchanged */
  TIX_PASS();
}

static void test_ticket_gen_id_null(TIX_TEST_ARGS()) {
  TIX_TEST();
  ASSERT_ERR(tix_ticket_gen_id(TIX_TICKET_TASK, NULL, 16));
  char buf[4];
  ASSERT_ERR(tix_ticket_gen_id(TIX_TICKET_TASK, buf, sizeof(buf)));
  TIX_PASS();
}

/* --- db error paths --- */

static void test_db_null_args(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_db_t db;
  memset(&db, 0, sizeof(db));
  tix_ticket_t t;
  tix_ticket_init(&t);
  u32 count = 0;

  ASSERT_ERR(tix_db_open(NULL, "path"));
  ASSERT_ERR(tix_db_open(&db, NULL));
  ASSERT_ERR(tix_db_close(NULL));
  ASSERT_ERR(tix_db_init_schema(NULL));
  ASSERT_ERR(tix_db_upsert_ticket(NULL, &t));
  ASSERT_ERR(tix_db_upsert_ticket(&db, NULL));
  ASSERT_ERR(tix_db_delete_ticket(NULL, "id"));
  ASSERT_ERR(tix_db_delete_ticket(&db, NULL));
  ASSERT_ERR(tix_db_get_ticket(NULL, "id", &t));
  ASSERT_ERR(tix_db_get_ticket(&db, NULL, &t));
  ASSERT_ERR(tix_db_get_ticket(&db, "id", NULL));
  ASSERT_ERR(tix_db_list_tickets(NULL, 0, 0, &t, &count, 1));
  ASSERT_ERR(tix_db_list_tickets(&db, 0, 0, NULL, &count, 1));
  ASSERT_ERR(tix_db_list_tickets(&db, 0, 0, &t, NULL, 1));
  ASSERT_ERR(tix_db_count_tickets(NULL, 0, 0, &count));
  ASSERT_ERR(tix_db_count_tickets(&db, 0, 0, NULL));
  ASSERT_ERR(tix_db_set_meta(NULL, "k", "v"));
  ASSERT_ERR(tix_db_set_meta(&db, NULL, "v"));
  ASSERT_ERR(tix_db_set_meta(&db, "k", NULL));
  ASSERT_ERR(tix_db_rebuild_from_jsonl(NULL, "path"));
  ASSERT_ERR(tix_db_rebuild_from_jsonl(&db, NULL));

  TIX_PASS();
}

static void test_db_get_nonexistent(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_db(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_db failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_ticket_t out;
  tix_err_t err = tix_db_get_ticket(&db, "t-nonexistent", &out);
  ASSERT_EQ(err, TIX_ERR_NOT_FOUND);

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

/* --- validate error paths --- */

static void test_validate_null_args(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_validation_result_t result;
  ASSERT_ERR(tix_validate_history(NULL, NULL, &result));
  TIX_PASS();
}

static void test_validate_circular_dep(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_db(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_db failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* create two tasks that depend on each other: A -> B -> A */
  tix_ticket_t a;
  tix_ticket_init(&a);
  a.type = TIX_TICKET_TASK;
  snprintf(a.id, sizeof(a.id), "t-aaa");
  tix_ticket_set_name(&a, "Task A");
  tix_ticket_add_dep(&a, "t-bbb");
  tix_db_upsert_ticket(&db, &a);

  tix_ticket_t b;
  tix_ticket_init(&b);
  b.type = TIX_TICKET_TASK;
  snprintf(b.id, sizeof(b.id), "t-bbb");
  tix_ticket_set_name(&b, "Task B");
  tix_ticket_add_dep(&b, "t-aaa");
  tix_db_upsert_ticket(&db, &b);

  tix_validation_result_t result;
  tix_err_t err = tix_validate_history(&db, NULL, &result);
  ASSERT_OK(err);  /* function succeeds, but result shows errors */
  ASSERT_FALSE(result.valid);
  ASSERT_GT(result.error_count, 0);

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_validate_done_no_commit(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_db(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_db failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* create a done task with no commit hash */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  t.status = TIX_STATUS_DONE;
  snprintf(t.id, sizeof(t.id), "t-done01");
  tix_ticket_set_name(&t, "Done without commit");
  /* done_at left empty */
  tix_db_upsert_ticket(&db, &t);

  tix_validation_result_t result;
  tix_err_t err = tix_validate_history(&db, NULL, &result);
  ASSERT_OK(err);
  ASSERT_FALSE(result.valid);
  ASSERT_GT(result.error_count, 0);

  /* verify the error message mentions the task */
  char output[TIX_MAX_LINE_LEN];
  tix_validate_print(&result, output, sizeof(output));
  ASSERT_STR_CONTAINS(output, "t-done01");

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

/* --- plan I/O error paths --- */

static void test_plan_append_null_args(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_ticket_t t;
  tix_ticket_init(&t);
  ASSERT_ERR(tix_plan_append_ticket(NULL, &t));
  ASSERT_ERR(tix_plan_append_ticket("/tmp/test", NULL));
  TIX_PASS();
}

static void test_plan_append_bad_path(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_ticket_t t;
  tix_ticket_init(&t);
  snprintf(t.id, sizeof(t.id), "t-test01");
  tix_ticket_set_name(&t, "test");
  tix_err_t err = tix_plan_append_ticket("/nonexistent/dir/plan.jsonl", &t);
  ASSERT_ERR(err);
  TIX_PASS();
}

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  tix_testsuite_add(&suite, "ticket_set_name_null", test_ticket_set_name_null);
  tix_testsuite_add(&suite, "ticket_set_name_overflow", test_ticket_set_name_overflow);
  tix_testsuite_add(&suite, "ticket_add_dep_overflow", test_ticket_add_dep_overflow);
  tix_testsuite_add(&suite, "ticket_gen_id_null", test_ticket_gen_id_null);
  tix_testsuite_add(&suite, "db_null_args", test_db_null_args);
  tix_testsuite_add(&suite, "db_get_nonexistent", test_db_get_nonexistent);
  tix_testsuite_add(&suite, "validate_null_args", test_validate_null_args);
  tix_testsuite_add(&suite, "validate_circular_dep", test_validate_circular_dep);
  tix_testsuite_add(&suite, "validate_done_no_commit", test_validate_done_no_commit);
  tix_testsuite_add(&suite, "plan_append_null_args", test_plan_append_null_args);
  tix_testsuite_add(&suite, "plan_append_bad_path", test_plan_append_bad_path);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
