/*
 * E2E tests for resolved ticket preservation and history walking.
 *
 * Tests cover:
 *   - Replay preserves accepted/deleted tickets with resolved_at
 *   - Reject sets REJECTED then ticket line resets to PENDING
 *   - New status values round-trip through JSON and DB
 *   - TQL 'all' modifier includes resolved tickets
 *   - TQL default excludes resolved tickets
 *   - Explicit status filter overrides default exclusion
 *   - resolved_at/compacted_at round-trip through JSON and DB
 *   - Compact sets compacted_at on resolved tickets
 */

#include "testing.h"
#include "db.h"
#include "cmd.h"
#include "json.h"
#include "ticket.h"
#include "tql.h"

#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>

/* --- helpers --- */

static int make_tmpdir(char *buf, size_t len) {
  snprintf(buf, len, "/tmp/tix_test_resolved_XXXXXX");
  return mkdtemp(buf) == NULL ? -1 : 0;
}

static void rmrf(const char *path) {
  char cmd[512];
  snprintf(cmd, sizeof(cmd), "rm -rf '%s'", path);
  int rc = system(cmd);
  (void)rc;
}

static int setup_db(const char *tmpdir, char *db_path, size_t db_len,
                    tix_db_t *db) {
  snprintf(db_path, db_len, "%s/cache.db", tmpdir);
  if (tix_db_open(db, db_path) != 0) { return -1; }
  if (tix_db_init_schema(db) != 0) { return -1; }
  return 0;
}

/* --- test: replay accept preserves ticket with ACCEPTED status --- */

