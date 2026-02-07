/*
 * E2E test: full task lifecycle - create, query, done, accept, delete
 * Each test runs in an isolated temp directory with its own git repo.
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "ticket.h"
#include "db.h"
#include "json.h"
#include "config.h"
#include "search.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/* Helper: create an isolated temp dir with a git repo and tix init */
static int setup_env(char *tmpdir, size_t tmpdir_len,
                     char *db_path, size_t db_path_len,
                     char *plan_path, size_t plan_path_len) {
  snprintf(tmpdir, tmpdir_len, "/tmp/tix_test_XXXXXX");
  if (mkdtemp(tmpdir) == NULL) { return -1; }

  /* init git repo */
  char cmd[512];
  snprintf(cmd, sizeof(cmd),
           "cd \"%s\" && git init -q && git config user.email test@test && "
           "git config user.name test && "
           "mkdir -p .tix && "
           "touch .tix/plan.jsonl && "
           "git add -A && git commit -q -m init", tmpdir);
  if (system(cmd) != 0) { return -1; }

  snprintf(db_path, db_path_len, "%s/.tix/cache.db", tmpdir);
  snprintf(plan_path, plan_path_len, "%s/.tix/plan.jsonl", tmpdir);
  return 0;
}

static void cleanup_env(const char *tmpdir) {
  char cmd[512];
  snprintf(cmd, sizeof(cmd), "rm -rf \"%s\"", tmpdir);
  system(cmd);
}

/* --- Tests --- */

static void test_ticket_init(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_ticket_t t;
  tix_ticket_init(&t);
  ASSERT_EQ(t.type, TIX_TICKET_TASK);
  ASSERT_EQ(t.status, TIX_STATUS_PENDING);
  ASSERT_EQ(t.priority, TIX_PRIORITY_NONE);
  ASSERT_EQ(t.dep_count, 0);
  ASSERT_STR_EQ(t.id, "");

  TIX_PASS();
}

static void test_ticket_gen_id(TIX_TEST_ARGS()) {
  TIX_TEST();

  char id1[TIX_MAX_ID_LEN];
  char id2[TIX_MAX_ID_LEN];

  tix_err_t err = tix_ticket_gen_id(TIX_TICKET_TASK, id1, sizeof(id1));
  ASSERT_OK(err);
  ASSERT_TRUE(id1[0] == 't');
  ASSERT_TRUE(id1[1] == '-');
  ASSERT_TRUE(strlen(id1) > 3);

  err = tix_ticket_gen_id(TIX_TICKET_ISSUE, id2, sizeof(id2));
  ASSERT_OK(err);
  ASSERT_TRUE(id2[0] == 'i');

  /* IDs should be unique */
  ASSERT_TRUE(strcmp(id1, id2) != 0);

  TIX_PASS();
}

static void test_ticket_set_fields(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_ticket_t t;
  tix_ticket_init(&t);

  tix_err_t err = tix_ticket_set_name(&t, "Build login page");
  ASSERT_OK(err);
  ASSERT_STR_EQ(t.name, "Build login page");

  err = tix_ticket_set_spec(&t, "ralph/specs/login.md");
  ASSERT_OK(err);
  ASSERT_STR_EQ(t.spec, "ralph/specs/login.md");

  err = tix_ticket_add_dep(&t, "t-abc123");
  ASSERT_OK(err);
  ASSERT_EQ(t.dep_count, 1);
  ASSERT_STR_EQ(t.deps[0], "t-abc123");

  err = tix_ticket_add_dep(&t, "t-def456");
  ASSERT_OK(err);
  ASSERT_EQ(t.dep_count, 2);

  TIX_PASS();
}

static void test_priority_roundtrip(TIX_TEST_ARGS()) {
  TIX_TEST();

  ASSERT_STR_EQ(tix_priority_str(TIX_PRIORITY_HIGH), "high");
  ASSERT_STR_EQ(tix_priority_str(TIX_PRIORITY_MEDIUM), "medium");
  ASSERT_STR_EQ(tix_priority_str(TIX_PRIORITY_LOW), "low");
  ASSERT_STR_EQ(tix_priority_str(TIX_PRIORITY_NONE), "none");

  ASSERT_EQ(tix_priority_from_str("high"), TIX_PRIORITY_HIGH);
  ASSERT_EQ(tix_priority_from_str("medium"), TIX_PRIORITY_MEDIUM);
  ASSERT_EQ(tix_priority_from_str("low"), TIX_PRIORITY_LOW);
  ASSERT_EQ(tix_priority_from_str(NULL), TIX_PRIORITY_NONE);
  ASSERT_EQ(tix_priority_from_str("garbage"), TIX_PRIORITY_NONE);

  TIX_PASS();
}

