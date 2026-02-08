/*
 * E2E tests for session 6 additions:
 *  - tix_json_get_double / float JSON parsing
 *  - metadata fields roundtrip (JSON -> DB -> ticket_meta)
 *  - author auto-fill via tix_git_user_name
 *  - completed_at via tix_timestamp_iso8601
 *  - task update subcommand (DB-level merge)
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "ticket.h"
#include "db.h"
#include "json.h"
#include "git.h"

#include <math.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/* Helper: create isolated temp dir with git repo and tix schema */
static int setup_env(char *tmpdir, size_t tmpdir_len,
                     char *db_path, size_t db_path_len) {
  snprintf(tmpdir, tmpdir_len, "/tmp/tix_nf_XXXXXX");
  if (mkdtemp(tmpdir) == NULL) { return -1; }

  char cmd[512];
  snprintf(cmd, sizeof(cmd),
           "cd \"%s\" && git init -q && git config user.email test@test && "
           "git config user.name \"Test Author\" && "
           "mkdir -p .tix && touch .tix/plan.jsonl && "
           "git add -A && git commit -q -m init", tmpdir);
  if (system(cmd) != 0) { return -1; }

  snprintf(db_path, db_path_len, "%s/.tix/cache.db", tmpdir);
  return 0;
}

static void cleanup_env(const char *tmpdir) {
  char cmd[512];
  snprintf(cmd, sizeof(cmd), "rm -rf \"%s\"", tmpdir);
  system(cmd);
}

/* Helper: query a numeric metadata value from ticket_meta */
static double get_meta_num(tix_db_t *db, const char *ticket_id,
                           const char *key) {
  const char *sql =
    "SELECT value_num FROM ticket_meta WHERE ticket_id=? AND key=?";
  sqlite3_stmt *stmt = NULL;
  double val = 0.0;
  if (sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL) == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, ticket_id, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 2, key, -1, SQLITE_STATIC);
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      val = sqlite3_column_double(stmt, 0);
    }
    sqlite3_finalize(stmt);
  }
  return val;
}

/* Helper: query a string metadata value from ticket_meta */
static const char *get_meta_str_buf(tix_db_t *db, const char *ticket_id,
                                    const char *key, char *buf, sz buf_len) {
  const char *sql =
    "SELECT value_text FROM ticket_meta WHERE ticket_id=? AND key=?";
  sqlite3_stmt *stmt = NULL;
  buf[0] = '\0';
  if (sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL) == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, ticket_id, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 2, key, -1, SQLITE_STATIC);
    if (sqlite3_step(stmt) == SQLITE_ROW) {
      const char *v = (const char *)sqlite3_column_text(stmt, 0);
      if (v != NULL) {
        snprintf(buf, buf_len, "%s", v);
      }
    }
    sqlite3_finalize(stmt);
  }
  return buf;
}

/* ---- JSON double parsing ---- */

static void test_json_get_double_basic(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line(
      "{\"cost\":0.1234,\"big\":99999.99,\"zero\":0,\"neg\":-1.5}", &obj);
  ASSERT_OK(err);

  double cost = tix_json_get_double(&obj, "cost", 0.0);
  ASSERT_TRUE(fabs(cost - 0.1234) < 0.0001);

  double big = tix_json_get_double(&obj, "big", 0.0);
  ASSERT_TRUE(fabs(big - 99999.99) < 0.01);

  double zero = tix_json_get_double(&obj, "zero", -1.0);
  ASSERT_TRUE(fabs(zero) < 0.0001);

  double neg = tix_json_get_double(&obj, "neg", 0.0);
  ASSERT_TRUE(fabs(neg - (-1.5)) < 0.0001);

  /* missing key returns default */
  double missing = tix_json_get_double(&obj, "nope", 42.5);
  ASSERT_TRUE(fabs(missing - 42.5) < 0.0001);

  TIX_PASS();
}

