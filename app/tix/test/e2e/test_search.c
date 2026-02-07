/*
 * E2E test: search index and query
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "ticket.h"
#include "db.h"
#include "search.h"

#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int setup(char *tmpdir, size_t tlen, char *dbp, size_t dlen) {
  snprintf(tmpdir, tlen, "/tmp/tix_srch_XXXXXX");
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

static void test_search_index_and_query(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* create and index tickets */
  tix_ticket_t t1;
  tix_ticket_init(&t1);
  t1.type = TIX_TICKET_TASK;
  snprintf(t1.id, sizeof(t1.id), "t-search1");
  tix_ticket_set_name(&t1, "Implement authentication login system");
  tix_db_upsert_ticket(&db, &t1);
  tix_search_index_ticket(&db, &t1);

  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  snprintf(t2.id, sizeof(t2.id), "t-search2");
  tix_ticket_set_name(&t2, "Fix database migration script");
  tix_db_upsert_ticket(&db, &t2);
  tix_search_index_ticket(&db, &t2);

  /* search for "authentication" should find t1 */
  tix_search_result_t results[10];
  u32 count = 0;
  tix_err_t err = tix_search_query(&db, "authentication", results, &count, 10);
  ASSERT_OK(err);
  ASSERT_GT(count, 0);
  ASSERT_STR_EQ(results[0].id, "t-search1");

  /* search for "database" should find t2 */
  count = 0;
  err = tix_search_query(&db, "database", results, &count, 10);
  ASSERT_OK(err);
  ASSERT_GT(count, 0);
  ASSERT_STR_EQ(results[0].id, "t-search2");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

static void test_search_no_results(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_search_result_t results[10];
  u32 count = 0;
  tix_err_t err = tix_search_query(&db, "xyznonexistent", results, &count, 10);
  ASSERT_OK(err);
  ASSERT_EQ(count, 0);

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

static void test_keyword_cloud(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* index some tickets */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-cloud1");
  tix_ticket_set_name(&t, "Build deployment pipeline infrastructure");
  tix_db_upsert_ticket(&db, &t);
  tix_search_index_ticket(&db, &t);

  char cloud[4096];
  tix_err_t err = tix_search_keyword_cloud(&db, cloud, sizeof(cloud));
  ASSERT_OK(err);
  /* cloud should have some content */
  ASSERT_GT(strlen(cloud), 0);

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  tix_testsuite_add(&suite, "search_index_and_query",
                    test_search_index_and_query);
  tix_testsuite_add(&suite, "search_no_results", test_search_no_results);
  tix_testsuite_add(&suite, "keyword_cloud", test_keyword_cloud);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