static void test_db_open_close(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512], plan_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path),
                plan_path, sizeof(plan_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_err_t err = tix_db_open(&db, db_path);
  ASSERT_OK(err);

  err = tix_db_init_schema(&db);
  ASSERT_OK(err);

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

static void test_db_upsert_get(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512], plan_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path),
                plan_path, sizeof(plan_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* create a ticket */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  t.status = TIX_STATUS_PENDING;
  t.priority = TIX_PRIORITY_HIGH;
  t.created_at = 1000;
  t.updated_at = 1000;
  tix_ticket_gen_id(TIX_TICKET_TASK, t.id, sizeof(t.id));
  tix_ticket_set_name(&t, "Test task one");

  tix_err_t err = tix_db_upsert_ticket(&db, &t);
  ASSERT_OK(err);

  /* retrieve it */
  tix_ticket_t out;
  err = tix_db_get_ticket(&db, t.id, &out);
  ASSERT_OK(err);
  ASSERT_STR_EQ(out.name, "Test task one");
  ASSERT_EQ(out.priority, TIX_PRIORITY_HIGH);
  ASSERT_EQ(out.status, TIX_STATUS_PENDING);
  ASSERT_EQ(out.type, TIX_TICKET_TASK);

  /* update it */
  t.status = TIX_STATUS_DONE;
  t.updated_at = 2000;
  snprintf(t.done_at, sizeof(t.done_at), "abc1234");
  err = tix_db_upsert_ticket(&db, &t);
  ASSERT_OK(err);

  err = tix_db_get_ticket(&db, t.id, &out);
  ASSERT_OK(err);
  ASSERT_EQ(out.status, TIX_STATUS_DONE);
  ASSERT_STR_EQ(out.done_at, "abc1234");

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

static void test_db_list_tickets(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512], plan_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path),
                plan_path, sizeof(plan_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* insert 3 pending tasks */
  for (int i = 0; i < 3; i++) {
    tix_ticket_t t;
    tix_ticket_init(&t);
    t.type = TIX_TICKET_TASK;
    t.status = TIX_STATUS_PENDING;
    tix_ticket_gen_id(TIX_TICKET_TASK, t.id, sizeof(t.id));
    char name[64];
    snprintf(name, sizeof(name), "task %d", i);
    tix_ticket_set_name(&t, name);
    tix_db_upsert_ticket(&db, &t);
  }

  /* insert 1 done task */
  {
    tix_ticket_t t;
    tix_ticket_init(&t);
    t.type = TIX_TICKET_TASK;
    t.status = TIX_STATUS_DONE;
    tix_ticket_gen_id(TIX_TICKET_TASK, t.id, sizeof(t.id));
    tix_ticket_set_name(&t, "done task");
    tix_db_upsert_ticket(&db, &t);
  }

  /* list pending */
  tix_ticket_t results[10];
  u32 count = 0;
  tix_err_t err = tix_db_list_tickets(&db, TIX_TICKET_TASK,
                                       TIX_STATUS_PENDING,
                                       results, &count, 10);
  ASSERT_OK(err);
  ASSERT_EQ(count, 3);

  /* list done */
  count = 0;
  err = tix_db_list_tickets(&db, TIX_TICKET_TASK, TIX_STATUS_DONE,
                            results, &count, 10);
  ASSERT_OK(err);
  ASSERT_EQ(count, 1);
  ASSERT_STR_EQ(results[0].name, "done task");

  /* count */
  u32 c = 0;
  err = tix_db_count_tickets(&db, TIX_TICKET_TASK, TIX_STATUS_PENDING, &c);
  ASSERT_OK(err);
  ASSERT_EQ(c, 3);

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

static void test_db_delete(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512], plan_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path),
                plan_path, sizeof(plan_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  tix_ticket_gen_id(TIX_TICKET_TASK, t.id, sizeof(t.id));
  tix_ticket_set_name(&t, "delete me");
  tix_db_upsert_ticket(&db, &t);

  char saved_id[TIX_MAX_ID_LEN];
  snprintf(saved_id, sizeof(saved_id), "%s", t.id);

  /* verify it exists */
  tix_ticket_t out;
  tix_err_t err = tix_db_get_ticket(&db, saved_id, &out);
  ASSERT_OK(err);

  /* delete */
  err = tix_db_delete_ticket(&db, saved_id);
  ASSERT_OK(err);

  /* verify it's gone */
  err = tix_db_get_ticket(&db, saved_id, &out);
  ASSERT_ERR(err);

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

static void test_tombstone(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512], plan_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path),
                plan_path, sizeof(plan_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_tombstone_t ts;
  memset(&ts, 0, sizeof(ts));
  snprintf(ts.id, sizeof(ts.id), "t-test01");
  snprintf(ts.done_at, sizeof(ts.done_at), "abc1234");
  snprintf(ts.name, sizeof(ts.name), "accepted task");
  ts.is_accept = 1;
  ts.timestamp = 5000;

  tix_err_t err = tix_db_upsert_tombstone(&db, &ts);
  ASSERT_OK(err);

  tix_tombstone_t out[10];
  u32 count = 0;
  err = tix_db_list_tombstones(&db, 1, out, &count, 10);
  ASSERT_OK(err);
  ASSERT_EQ(count, 1);
  ASSERT_STR_EQ(out[0].id, "t-test01");
  ASSERT_STR_EQ(out[0].name, "accepted task");
  ASSERT_EQ(out[0].is_accept, 1);

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

static void test_json_roundtrip(TIX_TEST_ARGS()) {
  TIX_TEST();

  /* create a ticket */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  t.status = TIX_STATUS_PENDING;
  t.priority = TIX_PRIORITY_HIGH;
  t.created_at = 1000;
  t.updated_at = 2000;
  snprintf(t.id, sizeof(t.id), "t-abc123");
  tix_ticket_set_name(&t, "Write tests");
  tix_ticket_add_dep(&t, "t-dep001");

  /* write to JSON */
  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&t, buf, sizeof(buf));
  ASSERT_GT(len, 0);
  ASSERT_STR_CONTAINS(buf, "\"id\":\"t-abc123\"");
  ASSERT_STR_CONTAINS(buf, "\"name\":\"Write tests\"");
  ASSERT_STR_CONTAINS(buf, "\"priority\":\"high\"");

  /* parse it back */
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line(buf, &obj);
  ASSERT_OK(err);

  const char *id = tix_json_get_str(&obj, "id");
  ASSERT_NOT_NULL(id);
  ASSERT_STR_EQ(id, "t-abc123");

  const char *name = tix_json_get_str(&obj, "name");
  ASSERT_NOT_NULL(name);
  ASSERT_STR_EQ(name, "Write tests");

  TIX_PASS();
}