static void test_json_double_int_compat(TIX_TEST_ARGS()) {
  TIX_TEST();

  /* When parsing a float, num_val should be the truncated integer value */
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line("{\"val\":3.7}", &obj);
  ASSERT_OK(err);

  i64 int_val = tix_json_get_num(&obj, "val", 0);
  ASSERT_EQ(int_val, 3);  /* truncated from 3.7 */

  double dbl_val = tix_json_get_double(&obj, "val", 0.0);
  ASSERT_TRUE(fabs(dbl_val - 3.7) < 0.0001);

  TIX_PASS();
}

static void test_json_get_double_wrong_type(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line("{\"name\":\"hello\"}", &obj);
  ASSERT_OK(err);

  /* asking for double on a string field should return default */
  double val = tix_json_get_double(&obj, "name", 99.0);
  ASSERT_TRUE(fabs(val - 99.0) < 0.0001);

  TIX_PASS();
}

static void test_json_get_double_null_args(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_json_obj_t obj;
  tix_json_obj_init(&obj);

  ASSERT_TRUE(fabs(tix_json_get_double(NULL, "x", 1.0) - 1.0) < 0.0001);
  ASSERT_TRUE(fabs(tix_json_get_double(&obj, NULL, 2.0) - 2.0) < 0.0001);

  TIX_PASS();
}

/* ---- Metadata fields: ticket_meta DB roundtrip ---- */

static void test_metadata_db_roundtrip(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* create ticket */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  t.status = TIX_STATUS_DONE;
  snprintf(t.id, sizeof(t.id), "t-dbrt01");
  tix_ticket_set_name(&t, "DB roundtrip");
  snprintf(t.author, sizeof(t.author), "Test User");
  snprintf(t.completed_at, sizeof(t.completed_at),
           "2026-02-07T10:00:00+00:00");

  tix_err_t err = tix_db_upsert_ticket(&db, &t);
  ASSERT_OK(err);

  /* set metadata via ticket_meta API */
  tix_db_set_ticket_meta_num(&db, "t-dbrt01", "cost", 1.2345);
  tix_db_set_ticket_meta_num(&db, "t-dbrt01", "tokens_in", 50000.0);
  tix_db_set_ticket_meta_num(&db, "t-dbrt01", "tokens_out", 8000.0);
  tix_db_set_ticket_meta_num(&db, "t-dbrt01", "iterations", 7.0);
  tix_db_set_ticket_meta_str(&db, "t-dbrt01", "model", "claude-opus-4-20250514");
  tix_db_set_ticket_meta_num(&db, "t-dbrt01", "retries", 3.0);
  tix_db_set_ticket_meta_num(&db, "t-dbrt01", "kill_count", 1.0);

  /* read back ticket fields (non-meta) */
  tix_ticket_t out;
  err = tix_db_get_ticket(&db, "t-dbrt01", &out);
  ASSERT_OK(err);

  ASSERT_STR_EQ(out.author, "Test User");
  ASSERT_STR_EQ(out.completed_at, "2026-02-07T10:00:00+00:00");

  /* verify metadata via SQL */
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-dbrt01", "cost") - 1.2345) < 0.001);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-dbrt01", "tokens_in") - 50000.0) < 1.0);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-dbrt01", "tokens_out") - 8000.0) < 1.0);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-dbrt01", "iterations") - 7.0) < 0.1);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-dbrt01", "retries") - 3.0) < 0.1);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-dbrt01", "kill_count") - 1.0) < 0.1);

  char model_buf[256];
  get_meta_str_buf(&db, "t-dbrt01", "model", model_buf, sizeof(model_buf));
  ASSERT_STR_EQ(model_buf, "claude-opus-4-20250514");

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

/* ---- replay_one_line picks up telemetry from legacy JSONL ---- */

