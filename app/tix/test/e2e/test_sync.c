#include "testing.h"
#include "db.h"
#include "cmd.h"
#include "json.h"
#include "ticket.h"

#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

/* --- helpers --- */

static int make_tmpdir(char *buf, size_t len) {
  snprintf(buf, len, "/tmp/tix_test_sync_XXXXXX");
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

/* --- test: replay_content parses ticket lines additively --- */

static void test_replay_content_basic(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed");
    return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed");
    rmrf(tmpdir);
    return;
  }

  /* replay some content */
  const char *content =
    "{\"t\":\"task\",\"id\":\"t-aabbcc01\",\"name\":\"Do thing\",\"s\":\"p\"}\n"
    "{\"t\":\"issue\",\"id\":\"i-aabbcc02\",\"name\":\"Bug found\",\"s\":\"p\"}\n";

  tix_err_t err = tix_db_replay_content(&db, content);
  ASSERT_OK(err);

  /* verify both exist */
  tix_ticket_t t;
  err = tix_db_get_ticket(&db, "t-aabbcc01", &t);
  ASSERT_OK(err);
  ASSERT_STR_EQ(t.name, "Do thing");
  ASSERT_EQ(t.type, TIX_TICKET_TASK);

  err = tix_db_get_ticket(&db, "i-aabbcc02", &t);
  ASSERT_OK(err);
  ASSERT_STR_EQ(t.name, "Bug found");
  ASSERT_EQ(t.type, TIX_TICKET_ISSUE);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: replay_content handles delete markers --- */

static void test_replay_content_delete(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed");
    return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed");
    rmrf(tmpdir);
    return;
  }

  const char *content =
    "{\"t\":\"issue\",\"id\":\"i-dd001122\",\"name\":\"Temp issue\",\"s\":\"p\"}\n"
    "{\"t\":\"delete\",\"id\":\"i-dd001122\"}\n";

  tix_err_t err = tix_db_replay_content(&db, content);
  ASSERT_OK(err);

  /* issue should be gone */
  tix_ticket_t t;
  err = tix_db_get_ticket(&db, "i-dd001122", &t);
  ASSERT_EQ(err, TIX_ERR_NOT_FOUND);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: replay_content handles accept tombstones --- */

static void test_replay_content_accept(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed");
    return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed");
    rmrf(tmpdir);
    return;
  }

  const char *content =
    "{\"t\":\"task\",\"id\":\"t-ee001122\",\"name\":\"Accepted task\",\"s\":\"d\",\"done_at\":\"abc123\"}\n"
    "{\"t\":\"accept\",\"id\":\"t-ee001122\",\"done_at\":\"abc123\",\"reason\":\"\",\"name\":\"Accepted task\"}\n";

  tix_err_t err = tix_db_replay_content(&db, content);
  ASSERT_OK(err);

  /* task should be deleted (accepted), tombstone should exist */
  tix_ticket_t t;
  err = tix_db_get_ticket(&db, "t-ee001122", &t);
  ASSERT_EQ(err, TIX_ERR_NOT_FOUND);

  tix_tombstone_t ts[4];
  u32 count = 0;
  tix_db_list_tombstones(&db, 1, ts, &count, 4);
  ASSERT_GT(count, 0);
  ASSERT_STR_EQ(ts[0].id, "t-ee001122");

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: replay is additive (doesn't nuke existing data) --- */

static void test_replay_additive(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed");
    return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed");
    rmrf(tmpdir);
    return;
  }

  /* first replay */
  const char *content1 =
    "{\"t\":\"task\",\"id\":\"t-11111111\",\"name\":\"First\",\"s\":\"p\"}\n";
  tix_db_replay_content(&db, content1);

  /* second replay (different content) */
  const char *content2 =
    "{\"t\":\"task\",\"id\":\"t-22222222\",\"name\":\"Second\",\"s\":\"p\"}\n";
  tix_db_replay_content(&db, content2);

  /* both should exist */
  tix_ticket_t t;
  tix_err_t err = tix_db_get_ticket(&db, "t-11111111", &t);
  ASSERT_OK(err);
  ASSERT_STR_EQ(t.name, "First");

  err = tix_db_get_ticket(&db, "t-22222222", &t);
  ASSERT_OK(err);
  ASSERT_STR_EQ(t.name, "Second");

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: last-write-wins for duplicate IDs --- */

static void test_replay_last_write_wins(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed");
    return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed");
    rmrf(tmpdir);
    return;
  }

  const char *content =
    "{\"t\":\"task\",\"id\":\"t-33333333\",\"name\":\"Version 1\",\"s\":\"p\"}\n"
    "{\"t\":\"task\",\"id\":\"t-33333333\",\"name\":\"Version 2\",\"s\":\"d\",\"done_at\":\"abc\"}\n";

  tix_db_replay_content(&db, content);

  tix_ticket_t t;
  tix_err_t err = tix_db_get_ticket(&db, "t-33333333", &t);
  ASSERT_OK(err);
  ASSERT_STR_EQ(t.name, "Version 2");
  ASSERT_EQ(t.status, TIX_STATUS_DONE);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: resolve_ref returns correct states --- */

static void test_resolve_ref(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed");
    return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed");
    rmrf(tmpdir);
    return;
  }

  /* add a live ticket */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-44444444");
  snprintf(t.name, sizeof(t.name), "Live task");
  tix_db_upsert_ticket(&db, &t);

  /* add a tombstone */
  tix_tombstone_t ts;
  memset(&ts, 0, sizeof(ts));
  snprintf(ts.id, sizeof(ts.id), "t-55555555");
  snprintf(ts.name, sizeof(ts.name), "Accepted task");
  ts.is_accept = 1;
  tix_db_upsert_tombstone(&db, &ts);

  /* resolved: live ticket */
  ASSERT_EQ(tix_db_resolve_ref(&db, "t-44444444"), TIX_REF_RESOLVED);

  /* stale: in tombstones */
  ASSERT_EQ(tix_db_resolve_ref(&db, "t-55555555"), TIX_REF_STALE);

  /* broken: nowhere */
  ASSERT_EQ(tix_db_resolve_ref(&db, "t-99999999"), TIX_REF_BROKEN);

  /* broken: NULL/empty */
  ASSERT_EQ(tix_db_resolve_ref(&db, ""), TIX_REF_BROKEN);
  ASSERT_EQ(tix_db_resolve_ref(&db, NULL), TIX_REF_BROKEN);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: count_refs reports broken and stale correctly --- */

static void test_count_refs(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed");
    return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed");
    rmrf(tmpdir);
    return;
  }

  /* task with broken dep and broken created_from */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-66666666");
  snprintf(t.name, sizeof(t.name), "Task with refs");
  snprintf(t.created_from, sizeof(t.created_from), "i-deadbeef");
  t.dep_count = 1;
  snprintf(t.deps[0], TIX_MAX_ID_LEN, "t-00000000");
  tix_db_upsert_ticket(&db, &t);

  /* add a tombstone for a stale supersedes ref */
  tix_tombstone_t ts;
  memset(&ts, 0, sizeof(ts));
  snprintf(ts.id, sizeof(ts.id), "t-77777777");
  snprintf(ts.name, sizeof(ts.name), "Old task");
  ts.is_accept = 1;
  tix_db_upsert_tombstone(&db, &ts);

  /* task with stale supersedes */
  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  snprintf(t2.id, sizeof(t2.id), "t-88888888");
  snprintf(t2.name, sizeof(t2.name), "New task");
  snprintf(t2.supersedes, sizeof(t2.supersedes), "t-77777777");
  tix_db_upsert_ticket(&db, &t2);

  tix_ref_counts_t counts;
  tix_err_t err = tix_db_count_refs(&db, &counts);
  ASSERT_OK(err);

  ASSERT_EQ(counts.broken_deps, 1);
  ASSERT_EQ(counts.broken_created_from, 1);
  ASSERT_EQ(counts.stale_supersedes, 1);
  ASSERT_EQ(counts.broken_supersedes, 0);
  ASSERT_EQ(counts.broken_parents, 0);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: clear_tickets removes everything --- */

static void test_clear_tickets(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed");
    return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed");
    rmrf(tmpdir);
    return;
  }

  /* add some data */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-aaaaaaaa");
  snprintf(t.name, sizeof(t.name), "Task A");
  tix_db_upsert_ticket(&db, &t);

  tix_tombstone_t ts;
  memset(&ts, 0, sizeof(ts));
  snprintf(ts.id, sizeof(ts.id), "t-bbbbbbbb");
  ts.is_accept = 1;
  tix_db_upsert_tombstone(&db, &ts);

  /* clear */
  tix_err_t err = tix_db_clear_tickets(&db);
  ASSERT_OK(err);

  /* verify empty */
  u32 count = 0;
  tix_db_count_tickets(&db, TIX_TICKET_TASK, TIX_STATUS_PENDING, &count);
  ASSERT_EQ(count, 0);

  tix_ticket_t out;
  err = tix_db_get_ticket(&db, "t-aaaaaaaa", &out);
  ASSERT_EQ(err, TIX_ERR_NOT_FOUND);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: replay_jsonl_file reads from file --- */

static void test_replay_jsonl_file(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed");
    return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed");
    rmrf(tmpdir);
    return;
  }

  /* write a plan.jsonl file */
  char plan_path[512];
  snprintf(plan_path, sizeof(plan_path), "%s/plan.jsonl", tmpdir);
  FILE *fp = fopen(plan_path, "w");
  if (fp == NULL) {
    TIX_FAIL_MSG("fopen failed");
    rmrf(tmpdir);
    return;
  }
  fprintf(fp,
    "{\"t\":\"task\",\"id\":\"t-ff001122\",\"name\":\"From file\",\"s\":\"p\"}\n"
    "{\"t\":\"note\",\"id\":\"n-ff001122\",\"name\":\"A note\",\"s\":\"p\"}\n");
  fclose(fp);

  tix_err_t err = tix_db_replay_jsonl_file(&db, plan_path);
  ASSERT_OK(err);

  tix_ticket_t t;
  err = tix_db_get_ticket(&db, "t-ff001122", &t);
  ASSERT_OK(err);
  ASSERT_STR_EQ(t.name, "From file");

  err = tix_db_get_ticket(&db, "n-ff001122", &t);
  ASSERT_OK(err);
  ASSERT_EQ(t.type, TIX_TICKET_NOTE);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: denormalized fields survive roundtrip --- */

static void test_denormalized_fields(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed");
    return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed");
    rmrf(tmpdir);
    return;
  }

  const char *content =
    "{\"t\":\"task\",\"id\":\"t-de001122\",\"name\":\"With refs\",\"s\":\"p\","
    "\"created_from\":\"i-dead0001\","
    "\"created_from_name\":\"Original issue\","
    "\"supersedes\":\"t-dead0002\","
    "\"supersedes_name\":\"Old attempt\","
    "\"supersedes_reason\":\"too complex\"}\n";

  tix_db_replay_content(&db, content);

  tix_ticket_t t;
  tix_err_t err = tix_db_get_ticket(&db, "t-de001122", &t);
  ASSERT_OK(err);
  ASSERT_STR_EQ(t.created_from_name, "Original issue");
  ASSERT_STR_EQ(t.supersedes_name, "Old attempt");
  ASSERT_STR_EQ(t.supersedes_reason, "too complex");

  /* verify json write includes the fields */
  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&t, buf, sizeof(buf));
  ASSERT_GT(len, 0);
  ASSERT_STR_CONTAINS(buf, "created_from_name");
  ASSERT_STR_CONTAINS(buf, "Original issue");
  ASSERT_STR_CONTAINS(buf, "supersedes_name");
  ASSERT_STR_CONTAINS(buf, "Old attempt");
  ASSERT_STR_CONTAINS(buf, "supersedes_reason");
  ASSERT_STR_CONTAINS(buf, "too complex");

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- test: legacy desc field is still parsed --- */

static void test_legacy_desc_field(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (make_tmpdir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mkdtemp failed");
    return;
  }

  char db_path[512];
  tix_db_t db;
  if (setup_db(tmpdir, db_path, sizeof(db_path), &db) != 0) {
    TIX_FAIL_MSG("setup_db failed");
    rmrf(tmpdir);
    return;
  }

  /* old ralph-style issue with "desc" instead of "name" */
  const char *content =
    "{\"t\":\"issue\",\"id\":\"i-legacy01\",\"desc\":\"API returns 500\",\"s\":\"p\"}\n";

  tix_db_replay_content(&db, content);

  tix_ticket_t t;
  tix_err_t err = tix_db_get_ticket(&db, "i-legacy01", &t);
  ASSERT_OK(err);
  ASSERT_STR_EQ(t.name, "API returns 500");
  ASSERT_EQ(t.type, TIX_TICKET_ISSUE);

  tix_db_close(&db);
  rmrf(tmpdir);
  TIX_PASS();
}

/* --- main --- */

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  tix_testsuite_add(&suite, "replay_content_basic", test_replay_content_basic);
  tix_testsuite_add(&suite, "replay_content_delete", test_replay_content_delete);
  tix_testsuite_add(&suite, "replay_content_accept", test_replay_content_accept);
  tix_testsuite_add(&suite, "replay_additive", test_replay_additive);
  tix_testsuite_add(&suite, "replay_last_write_wins", test_replay_last_write_wins);
  tix_testsuite_add(&suite, "resolve_ref", test_resolve_ref);
  tix_testsuite_add(&suite, "count_refs", test_count_refs);
  tix_testsuite_add(&suite, "clear_tickets", test_clear_tickets);
  tix_testsuite_add(&suite, "replay_jsonl_file", test_replay_jsonl_file);
  tix_testsuite_add(&suite, "denormalized_fields", test_denormalized_fields);
  tix_testsuite_add(&suite, "legacy_desc_field", test_legacy_desc_field);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
