/*
 * E2E tests for the assigned field.
 *
 * Tests cover:
 *   - JSON roundtrip: assigned field serializes and deserializes
 *   - Empty assigned not serialized
 *   - DB roundtrip: assigned survives upsert and get
 *   - Replay: assigned field parsed from JSONL
 *   - Replay without assigned leaves it empty
 *   - TQL parse/compile/exec for assigned=alice, assigned=, assigned!=alice
 *   - Full roundtrip JSON -> DB -> JSON
 */

#include "testing.h"
#include "db.h"
#include "json.h"
#include "ticket.h"
#include "tql.h"

#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

/* --- helpers --- */

static int make_tmpdir(char *buf, size_t len) {
  int n = snprintf(buf, len, "/tmp/tix_test_assigned_XXXXXX");
  (void)n;
  return mkdtemp(buf) == NULL ? -1 : 0;
}

static void rmrf(const char *path) {
  char cmd[512];
  int n = snprintf(cmd, sizeof(cmd), "rm -rf '%s'", path);
  (void)n;
  int rc = system(cmd);
  (void)rc;
}

static int setup_db(const char *tmpdir, char *db_path, size_t db_len,
                    tix_db_t *db) {
  int n = snprintf(db_path, db_len, "%s/cache.db", tmpdir);
  (void)n;
  if (tix_db_open(db, db_path) != 0) { return -1; }
  if (tix_db_init_schema(db) != 0) { return -1; }
  return 0;
}

/* --- test: JSON roundtrip --- */

static void test_json_roundtrip_assigned(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  t.status = TIX_STATUS_PENDING;
  snprintf(t.id, sizeof(t.id), "t-aabbccdd");
  snprintf(t.name, sizeof(t.name), "test task");
  snprintf(t.assigned, sizeof(t.assigned), "alice");

  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&t, buf, sizeof(buf));
  ASSERT_TRUE(len > 0);

  /* Parse it back */
  tix_json_obj_t obj;
  ASSERT_EQ(tix_json_parse_line(buf, &obj), TIX_OK);

  const char *assigned = tix_json_get_str(&obj, "assigned");
  ASSERT_NOT_NULL(assigned);
  ASSERT_STR_EQ(assigned, "alice");

  TIX_PASS();
}

/* --- test: empty assigned not serialized --- */

static void test_json_empty_assigned_skipped(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  t.status = TIX_STATUS_PENDING;
  snprintf(t.id, sizeof(t.id), "t-aabbccdd");
  snprintf(t.name, sizeof(t.name), "test task");
  /* assigned left empty */

  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&t, buf, sizeof(buf));
  ASSERT_TRUE(len > 0);

  /* Should NOT contain "assigned" key */
  tix_json_obj_t obj;
  ASSERT_EQ(tix_json_parse_line(buf, &obj), TIX_OK);
  ASSERT_FALSE(tix_json_has_key(&obj, "assigned"));

  TIX_PASS();
}

/* --- test: DB roundtrip --- */

static void test_db_roundtrip_assigned(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed"); return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed"); rmrf(tmpdir); return;
  }

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  t.status = TIX_STATUS_PENDING;
  snprintf(t.id, sizeof(t.id), "t-aabbccdd");
  snprintf(t.name, sizeof(t.name), "test task");
  snprintf(t.assigned, sizeof(t.assigned), "alice");

  ASSERT_EQ(tix_db_upsert_ticket(&db, &t), TIX_OK);

  tix_ticket_t out;
  ASSERT_EQ(tix_db_get_ticket(&db, "t-aabbccdd", &out), TIX_OK);
  ASSERT_STR_EQ(out.assigned, "alice");

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: replay parses assigned from JSONL --- */

static void test_replay_assigned(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed"); return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed"); rmrf(tmpdir); return;
  }

  const char *content =
    "{\"t\":\"task\",\"id\":\"t-11111111\",\"name\":\"do stuff\","
    "\"s\":\"p\",\"assigned\":\"alice\"}\n";
  ASSERT_EQ(tix_db_replay_content(&db, content), TIX_OK);

  tix_ticket_t out;
  ASSERT_EQ(tix_db_get_ticket(&db, "t-11111111", &out), TIX_OK);
  ASSERT_STR_EQ(out.assigned, "alice");

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: replay without assigned leaves it empty --- */