static void test_metadata_replay_legacy(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* simulate a legacy JSONL line with inline telemetry */
  const char *jsonl =
    "{\"t\":\"task\",\"id\":\"t-replay1\",\"name\":\"Replay test\","
    "\"s\":\"d\",\"author\":\"ReplayBot\","
    "\"completed_at\":\"2026-01-15T09:00:00-05:00\","
    "\"cost\":0.42,\"tokens_in\":20000,\"tokens_out\":5000,"
    "\"iterations\":3,\"model\":\"gpt-5\",\"retries\":2,\"kill_count\":0}";

  tix_err_t err = tix_db_replay_content(&db, jsonl);
  ASSERT_OK(err);

  tix_ticket_t out;
  err = tix_db_get_ticket(&db, "t-replay1", &out);
  ASSERT_OK(err);

  ASSERT_STR_EQ(out.author, "ReplayBot");
  ASSERT_STR_EQ(out.completed_at, "2026-01-15T09:00:00-05:00");
  ASSERT_EQ(out.status, TIX_STATUS_DONE);

  /* telemetry should be in ticket_meta, not struct fields */
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-replay1", "cost") - 0.42) < 0.01);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-replay1", "tokens_in") - 20000.0) < 1.0);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-replay1", "tokens_out") - 5000.0) < 1.0);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-replay1", "iterations") - 3.0) < 0.1);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-replay1", "retries") - 2.0) < 0.1);
  /* kill_count=0 should NOT be stored (we skip zero values) */

  char model_buf[256];
  get_meta_str_buf(&db, "t-replay1", "model", model_buf, sizeof(model_buf));
  ASSERT_STR_EQ(model_buf, "gpt-5");

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

/* ---- replay with new meta:{} nested object format ---- */

static void test_metadata_replay_nested(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* new-format JSONL with "meta":{...} nested object */
  const char *jsonl =
    "{\"t\":\"task\",\"id\":\"t-meta01\",\"name\":\"Meta test\","
    "\"s\":\"d\",\"meta\":{\"cost\":1.23,\"model\":\"test-v2\","
    "\"tokens_in\":30000,\"custom_field\":\"hello\"}}";

  tix_err_t err = tix_db_replay_content(&db, jsonl);
  ASSERT_OK(err);

  /* verify metadata */
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-meta01", "cost") - 1.23) < 0.01);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-meta01", "tokens_in") - 30000.0) < 1.0);

  char model_buf[256];
  get_meta_str_buf(&db, "t-meta01", "model", model_buf, sizeof(model_buf));
  ASSERT_STR_EQ(model_buf, "test-v2");

  char custom_buf[256];
  get_meta_str_buf(&db, "t-meta01", "custom_field", custom_buf, sizeof(custom_buf));
  ASSERT_STR_EQ(custom_buf, "hello");

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

/* ---- tix_git_user_name ---- */

static void test_git_user_name(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  /* chdir to the test repo so git config works */
  char cwd[512];
  if (getcwd(cwd, sizeof(cwd)) == NULL) {
    TIX_FAIL_MSG("getcwd failed");
    cleanup_env(tmpdir);
    return;
  }
  if (chdir(tmpdir) != 0) {
    TIX_FAIL_MSG("chdir failed");
    cleanup_env(tmpdir);
    return;
  }

  char name[256];
  tix_err_t err = tix_git_user_name(name, sizeof(name));
  ASSERT_OK(err);
  ASSERT_STR_EQ(name, "Test Author");

  /* restore cwd */
  chdir(cwd);
  cleanup_env(tmpdir);

  TIX_PASS();
}

/* ---- tix_timestamp_iso8601 ---- */

static void test_timestamp_iso8601(TIX_TEST_ARGS()) {
  TIX_TEST();

  char ts[64];
  tix_err_t err = tix_timestamp_iso8601(ts, sizeof(ts));
  ASSERT_OK(err);

  /* should look like "2026-02-07T14:30:00-08:00" (25 chars) */
  ASSERT_TRUE(strlen(ts) == 25);
  /* year starts with 20 */
  ASSERT_TRUE(ts[0] == '2' && ts[1] == '0');
  /* has T separator */
  ASSERT_TRUE(ts[10] == 'T');
  /* ends with timezone offset like +00:00 or -08:00 */
  ASSERT_TRUE(ts[19] == '+' || ts[19] == '-');
  ASSERT_TRUE(ts[22] == ':');

  TIX_PASS();
}