static void test_replay_accept_preserves(TIX_TEST_ARGS()) {
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
    "{\"t\":\"task\",\"id\":\"t-acc10001\",\"name\":\"Accept me\","
    "\"s\":\"d\",\"done_at\":\"abc123\",\"author\":\"alice\"}\n"
    "{\"t\":\"accept\",\"id\":\"t-acc10001\",\"done_at\":\"abc123\","
    "\"name\":\"Accept me\",\"timestamp\":1700000000}\n";

  tix_err_t err = tix_db_replay_content(&db, content);
  ASSERT_OK(err);

  /* ticket should exist with ACCEPTED status */
  tix_ticket_t t;
  err = tix_db_get_ticket(&db, "t-acc10001", &t);
  ASSERT_OK(err);
  ASSERT_EQ((int)t.status, (int)TIX_STATUS_ACCEPTED);
  ASSERT_STR_EQ(t.name, "Accept me");
  ASSERT_STR_EQ(t.author, "alice");

  /* resolved_at should be set from tombstone timestamp */
  ASSERT_EQ(t.resolved_at, 1700000000);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: replay delete preserves ticket with DELETED status --- */

static void test_replay_delete_preserves(TIX_TEST_ARGS()) {
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
    "{\"t\":\"issue\",\"id\":\"i-del20001\",\"name\":\"Delete me\",\"s\":\"p\"}\n"
    "{\"t\":\"delete\",\"id\":\"i-del20001\"}\n";

  tix_err_t err = tix_db_replay_content(&db, content);
  ASSERT_OK(err);

  /* issue should exist with DELETED status */
  tix_ticket_t t;
  err = tix_db_get_ticket(&db, "i-del20001", &t);
  ASSERT_OK(err);
  ASSERT_EQ((int)t.status, (int)TIX_STATUS_DELETED);
  ASSERT_GT(t.resolved_at, 0);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: replay reject sets REJECTED, then ticket line resets --- */

static void test_replay_reject_cycle(TIX_TEST_ARGS()) {
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

  /* task done, then rejected, then reset to pending */
  const char *content =
    "{\"t\":\"task\",\"id\":\"t-rej30001\",\"name\":\"Reject me\","
    "\"s\":\"d\",\"done_at\":\"def456\"}\n"
    "{\"t\":\"reject\",\"id\":\"t-rej30001\",\"done_at\":\"def456\","
    "\"reason\":\"needs work\",\"name\":\"Reject me\",\"timestamp\":1700000100}\n"
    "{\"t\":\"task\",\"id\":\"t-rej30001\",\"name\":\"Reject me\",\"s\":\"p\"}\n";

  tix_err_t err = tix_db_replay_content(&db, content);
  ASSERT_OK(err);

  /* after the full replay, ticket should be PENDING again */
  tix_ticket_t t;
  err = tix_db_get_ticket(&db, "t-rej30001", &t);
  ASSERT_OK(err);
  ASSERT_EQ((int)t.status, (int)TIX_STATUS_PENDING);

  /* tombstone should also exist */
  tix_tombstone_t ts[4];
  u32 count = 0;
  tix_db_list_tombstones(&db, 0, ts, &count, 4);
  ASSERT_GT(count, 0);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: new status values in JSON roundtrip --- */

static void test_status_json_roundtrip(TIX_TEST_ARGS()) {
  TIX_TEST();

  /* test REJECTED status */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  t.status = TIX_STATUS_REJECTED;
  snprintf(t.id, sizeof(t.id), "t-rj400001");
  snprintf(t.name, sizeof(t.name), "Rejected task");
  t.resolved_at = 1700000200;

  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&t, buf, sizeof(buf));
  ASSERT_GT((int)len, 0);

  /* should contain "s":"r" and "resolved_at" */
  ASSERT_TRUE(strstr(buf, "\"s\":\"r\"") != NULL);
  ASSERT_TRUE(strstr(buf, "\"resolved_at\":1700000200") != NULL);

  /* test DELETED status */
  t.status = TIX_STATUS_DELETED;
  snprintf(t.id, sizeof(t.id), "t-dl500001");
  snprintf(t.name, sizeof(t.name), "Deleted task");
  t.compacted_at = 1700000300;

  len = tix_json_write_ticket(&t, buf, sizeof(buf));
  ASSERT_GT((int)len, 0);

  /* should contain "s":"x" and "compacted_at" */
  ASSERT_TRUE(strstr(buf, "\"s\":\"x\"") != NULL);
  ASSERT_TRUE(strstr(buf, "\"compacted_at\":1700000300") != NULL);

  TIX_PASS();
}

/* --- test: resolved_at/compacted_at DB roundtrip --- */

static void test_lifecycle_timestamps_db(TIX_TEST_ARGS()) {
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
  t.status = TIX_STATUS_ACCEPTED;
  snprintf(t.id, sizeof(t.id), "t-lf600001");
  snprintf(t.name, sizeof(t.name), "Lifecycle test");
  t.resolved_at = 1700000400;
  t.compacted_at = 1700000500;

  tix_err_t err = tix_db_upsert_ticket(&db, &t);
  ASSERT_OK(err);

  tix_ticket_t out;
  err = tix_db_get_ticket(&db, "t-lf600001", &out);
  ASSERT_OK(err);
  ASSERT_EQ(out.resolved_at, 1700000400);
  ASSERT_EQ(out.compacted_at, 1700000500);
  ASSERT_EQ((int)out.status, (int)TIX_STATUS_ACCEPTED);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: TQL 'all' modifier parsing --- */

static void test_tql_parse_all(TIX_TEST_ARGS()) {
  TIX_TEST();

  tql_pipeline_t p;
  char err_buf[256];

  /* "tasks all" should set has_all */
  tix_err_t err = tql_parse("tasks all", &p, err_buf, sizeof(err_buf));
  ASSERT_OK(err);
  ASSERT_TRUE(p.has_all == 1);
  ASSERT_EQ((int)p.source, (int)TQL_SOURCE_TASKS);

  /* "tasks" (no all) should not set has_all */
  err = tql_parse("tasks", &p, err_buf, sizeof(err_buf));
  ASSERT_OK(err);
  ASSERT_TRUE(p.has_all == 0);

  /* "tickets all" should work too */
  err = tql_parse("tickets all", &p, err_buf, sizeof(err_buf));
  ASSERT_OK(err);
  ASSERT_TRUE(p.has_all == 1);
  ASSERT_EQ((int)p.source, (int)TQL_SOURCE_TICKETS);

  /* "tasks all" with filter should work */
  err = tql_parse("tasks all | status=accepted", &p,
                   err_buf, sizeof(err_buf));
  ASSERT_OK(err);
  ASSERT_TRUE(p.has_all == 1);
  ASSERT_EQ(p.filter_count, 1);

  TIX_PASS();
}

/* --- test: TQL default excludes resolved tickets --- */

static void test_tql_default_excludes_resolved(TIX_TEST_ARGS()) {
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

  /* insert one pending and one accepted task */
  tix_ticket_t t1;
  tix_ticket_init(&t1);
  t1.type = TIX_TICKET_TASK;
  snprintf(t1.id, sizeof(t1.id), "t-tq700001");
  snprintf(t1.name, sizeof(t1.name), "Pending task");
  tix_db_upsert_ticket(&db, &t1);

  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  t2.status = TIX_STATUS_ACCEPTED;
  snprintf(t2.id, sizeof(t2.id), "t-tq700002");
  snprintf(t2.name, sizeof(t2.name), "Accepted task");
  t2.resolved_at = 1700000600;
  tix_db_upsert_ticket(&db, &t2);

  /* compile "tasks" - should have status < 2 filter */
  tql_compiled_t compiled;
  char err_buf[256];
  tix_err_t err = tql_prepare("tasks", &compiled, err_buf, sizeof(err_buf));
  ASSERT_OK(err);

  /* SQL should contain "status < 2" */
  ASSERT_TRUE(strstr(compiled.sql, "t.status < 2") != NULL);

  /* execute: should only return the pending task */
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db.handle, compiled.sql, -1, &stmt, NULL);
  ASSERT_EQ(rc, SQLITE_OK);

  for (u32 i = 0; i < compiled.bind_count; i++) {
    if (compiled.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), compiled.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), compiled.binds[i].sval,
                        -1, SQLITE_STATIC);
    }
  }

  u32 row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 1);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: TQL 'all' includes resolved tickets --- */