static void test_replay_no_assigned(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed"); return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed"); rmrf(tmpdir); return;
  }

  const char *content =
    "{\"t\":\"task\",\"id\":\"t-22222222\",\"name\":\"old task\",\"s\":\"p\"}\n";
  ASSERT_EQ(tix_db_replay_content(&db, content), TIX_OK);

  tix_ticket_t out;
  ASSERT_EQ(tix_db_get_ticket(&db, "t-22222222", &out), TIX_OK);
  ASSERT_STR_EQ(out.assigned, "");

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: TQL parse assigned filter --- */

static void test_tql_filter_assigned(TIX_TEST_ARGS()) {
  TIX_TEST();

  tql_pipeline_t p;
  char err[256];

  ASSERT_EQ(tql_parse("tasks | assigned=alice", &p, err, sizeof(err)), TIX_OK);
  ASSERT_EQ(p.filter_count, 1u);
  ASSERT_STR_EQ(p.filters[0].field, "assigned");
  ASSERT_STR_EQ(p.filters[0].value, "alice");
  ASSERT_EQ(p.filters[0].op, TQL_OP_EQ);

  TIX_PASS();
}

/* --- test: TQL compile assigned=alice --- */

static void test_tql_compile_assigned(TIX_TEST_ARGS()) {
  TIX_TEST();

  tql_compiled_t compiled;
  char err[256];

  ASSERT_EQ(tql_prepare("tasks | assigned=alice", &compiled, err, sizeof(err)),
            TIX_OK);

  /* SQL should contain "t.assigned" */
  ASSERT_NOT_NULL(strstr(compiled.sql, "t.assigned"));

  TIX_PASS();
}

/* --- test: TQL filter assigned= (unassigned, IS NULL check) --- */

static void test_tql_filter_unassigned(TIX_TEST_ARGS()) {
  TIX_TEST();

  tql_compiled_t compiled;
  char err[256];

  ASSERT_EQ(tql_prepare("tasks | assigned=", &compiled, err, sizeof(err)),
            TIX_OK);

  /* Should use IS NULL OR = '' pattern */
  ASSERT_NOT_NULL(strstr(compiled.sql, "t.assigned"));

  TIX_PASS();
}

/* --- test: TQL filter assigned!=alice --- */

static void test_tql_filter_not_assigned(TIX_TEST_ARGS()) {
  TIX_TEST();

  tql_compiled_t compiled;
  char err[256];

  ASSERT_EQ(tql_prepare("tasks | assigned!=alice", &compiled, err, sizeof(err)),
            TIX_OK);

  ASSERT_NOT_NULL(strstr(compiled.sql, "t.assigned"));

  TIX_PASS();
}

/* --- test: TQL exec filters by assigned --- */