static void test_json_parse_invalid(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_json_obj_t obj;

  /* empty string */
  tix_err_t err = tix_json_parse_line("", &obj);
  ASSERT_ERR(err);

  /* not json */
  err = tix_json_parse_line("hello world", &obj);
  ASSERT_ERR(err);

  TIX_PASS();
}

static void test_db_meta(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512], plan_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path),
                plan_path, sizeof(plan_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_err_t err = tix_db_set_meta(&db, "version", "1.0.0");
  ASSERT_OK(err);

  char val[256];
  err = tix_db_get_meta(&db, "version", val, sizeof(val));
  ASSERT_OK(err);
  ASSERT_STR_EQ(val, "1.0.0");

  /* update it */
  err = tix_db_set_meta(&db, "version", "2.0.0");
  ASSERT_OK(err);
  err = tix_db_get_meta(&db, "version", val, sizeof(val));
  ASSERT_OK(err);
  ASSERT_STR_EQ(val, "2.0.0");

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  tix_testsuite_add(&suite, "ticket_init", test_ticket_init);
  tix_testsuite_add(&suite, "ticket_gen_id", test_ticket_gen_id);
  tix_testsuite_add(&suite, "ticket_set_fields", test_ticket_set_fields);
  tix_testsuite_add(&suite, "priority_roundtrip", test_priority_roundtrip);
  tix_testsuite_add(&suite, "db_open_close", test_db_open_close);
  tix_testsuite_add(&suite, "db_upsert_get", test_db_upsert_get);
  tix_testsuite_add(&suite, "db_list_tickets", test_db_list_tickets);
  tix_testsuite_add(&suite, "db_delete", test_db_delete);
  tix_testsuite_add(&suite, "tombstone", test_tombstone);
  tix_testsuite_add(&suite, "json_roundtrip", test_json_roundtrip);
  tix_testsuite_add(&suite, "json_parse_invalid", test_json_parse_invalid);
  tix_testsuite_add(&suite, "db_meta", test_db_meta);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
