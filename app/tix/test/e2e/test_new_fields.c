/*
 * E2E tests for session 6 additions:
 *  - tix_json_get_double / float JSON parsing
 *  - telemetry fields roundtrip (JSON -> DB -> JSON)
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

/* ---- Telemetry fields: JSON write -> parse roundtrip ---- */

static void test_telemetry_json_roundtrip(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  t.status = TIX_STATUS_DONE;
  snprintf(t.id, sizeof(t.id), "t-telem01");
  tix_ticket_set_name(&t, "Telemetry test");
  snprintf(t.author, sizeof(t.author), "Test Author");
  snprintf(t.completed_at, sizeof(t.completed_at),
           "2026-02-07T14:30:00-08:00");
  t.cost = 0.0573;
  t.tokens_in = 15000;
  t.tokens_out = 3200;
  t.iterations = 4;
  snprintf(t.model, sizeof(t.model), "claude-sonnet-4-20250514");
  t.retries = 1;
  t.kill_count = 2;

  /* write to JSON */
  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&t, buf, sizeof(buf));
  ASSERT_GT(len, 0);

  /* verify JSON contains expected fields */
  ASSERT_STR_CONTAINS(buf, "\"author\":\"Test Author\"");
  ASSERT_STR_CONTAINS(buf, "\"completed_at\":\"2026-02-07T14:30:00-08:00\"");
  ASSERT_STR_CONTAINS(buf, "\"cost\":");
  ASSERT_STR_CONTAINS(buf, "\"tokens_in\":15000");
  ASSERT_STR_CONTAINS(buf, "\"tokens_out\":3200");
  ASSERT_STR_CONTAINS(buf, "\"iterations\":4");
  ASSERT_STR_CONTAINS(buf, "\"model\":\"claude-sonnet-4-20250514\"");
  ASSERT_STR_CONTAINS(buf, "\"retries\":1");
  ASSERT_STR_CONTAINS(buf, "\"kill_count\":2");

  /* parse it back */
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line(buf, &obj);
  ASSERT_OK(err);

  const char *author = tix_json_get_str(&obj, "author");
  ASSERT_NOT_NULL(author);
  ASSERT_STR_EQ(author, "Test Author");

  const char *cat = tix_json_get_str(&obj, "completed_at");
  ASSERT_NOT_NULL(cat);
  ASSERT_STR_EQ(cat, "2026-02-07T14:30:00-08:00");

  double cost = tix_json_get_double(&obj, "cost", 0.0);
  ASSERT_TRUE(fabs(cost - 0.0573) < 0.001);

  ASSERT_EQ(tix_json_get_num(&obj, "tokens_in", 0), 15000);
  ASSERT_EQ(tix_json_get_num(&obj, "tokens_out", 0), 3200);
  ASSERT_EQ(tix_json_get_num(&obj, "iterations", 0), 4);

  const char *model = tix_json_get_str(&obj, "model");
  ASSERT_NOT_NULL(model);
  ASSERT_STR_EQ(model, "claude-sonnet-4-20250514");

  ASSERT_EQ(tix_json_get_num(&obj, "retries", 0), 1);
  ASSERT_EQ(tix_json_get_num(&obj, "kill_count", 0), 2);

  TIX_PASS();
}

static void test_telemetry_zero_skipped(TIX_TEST_ARGS()) {
  TIX_TEST();

  /* When telemetry fields are zero/empty, they should NOT appear in JSON */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-notelem");
  tix_ticket_set_name(&t, "No telemetry");

  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&t, buf, sizeof(buf));
  ASSERT_GT(len, 0);

  /* none of these should be present */
  ASSERT_TRUE(strstr(buf, "\"author\"") == NULL);
  ASSERT_TRUE(strstr(buf, "\"completed_at\"") == NULL);
  ASSERT_TRUE(strstr(buf, "\"cost\"") == NULL);
  ASSERT_TRUE(strstr(buf, "\"tokens_in\"") == NULL);
  ASSERT_TRUE(strstr(buf, "\"tokens_out\"") == NULL);
  ASSERT_TRUE(strstr(buf, "\"iterations\"") == NULL);
  ASSERT_TRUE(strstr(buf, "\"model\"") == NULL);
  ASSERT_TRUE(strstr(buf, "\"retries\"") == NULL);
  ASSERT_TRUE(strstr(buf, "\"kill_count\"") == NULL);

  TIX_PASS();
}