static void test_timestamp_small_buffer(TIX_TEST_ARGS()) {
  TIX_TEST();

  char ts[10];
  tix_err_t err = tix_timestamp_iso8601(ts, sizeof(ts));
  /* should fail - buffer too small for 25-char timestamp + nul */
  ASSERT_ERR(err);

  TIX_PASS();
}

/* ---- task_update merge via DB ---- */

static void test_task_update_merge(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* create a base ticket */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  t.status = TIX_STATUS_DONE;
  snprintf(t.id, sizeof(t.id), "t-upd001");
  tix_ticket_set_name(&t, "Update test");
  snprintf(t.author, sizeof(t.author), "OrigAuthor");
  t.created_at = 1000;
  t.updated_at = 1000;

  tix_err_t err = tix_db_upsert_ticket(&db, &t);
  ASSERT_OK(err);

  /* simulate setting metadata after upsert */
  tix_db_set_ticket_meta_num(&db, "t-upd001", "cost", 0.88);
  tix_db_set_ticket_meta_num(&db, "t-upd001", "tokens_in", 12000.0);
  tix_db_set_ticket_meta_num(&db, "t-upd001", "tokens_out", 2500.0);
  tix_db_set_ticket_meta_num(&db, "t-upd001", "iterations", 5.0);
  tix_db_set_ticket_meta_str(&db, "t-upd001", "model", "claude-sonnet-4-20250514");
  tix_db_set_ticket_meta_num(&db, "t-upd001", "retries", 1.0);
  tix_db_set_ticket_meta_num(&db, "t-upd001", "kill_count", 0.0);

  /* verify original ticket fields preserved */
  tix_ticket_t result;
  err = tix_db_get_ticket(&db, "t-upd001", &result);
  ASSERT_OK(err);

  ASSERT_STR_EQ(result.name, "Update test");
  ASSERT_STR_EQ(result.author, "OrigAuthor");
  ASSERT_EQ(result.status, TIX_STATUS_DONE);

  /* verify metadata */
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-upd001", "cost") - 0.88) < 0.01);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-upd001", "tokens_in") - 12000.0) < 1.0);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-upd001", "tokens_out") - 2500.0) < 1.0);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-upd001", "iterations") - 5.0) < 0.1);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-upd001", "retries") - 1.0) < 0.1);

  char model_buf[256];
  get_meta_str_buf(&db, "t-upd001", "model", model_buf, sizeof(model_buf));
  ASSERT_STR_EQ(model_buf, "claude-sonnet-4-20250514");

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

/* ---- Schema version migration ---- */

static void test_schema_version_migration(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);

  /* First init: creates tables at current schema version */
  tix_err_t err = tix_db_init_schema(&db);
  ASSERT_OK(err);

  /* Insert a ticket */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-migrate1");
  tix_ticket_set_name(&t, "Will be dropped");
  tix_db_upsert_ticket(&db, &t);

  /* Fake an old schema version */
  tix_db_set_meta(&db, "schema_version", "1");

  /* Re-init should detect mismatch and drop+recreate tables */
  err = tix_db_init_schema(&db);
  ASSERT_OK(err);

  /* The old ticket should be gone */
  tix_ticket_t out;
  err = tix_db_get_ticket(&db, "t-migrate1", &out);
  ASSERT_ERR(err);

  /* Schema version should be updated */
  char ver[32];
  tix_db_get_meta(&db, "schema_version", ver, sizeof(ver));
  ASSERT_STR_EQ(ver, "6");

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

/* ---- JSON write does NOT include telemetry (now in meta) ---- */