static void test_tql_all_includes_resolved(TIX_TEST_ARGS()) {
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

  /* insert pending + accepted + deleted tasks */
  tix_ticket_t t1;
  tix_ticket_init(&t1);
  t1.type = TIX_TICKET_TASK;
  snprintf(t1.id, sizeof(t1.id), "t-al800001");
  snprintf(t1.name, sizeof(t1.name), "Pending");
  tix_db_upsert_ticket(&db, &t1);

  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  t2.status = TIX_STATUS_ACCEPTED;
  snprintf(t2.id, sizeof(t2.id), "t-al800002");
  snprintf(t2.name, sizeof(t2.name), "Accepted");
  tix_db_upsert_ticket(&db, &t2);

  tix_ticket_t t3;
  tix_ticket_init(&t3);
  t3.type = TIX_TICKET_TASK;
  t3.status = TIX_STATUS_DELETED;
  snprintf(t3.id, sizeof(t3.id), "t-al800003");
  snprintf(t3.name, sizeof(t3.name), "Deleted");
  tix_db_upsert_ticket(&db, &t3);

  /* compile "tasks all" - should NOT have status < 2 filter */
  tql_compiled_t compiled;
  char err_buf[256];
  tix_err_t err = tql_prepare("tasks all", &compiled,
                               err_buf, sizeof(err_buf));
  ASSERT_OK(err);
  ASSERT_TRUE(strstr(compiled.sql, "status < 2") == NULL);

  /* execute: should return all 3 tasks */
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db.handle, compiled.sql, -1, &stmt, NULL);
  ASSERT_EQ(rc, SQLITE_OK);

  for (u32 i = 0; i < compiled.bind_count; i++) {
    if (compiled.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), compiled.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), compiled.binds[i].sval,
                        -1, SQLITE_STATIC);
    }
  }

  u32 row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 3);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: explicit status filter overrides default exclusion --- */