/* ---- Telemetry fields: DB roundtrip ---- */

static void test_telemetry_db_roundtrip(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* create ticket with all telemetry fields */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  t.status = TIX_STATUS_DONE;
  snprintf(t.id, sizeof(t.id), "t-dbrt01");
  tix_ticket_set_name(&t, "DB roundtrip");
  snprintf(t.author, sizeof(t.author), "Test User");
  snprintf(t.completed_at, sizeof(t.completed_at),
           "2026-02-07T10:00:00+00:00");
  t.cost = 1.2345;
  t.tokens_in = 50000;
  t.tokens_out = 8000;
  t.iterations = 7;
  snprintf(t.model, sizeof(t.model), "claude-opus-4-20250514");
  t.retries = 3;
  t.kill_count = 1;

  tix_err_t err = tix_db_upsert_ticket(&db, &t);
  ASSERT_OK(err);

  /* read back */
  tix_ticket_t out;
  err = tix_db_get_ticket(&db, "t-dbrt01", &out);
  ASSERT_OK(err);

  ASSERT_STR_EQ(out.author, "Test User");
  ASSERT_STR_EQ(out.completed_at, "2026-02-07T10:00:00+00:00");
  ASSERT_TRUE(fabs(out.cost - 1.2345) < 0.001);
  ASSERT_EQ(out.tokens_in, 50000);
  ASSERT_EQ(out.tokens_out, 8000);
  ASSERT_EQ(out.iterations, 7);
  ASSERT_STR_EQ(out.model, "claude-opus-4-20250514");
  ASSERT_EQ(out.retries, 3);
  ASSERT_EQ(out.kill_count, 1);

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

/* ---- replay_one_line picks up telemetry from JSONL ---- */

static void test_telemetry_replay(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* simulate a JSONL line that includes telemetry */
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
  ASSERT_TRUE(fabs(out.cost - 0.42) < 0.01);
  ASSERT_EQ(out.tokens_in, 20000);
  ASSERT_EQ(out.tokens_out, 5000);
  ASSERT_EQ(out.iterations, 3);
  ASSERT_STR_EQ(out.model, "gpt-5");
  ASSERT_EQ(out.retries, 2);
  ASSERT_EQ(out.kill_count, 0);
  ASSERT_EQ(out.status, TIX_STATUS_DONE);

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

  /* simulate task_update: read, merge, write */
  tix_ticket_t existing;
  err = tix_db_get_ticket(&db, "t-upd001", &existing);
  ASSERT_OK(err);

  /* merge telemetry fields */
  existing.cost = 0.88;
  existing.tokens_in = 12000;
  existing.tokens_out = 2500;
  existing.iterations = 5;
  snprintf(existing.model, sizeof(existing.model), "claude-sonnet-4-20250514");
  existing.retries = 1;
  existing.kill_count = 0;

  err = tix_db_upsert_ticket(&db, &existing);
  ASSERT_OK(err);

  /* verify original + merged fields persisted */
  tix_ticket_t result;
  err = tix_db_get_ticket(&db, "t-upd001", &result);
  ASSERT_OK(err);

  /* original fields preserved */
  ASSERT_STR_EQ(result.name, "Update test");
  ASSERT_STR_EQ(result.author, "OrigAuthor");
  ASSERT_EQ(result.status, TIX_STATUS_DONE);

  /* merged telemetry */
  ASSERT_TRUE(fabs(result.cost - 0.88) < 0.01);
  ASSERT_EQ(result.tokens_in, 12000);
  ASSERT_EQ(result.tokens_out, 2500);
  ASSERT_EQ(result.iterations, 5);
  ASSERT_STR_EQ(result.model, "claude-sonnet-4-20250514");
  ASSERT_EQ(result.retries, 1);
  ASSERT_EQ(result.kill_count, 0);

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
  ASSERT_STR_EQ(ver, "5");

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

/* ---- Full JSON -> DB -> JSON roundtrip with telemetry ---- */

static void test_full_telemetry_roundtrip(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* Step 1: write a ticket struct to JSON */
  tix_ticket_t original;
  tix_ticket_init(&original);
  original.type = TIX_TICKET_TASK;
  original.status = TIX_STATUS_DONE;
  snprintf(original.id, sizeof(original.id), "t-full01");
  tix_ticket_set_name(&original, "Full roundtrip");
  snprintf(original.author, sizeof(original.author), "Alice");
  snprintf(original.completed_at, sizeof(original.completed_at),
           "2026-02-07T12:00:00+00:00");
  original.cost = 2.5678;
  original.tokens_in = 100000;
  original.tokens_out = 20000;
  original.iterations = 10;
  snprintf(original.model, sizeof(original.model), "test-model-v1");
  original.retries = 2;
  original.kill_count = 3;

  char json_buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&original, json_buf, sizeof(json_buf));
  ASSERT_GT(len, 0);

  /* Step 2: replay that JSON line into DB */
  tix_err_t err = tix_db_replay_content(&db, json_buf);
  ASSERT_OK(err);

  /* Step 3: read from DB */
  tix_ticket_t from_db;
  err = tix_db_get_ticket(&db, "t-full01", &from_db);
  ASSERT_OK(err);

  /* Step 4: write DB ticket back to JSON */
  char json_buf2[TIX_MAX_LINE_LEN];
  sz len2 = tix_json_write_ticket(&from_db, json_buf2, sizeof(json_buf2));
  ASSERT_GT(len2, 0);

  /* Step 5: verify all fields survived the full trip */
  ASSERT_STR_EQ(from_db.id, "t-full01");
  ASSERT_STR_EQ(from_db.name, "Full roundtrip");
  ASSERT_STR_EQ(from_db.author, "Alice");
  ASSERT_STR_EQ(from_db.completed_at, "2026-02-07T12:00:00+00:00");
  ASSERT_TRUE(fabs(from_db.cost - 2.5678) < 0.001);
  ASSERT_EQ(from_db.tokens_in, 100000);
  ASSERT_EQ(from_db.tokens_out, 20000);
  ASSERT_EQ(from_db.iterations, 10);
  ASSERT_STR_EQ(from_db.model, "test-model-v1");
  ASSERT_EQ(from_db.retries, 2);
  ASSERT_EQ(from_db.kill_count, 3);

  /* second JSON should also contain all fields */
  ASSERT_STR_CONTAINS(json_buf2, "\"author\":\"Alice\"");
  ASSERT_STR_CONTAINS(json_buf2, "\"tokens_in\":100000");
  ASSERT_STR_CONTAINS(json_buf2, "\"kill_count\":3");

  tix_db_close(&db);
  cleanup_env(tmpdir);

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

  /* all telemetry fields should be zero/empty */
  ASSERT_STR_EQ(out.author, "");
  ASSERT_STR_EQ(out.completed_at, "");
  ASSERT_TRUE(fabs(out.cost) < 0.0001);
  ASSERT_EQ(out.tokens_in, 0);
  ASSERT_EQ(out.tokens_out, 0);
  ASSERT_EQ(out.iterations, 0);
  ASSERT_STR_EQ(out.model, "");
  ASSERT_EQ(out.retries, 0);
  ASSERT_EQ(out.kill_count, 0);

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

  /* JSON telemetry roundtrip */
  tix_testsuite_add(&suite, "telemetry_json_roundtrip",
                    test_telemetry_json_roundtrip);
  tix_testsuite_add(&suite, "telemetry_zero_skipped",
                    test_telemetry_zero_skipped);

  /* DB telemetry roundtrip */
  tix_testsuite_add(&suite, "telemetry_db_roundtrip",
                    test_telemetry_db_roundtrip);
  tix_testsuite_add(&suite, "telemetry_replay",
                    test_telemetry_replay);

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

  /* full roundtrip */
  tix_testsuite_add(&suite, "full_telemetry_roundtrip",
                    test_full_telemetry_roundtrip);

  /* backward compat */
  tix_testsuite_add(&suite, "old_jsonl_compat", test_old_jsonl_compat);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