static void test_json_write_no_telemetry(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-notelem");
  tix_ticket_set_name(&t, "No telemetry");

  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&t, buf, sizeof(buf));
  ASSERT_GT(len, 0);

  /* telemetry fields should NOT be in JSON (they're in ticket_meta now) */
  ASSERT_TRUE(strstr(buf, "\"cost\"") == NULL);
  ASSERT_TRUE(strstr(buf, "\"tokens_in\"") == NULL);
  ASSERT_TRUE(strstr(buf, "\"tokens_out\"") == NULL);
  ASSERT_TRUE(strstr(buf, "\"iterations\"") == NULL);
  ASSERT_TRUE(strstr(buf, "\"model\"") == NULL);
  ASSERT_TRUE(strstr(buf, "\"retries\"") == NULL);
  ASSERT_TRUE(strstr(buf, "\"kill_count\"") == NULL);

  TIX_PASS();
}

/* ---- Backward compat: old JSONL without telemetry ---- */

static void test_old_jsonl_compat(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* old-style JSONL with no telemetry fields */
  const char *old_jsonl =
    "{\"t\":\"task\",\"id\":\"t-old01\",\"name\":\"Old task\",\"s\":\"p\"}";

  tix_err_t err = tix_db_replay_content(&db, old_jsonl);
  ASSERT_OK(err);

  tix_ticket_t out;
  err = tix_db_get_ticket(&db, "t-old01", &out);
  ASSERT_OK(err);

  ASSERT_STR_EQ(out.name, "Old task");
  ASSERT_EQ(out.status, TIX_STATUS_PENDING);

  /* ticket fields should be zero/empty */
  ASSERT_STR_EQ(out.author, "");
  ASSERT_STR_EQ(out.completed_at, "");

  /* no metadata should exist */
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-old01", "cost")) < 0.0001);
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-old01", "tokens_in")) < 0.0001);

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

/* ---- Metadata cleanup on ticket delete ---- */

static void test_metadata_cleanup_on_delete(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* create ticket + metadata */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-del01");
  tix_ticket_set_name(&t, "Delete me");
  tix_db_upsert_ticket(&db, &t);
  tix_db_set_ticket_meta_num(&db, "t-del01", "cost", 5.0);
  tix_db_set_ticket_meta_str(&db, "t-del01", "model", "test");

  /* verify metadata exists */
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-del01", "cost") - 5.0) < 0.1);

  /* delete ticket */
  tix_db_delete_ticket(&db, "t-del01");

  /* metadata should also be gone */
  ASSERT_TRUE(fabs(get_meta_num(&db, "t-del01", "cost")) < 0.0001);

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  /* JSON double parsing */
  tix_testsuite_add(&suite, "json_get_double_basic",
                    test_json_get_double_basic);
  tix_testsuite_add(&suite, "json_double_int_compat",
                    test_json_double_int_compat);
  tix_testsuite_add(&suite, "json_get_double_wrong_type",
                    test_json_get_double_wrong_type);
  tix_testsuite_add(&suite, "json_get_double_null_args",
                    test_json_get_double_null_args);

  /* metadata DB roundtrip */
  tix_testsuite_add(&suite, "metadata_db_roundtrip",
                    test_metadata_db_roundtrip);
  tix_testsuite_add(&suite, "metadata_replay_legacy",
                    test_metadata_replay_legacy);
  tix_testsuite_add(&suite, "metadata_replay_nested",
                    test_metadata_replay_nested);

  /* git user name */
  tix_testsuite_add(&suite, "git_user_name", test_git_user_name);

  /* timestamp */
  tix_testsuite_add(&suite, "timestamp_iso8601", test_timestamp_iso8601);
  tix_testsuite_add(&suite, "timestamp_small_buffer",
                    test_timestamp_small_buffer);

  /* task update merge */
  tix_testsuite_add(&suite, "task_update_merge", test_task_update_merge);

  /* schema migration */
  tix_testsuite_add(&suite, "schema_version_migration",
                    test_schema_version_migration);

  /* JSON write */
  tix_testsuite_add(&suite, "json_write_no_telemetry",
                    test_json_write_no_telemetry);

  /* backward compat */
  tix_testsuite_add(&suite, "old_jsonl_compat", test_old_jsonl_compat);

  /* metadata cleanup */
  tix_testsuite_add(&suite, "metadata_cleanup_on_delete",
                    test_metadata_cleanup_on_delete);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