static void test_tql_explicit_status_filter(TIX_TEST_ARGS()) {
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

  /* insert pending + accepted */
  tix_ticket_t t1;
  tix_ticket_init(&t1);
  t1.type = TIX_TICKET_TASK;
  snprintf(t1.id, sizeof(t1.id), "t-ef900001");
  snprintf(t1.name, sizeof(t1.name), "Pending");
  tix_db_upsert_ticket(&db, &t1);

  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  t2.status = TIX_STATUS_ACCEPTED;
  snprintf(t2.id, sizeof(t2.id), "t-ef900002");
  snprintf(t2.name, sizeof(t2.name), "Accepted");
  tix_db_upsert_ticket(&db, &t2);

  /* "tasks | status=accepted" should not add default exclusion */
  tql_compiled_t compiled;
  char err_buf[256];
  tix_err_t err = tql_prepare("tasks | status=accepted", &compiled,
                               err_buf, sizeof(err_buf));
  ASSERT_OK(err);
  ASSERT_TRUE(strstr(compiled.sql, "status < 2") == NULL);

  /* execute: should return only the accepted task */
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db.handle, compiled.sql, -1, &stmt, NULL);
  ASSERT_EQ(rc, SQLITE_OK);

  for (u32 i = 0; i < compiled.bind_count; i++) {
    if (compiled.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), compiled.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), compiled.binds[i].sval,
                        -1, SQLITE_STATIC);
    }
  }

  u32 row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 1);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: status_str covers new values --- */

static void test_status_str_new_values(TIX_TEST_ARGS()) {
  TIX_TEST();

  ASSERT_STR_EQ(tix_status_str(TIX_STATUS_REJECTED), "rejected");
  ASSERT_STR_EQ(tix_status_str(TIX_STATUS_DELETED), "deleted");
  ASSERT_STR_EQ(tix_status_str(TIX_STATUS_PENDING), "pending");
  ASSERT_STR_EQ(tix_status_str(TIX_STATUS_DONE), "done");
  ASSERT_STR_EQ(tix_status_str(TIX_STATUS_ACCEPTED), "accepted");

  TIX_PASS();
}

/* --- test: TQL enum sugar for new statuses --- */

static void test_tql_enum_new_statuses(TIX_TEST_ARGS()) {
  TIX_TEST();

  tql_compiled_t compiled;
  char err_buf[256];

  /* "tasks | status=rejected" should compile with enum=3 */
  tix_err_t err = tql_prepare("tasks | status=rejected", &compiled,
                               err_buf, sizeof(err_buf));
  ASSERT_OK(err);
  /* find the status bind - it should be an int with value 3 */
  int found = 0;
  for (u32 i = 0; i < compiled.bind_count; i++) {
    if (compiled.binds[i].is_int && compiled.binds[i].ival == 3) {
      found = 1;
      break;
    }
  }
  ASSERT_TRUE(found);

  /* "tasks | status=deleted" should compile with enum=4 */
  err = tql_prepare("tasks | status=deleted", &compiled,
                     err_buf, sizeof(err_buf));
  ASSERT_OK(err);
  found = 0;
  for (u32 i = 0; i < compiled.bind_count; i++) {
    if (compiled.binds[i].is_int && compiled.binds[i].ival == 4) {
      found = 1;
      break;
    }
  }
  ASSERT_TRUE(found);

  TIX_PASS();
}

/* --- test: replay JSONL with new status codes r/x --- */

