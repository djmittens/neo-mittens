/*
 * E2E test: batch operations
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "ticket.h"
#include "db.h"
#include "batch.h"
#include "json.h"

#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int setup(char *tmpdir, size_t tlen, char *dbp, size_t dlen,
                 char *pp, size_t plen) {
  snprintf(tmpdir, tlen, "/tmp/tix_bat_XXXXXX");
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

static void test_batch_json_array(TIX_TEST_ARGS()) {
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

  /* batch create via JSON array */
  const char *json = "[{\"type\":\"task\",\"name\":\"Batch task 1\"},"
                     "{\"type\":\"task\",\"name\":\"Batch task 2\"}]";

  tix_batch_result_t result;
  tix_err_t err = tix_batch_execute_json(&db, plan_path, json, &result);
  ASSERT_OK(err);
  ASSERT_EQ(result.success_count, 2);
  ASSERT_EQ(result.error_count, 0);

  /* verify they exist in db */
  tix_ticket_t tickets[10];
  u32 count = 0;
  tix_db_list_tickets(&db, TIX_TICKET_TASK, TIX_STATUS_PENDING,
                      tickets, &count, 10);
  ASSERT_EQ(count, 2);

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

static void test_batch_empty(TIX_TEST_ARGS()) {
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

  tix_batch_result_t result;
  tix_err_t err = tix_batch_execute_json(&db, plan_path, "[]", &result);
  ASSERT_OK(err);
  ASSERT_EQ(result.success_count, 0);

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  tix_testsuite_add(&suite, "batch_json_array", test_batch_json_array);
  tix_testsuite_add(&suite, "batch_empty", test_batch_empty);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