static void test_tql_exec_assigned(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed"); return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed"); rmrf(tmpdir); return;
  }

  /* Insert two tasks: one assigned to alice, one to bob */
  tix_ticket_t t1;
  tix_ticket_init(&t1);
  t1.type = TIX_TICKET_TASK;
  t1.status = TIX_STATUS_PENDING;
  snprintf(t1.id, sizeof(t1.id), "t-aaaaaaaa");
  snprintf(t1.name, sizeof(t1.name), "alice task");
  snprintf(t1.assigned, sizeof(t1.assigned), "alice");
  ASSERT_EQ(tix_db_upsert_ticket(&db, &t1), TIX_OK);

  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  t2.status = TIX_STATUS_PENDING;
  snprintf(t2.id, sizeof(t2.id), "t-bbbbbbbb");
  snprintf(t2.name, sizeof(t2.name), "bob task");
  snprintf(t2.assigned, sizeof(t2.assigned), "bob");
  ASSERT_EQ(tix_db_upsert_ticket(&db, &t2), TIX_OK);

  tix_ticket_t t3;
  tix_ticket_init(&t3);
  t3.type = TIX_TICKET_TASK;
  t3.status = TIX_STATUS_PENDING;
  snprintf(t3.id, sizeof(t3.id), "t-cccccccc");
  snprintf(t3.name, sizeof(t3.name), "unassigned task");
  /* no assigned */
  ASSERT_EQ(tix_db_upsert_ticket(&db, &t3), TIX_OK);

  /* Query: assigned=alice - should get exactly 1 */
  tql_compiled_t compiled;
  char err[256];
  ASSERT_EQ(tql_prepare("tasks | assigned=alice", &compiled, err, sizeof(err)),
            TIX_OK);

  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db.handle, compiled.sql, -1, &stmt, NULL);
  ASSERT_EQ(rc, 0);

  for (u32 i = 0; i < compiled.bind_count; i++) {
    if (compiled.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), compiled.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), compiled.binds[i].sval,
                        -1, SQLITE_STATIC);
    }
  }

  int count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { count++; }
  sqlite3_finalize(stmt);
  ASSERT_EQ(count, 1);

  /* Query: assigned= (unassigned) - should get exactly 1 */
  ASSERT_EQ(tql_prepare("tasks | assigned=", &compiled, err, sizeof(err)),
            TIX_OK);
  rc = sqlite3_prepare_v2(db.handle, compiled.sql, -1, &stmt, NULL);
  ASSERT_EQ(rc, 0);
  for (u32 i = 0; i < compiled.bind_count; i++) {
    if (compiled.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), compiled.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), compiled.binds[i].sval,
                        -1, SQLITE_STATIC);
    }
  }
  count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { count++; }
  sqlite3_finalize(stmt);
  ASSERT_EQ(count, 1);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: full roundtrip JSON -> DB -> JSON --- */

static void test_full_assigned_roundtrip(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed"); return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed"); rmrf(tmpdir); return;
  }

  /* Write ticket with assigned to JSON */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  t.status = TIX_STATUS_PENDING;
  snprintf(t.id, sizeof(t.id), "t-dddddddd");
  snprintf(t.name, sizeof(t.name), "full roundtrip");
  snprintf(t.assigned, sizeof(t.assigned), "agent-42");

  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&t, buf, sizeof(buf));
  ASSERT_TRUE(len > 0);

  /* Replay into DB */
  /* Add newline for replay_content */
  char content[TIX_MAX_LINE_LEN + 2];
  snprintf(content, sizeof(content), "%s\n", buf);
  ASSERT_EQ(tix_db_replay_content(&db, content), TIX_OK);

  /* Read back */
  tix_ticket_t out;
  ASSERT_EQ(tix_db_get_ticket(&db, "t-dddddddd", &out), TIX_OK);
  ASSERT_STR_EQ(out.assigned, "agent-42");

  /* Write back to JSON and verify */
  char buf2[TIX_MAX_LINE_LEN];
  sz len2 = tix_json_write_ticket(&out, buf2, sizeof(buf2));
  ASSERT_TRUE(len2 > 0);

  tix_json_obj_t obj;
  ASSERT_EQ(tix_json_parse_line(buf2, &obj), TIX_OK);
  ASSERT_STR_EQ(tix_json_get_str(&obj, "assigned"), "agent-42");

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- main --- */

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  tix_testsuite_add(&suite, "json_roundtrip_assigned",
                    test_json_roundtrip_assigned);
  tix_testsuite_add(&suite, "json_empty_assigned_skipped",
                    test_json_empty_assigned_skipped);
  tix_testsuite_add(&suite, "db_roundtrip_assigned",
                    test_db_roundtrip_assigned);
  tix_testsuite_add(&suite, "replay_assigned",
                    test_replay_assigned);
  tix_testsuite_add(&suite, "replay_no_assigned",
                    test_replay_no_assigned);
  tix_testsuite_add(&suite, "tql_filter_assigned",
                    test_tql_filter_assigned);
  tix_testsuite_add(&suite, "tql_compile_assigned",
                    test_tql_compile_assigned);
  tix_testsuite_add(&suite, "tql_filter_unassigned",
                    test_tql_filter_unassigned);
  tix_testsuite_add(&suite, "tql_filter_not_assigned",
                    test_tql_filter_not_assigned);
  tix_testsuite_add(&suite, "tql_exec_assigned",
                    test_tql_exec_assigned);
  tix_testsuite_add(&suite, "full_assigned_roundtrip",
                    test_full_assigned_roundtrip);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