static void test_replay_new_status_codes(TIX_TEST_ARGS()) {
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

  /* Ticket line with s=r (rejected) and s=x (deleted) */
  const char *content =
    "{\"t\":\"task\",\"id\":\"t-ns100001\",\"name\":\"Rejected via JSON\","
    "\"s\":\"r\",\"resolved_at\":1700000700}\n"
    "{\"t\":\"task\",\"id\":\"t-ns100002\",\"name\":\"Deleted via JSON\","
    "\"s\":\"x\",\"resolved_at\":1700000800,\"compacted_at\":1700000900}\n";

  tix_err_t err = tix_db_replay_content(&db, content);
  ASSERT_OK(err);

  tix_ticket_t t1;
  err = tix_db_get_ticket(&db, "t-ns100001", &t1);
  ASSERT_OK(err);
  ASSERT_EQ((int)t1.status, (int)TIX_STATUS_REJECTED);
  ASSERT_EQ(t1.resolved_at, 1700000700);

  tix_ticket_t t2;
  err = tix_db_get_ticket(&db, "t-ns100002", &t2);
  ASSERT_OK(err);
  ASSERT_EQ((int)t2.status, (int)TIX_STATUS_DELETED);
  ASSERT_EQ(t2.resolved_at, 1700000800);
  ASSERT_EQ(t2.compacted_at, 1700000900);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: TQL all with inline filters --- */

static void test_tql_all_with_filters(TIX_TEST_ARGS()) {
  TIX_TEST();

  tql_pipeline_t p;
  char err_buf[256];

  tix_err_t err = tql_parse("tasks all status=accepted", &p,
                             err_buf, sizeof(err_buf));
  ASSERT_OK(err);
  ASSERT_TRUE(p.has_all == 1);
  ASSERT_EQ(p.filter_count, 1);
  ASSERT_STR_EQ(p.filters[0].field, "status");
  ASSERT_STR_EQ(p.filters[0].value, "accepted");

  TIX_PASS();
}

/* --- test: TQL OR with new statuses --- */

static void test_tql_or_new_statuses(TIX_TEST_ARGS()) {
  TIX_TEST();

  tql_compiled_t compiled;
  char err_buf[256];

  /* "tasks all | status=accepted,rejected" should use IN with 2,3 */
  tix_err_t err = tql_prepare("tasks all | status=accepted,rejected",
                               &compiled, err_buf, sizeof(err_buf));
  ASSERT_OK(err);

  /* Should have IN clause */
  ASSERT_TRUE(strstr(compiled.sql, "IN") != NULL);

  TIX_PASS();
}

/* --- test: compact preserves uncommitted resolved tickets --- */

static void test_compact_preserves_uncommitted(TIX_TEST_ARGS()) {
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

  /* insert a pending task */
  tix_ticket_t t1;
  tix_ticket_init(&t1);
  t1.type = TIX_TICKET_TASK;
  snprintf(t1.id, sizeof(t1.id), "t-cp100001");
  snprintf(t1.name, sizeof(t1.name), "Still pending");
  tix_db_upsert_ticket(&db, &t1);

  /* insert an accepted task (resolved but never committed) */
  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  t2.status = TIX_STATUS_ACCEPTED;
  snprintf(t2.id, sizeof(t2.id), "t-cp100002");
  snprintf(t2.name, sizeof(t2.name), "Accepted uncommitted");
  snprintf(t2.done_at, sizeof(t2.done_at), "abc123");
  t2.resolved_at = 1700000100;
  tix_db_upsert_ticket(&db, &t2);

  /* insert the corresponding tombstone */
  tix_tombstone_t ts;
  memset(&ts, 0, sizeof(ts));
  snprintf(ts.id, sizeof(ts.id), "t-cp100002");
  snprintf(ts.done_at, sizeof(ts.done_at), "abc123");
  snprintf(ts.name, sizeof(ts.name), "Accepted uncommitted");
  ts.is_accept = 1;
  ts.timestamp = 1700000100;
  tix_db_upsert_tombstone(&db, &ts);

  /* insert a deleted task (also uncommitted) */
  tix_ticket_t t3;
  tix_ticket_init(&t3);
  t3.type = TIX_TICKET_TASK;
  t3.status = TIX_STATUS_DELETED;
  snprintf(t3.id, sizeof(t3.id), "t-cp100003");
  snprintf(t3.name, sizeof(t3.name), "Deleted uncommitted");
  t3.resolved_at = 1700000200;
  tix_db_upsert_ticket(&db, &t3);

  /* create plan.jsonl with all three */
  char plan_path[512];
  snprintf(plan_path, sizeof(plan_path), "%s/plan.jsonl", tmpdir);
  FILE *fp = fopen(plan_path, "w");
  ASSERT_NOT_NULL(fp);
  fprintf(fp,
    "{\"t\":\"task\",\"id\":\"t-cp100001\",\"name\":\"Still pending\",\"s\":\"p\"}\n"
    "{\"t\":\"task\",\"id\":\"t-cp100002\",\"name\":\"Accepted uncommitted\","
    "\"s\":\"d\",\"done_at\":\"abc123\"}\n"
    "{\"t\":\"accept\",\"id\":\"t-cp100002\",\"done_at\":\"abc123\","
    "\"name\":\"Accepted uncommitted\"}\n"
    "{\"t\":\"task\",\"id\":\"t-cp100003\",\"name\":\"Deleted uncommitted\",\"s\":\"p\"}\n"
    "{\"t\":\"delete\",\"id\":\"t-cp100003\"}\n");
  fclose(fp);

  /* simulate mark_uncommitted_resolved: protect the resolved tickets */
  sqlite3_exec(db.handle,
    "CREATE TEMP TABLE _compact_uncommitted(id TEXT PRIMARY KEY)",
    NULL, NULL, NULL);
  sqlite3_exec(db.handle,
    "INSERT INTO _compact_uncommitted VALUES('t-cp100002')",
    NULL, NULL, NULL);
  sqlite3_exec(db.handle,
    "INSERT INTO _compact_uncommitted VALUES('t-cp100003')",
    NULL, NULL, NULL);

  /* run compact */
  tix_err_t err = tix_plan_compact(plan_path, &db);
  ASSERT_OK(err);

  /* read back plan.jsonl and verify content */
  fp = fopen(plan_path, "r");
  ASSERT_NOT_NULL(fp);
  char content[4096];
  size_t nread = fread(content, 1, sizeof(content) - 1, fp);
  content[nread] = '\0';
  fclose(fp);

  /* pending task should be present */
  ASSERT_STR_CONTAINS(content, "t-cp100001");
  ASSERT_STR_CONTAINS(content, "Still pending");

  /* accepted task should be preserved (uncommitted) */
  ASSERT_STR_CONTAINS(content, "t-cp100002");
  ASSERT_STR_CONTAINS(content, "Accepted uncommitted");

  /* accept tombstone should also be preserved */
  ASSERT_STR_CONTAINS(content, "\"t\":\"accept\"");

  /* deleted task should be preserved (uncommitted) */
  ASSERT_STR_CONTAINS(content, "t-cp100003");

  /* delete marker should be preserved */
  ASSERT_STR_CONTAINS(content, "\"t\":\"delete\"");

  sqlite3_exec(db.handle,
    "DROP TABLE IF EXISTS _compact_uncommitted", NULL, NULL, NULL);
  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: compact removes committed resolved tickets normally --- */

static void test_compact_removes_committed(TIX_TEST_ARGS()) {
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

  /* insert a pending task */
  tix_ticket_t t1;
  tix_ticket_init(&t1);
  t1.type = TIX_TICKET_TASK;
  snprintf(t1.id, sizeof(t1.id), "t-cr200001");
  snprintf(t1.name, sizeof(t1.name), "Still pending");
  tix_db_upsert_ticket(&db, &t1);

  /* insert an accepted task (already committed) */
  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  t2.status = TIX_STATUS_ACCEPTED;
  snprintf(t2.id, sizeof(t2.id), "t-cr200002");
  snprintf(t2.name, sizeof(t2.name), "Accepted committed");
  t2.resolved_at = 1700000300;
  tix_db_upsert_ticket(&db, &t2);

  char plan_path[512];
  snprintf(plan_path, sizeof(plan_path), "%s/plan.jsonl", tmpdir);
  FILE *fp = fopen(plan_path, "w");
  ASSERT_NOT_NULL(fp);
  fprintf(fp,
    "{\"t\":\"task\",\"id\":\"t-cr200001\",\"name\":\"Still pending\",\"s\":\"p\"}\n"
    "{\"t\":\"task\",\"id\":\"t-cr200002\",\"name\":\"Accepted committed\","
    "\"s\":\"d\",\"done_at\":\"def456\"}\n"
    "{\"t\":\"accept\",\"id\":\"t-cr200002\",\"done_at\":\"def456\","
    "\"name\":\"Accepted committed\"}\n");
  fclose(fp);

  /* empty _compact_uncommitted = nothing protected, all committed */
  sqlite3_exec(db.handle,
    "CREATE TEMP TABLE _compact_uncommitted(id TEXT PRIMARY KEY)",
    NULL, NULL, NULL);

  tix_err_t err = tix_plan_compact(plan_path, &db);
  ASSERT_OK(err);

  /* read back */
  fp = fopen(plan_path, "r");
  ASSERT_NOT_NULL(fp);
  char content[4096];
  size_t nread = fread(content, 1, sizeof(content) - 1, fp);
  content[nread] = '\0';
  fclose(fp);

  /* pending task should be present */
  ASSERT_STR_CONTAINS(content, "t-cr200001");

  /* accepted task should be REMOVED (it was committed) */
  ASSERT_TRUE(strstr(content, "t-cr200002") == NULL);
  ASSERT_TRUE(strstr(content, "Accepted committed") == NULL);

  sqlite3_exec(db.handle,
    "DROP TABLE IF EXISTS _compact_uncommitted", NULL, NULL, NULL);
  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: compact without temp table (backwards compat) --- */

static void test_compact_no_temp_table(TIX_TEST_ARGS()) {
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

  /* insert a pending task and an accepted task */
  tix_ticket_t t1;
  tix_ticket_init(&t1);
  t1.type = TIX_TICKET_TASK;
  snprintf(t1.id, sizeof(t1.id), "t-nt300001");
  snprintf(t1.name, sizeof(t1.name), "Pending");
  tix_db_upsert_ticket(&db, &t1);

  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  t2.status = TIX_STATUS_ACCEPTED;
  snprintf(t2.id, sizeof(t2.id), "t-nt300002");
  snprintf(t2.name, sizeof(t2.name), "Accepted");
  tix_db_upsert_ticket(&db, &t2);

  char plan_path[512];
  snprintf(plan_path, sizeof(plan_path), "%s/plan.jsonl", tmpdir);
  FILE *fp = fopen(plan_path, "w");
  ASSERT_NOT_NULL(fp);
  fprintf(fp,
    "{\"t\":\"task\",\"id\":\"t-nt300001\",\"name\":\"Pending\",\"s\":\"p\"}\n"
    "{\"t\":\"task\",\"id\":\"t-nt300002\",\"name\":\"Accepted\",\"s\":\"a\"}\n");
  fclose(fp);

  /* do NOT create _compact_uncommitted - test backwards compat.
     Without the temp table, resolved tickets should still be removed
     (the SELECT from _compact_uncommitted will fail, so no uncommitted
     tickets are written). */
  tix_err_t err = tix_plan_compact(plan_path, &db);
  ASSERT_OK(err);

  fp = fopen(plan_path, "r");
  ASSERT_NOT_NULL(fp);
  char content[4096];
  size_t nread = fread(content, 1, sizeof(content) - 1, fp);
  content[nread] = '\0';
  fclose(fp);

  /* pending should be present */
  ASSERT_STR_CONTAINS(content, "t-nt300001");

  /* accepted should be removed (no protection table) */
  ASSERT_TRUE(strstr(content, "t-nt300002") == NULL);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- main --- */

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  tix_testsuite_add(&suite, "replay_accept_preserves",
                    test_replay_accept_preserves);
  tix_testsuite_add(&suite, "replay_delete_preserves",
                    test_replay_delete_preserves);
  tix_testsuite_add(&suite, "replay_reject_cycle",
                    test_replay_reject_cycle);
  tix_testsuite_add(&suite, "status_json_roundtrip",
                    test_status_json_roundtrip);
  tix_testsuite_add(&suite, "lifecycle_timestamps_db",
                    test_lifecycle_timestamps_db);
  tix_testsuite_add(&suite, "tql_parse_all",
                    test_tql_parse_all);
  tix_testsuite_add(&suite, "tql_default_excludes_resolved",
                    test_tql_default_excludes_resolved);
  tix_testsuite_add(&suite, "tql_all_includes_resolved",
                    test_tql_all_includes_resolved);
  tix_testsuite_add(&suite, "tql_explicit_status_filter",
                    test_tql_explicit_status_filter);
  tix_testsuite_add(&suite, "status_str_new_values",
                    test_status_str_new_values);
  tix_testsuite_add(&suite, "tql_enum_new_statuses",
                    test_tql_enum_new_statuses);
  tix_testsuite_add(&suite, "replay_new_status_codes",
                    test_replay_new_status_codes);
  tix_testsuite_add(&suite, "tql_all_with_filters",
                    test_tql_all_with_filters);
  tix_testsuite_add(&suite, "tql_or_new_statuses",
                    test_tql_or_new_statuses);
  tix_testsuite_add(&suite, "compact_preserves_uncommitted",
                    test_compact_preserves_uncommitted);
  tix_testsuite_add(&suite, "compact_removes_committed",
                    test_compact_removes_committed);
  tix_testsuite_add(&suite, "compact_no_temp_table",
                    test_compact_no_temp_table);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
