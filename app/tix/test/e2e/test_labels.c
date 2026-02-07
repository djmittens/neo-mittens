/*
 * E2E tests for labels and filtered query support:
 *  - tix_ticket_add_label / tix_ticket_has_label helpers
 *  - Labels in JSON write/parse roundtrip
 *  - Labels in DB upsert/get roundtrip
 *  - Labels in JSONL replay
 *  - Filtered queries by label, spec, author, priority
 *  - Label deduplication
 *  - Label overflow protection
 *  - Backward compat: old JSONL without labels
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "ticket.h"
#include "db.h"
#include "json.h"

#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

/* Helper: create isolated temp dir with git repo and tix schema */
static int setup_env(char *tmpdir, size_t tmpdir_len,
                     char *db_path, size_t db_path_len) {
  snprintf(tmpdir, tmpdir_len, "/tmp/tix_label_XXXXXX");
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

/* ---- tix_ticket_add_label / tix_ticket_has_label ---- */

static void test_add_label_basic(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_ticket_t t;
  tix_ticket_init(&t);

  ASSERT_EQ(t.label_count, 0);
  ASSERT_FALSE(tix_ticket_has_label(&t, "module:parser"));

  tix_err_t err = tix_ticket_add_label(&t, "module:parser");
  ASSERT_OK(err);
  ASSERT_EQ(t.label_count, 1);
  ASSERT_TRUE(tix_ticket_has_label(&t, "module:parser"));

  err = tix_ticket_add_label(&t, "epic:auth");
  ASSERT_OK(err);
  ASSERT_EQ(t.label_count, 2);
  ASSERT_TRUE(tix_ticket_has_label(&t, "epic:auth"));
  ASSERT_TRUE(tix_ticket_has_label(&t, "module:parser"));

  TIX_PASS();
}

static void test_add_label_dedup(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_ticket_t t;
  tix_ticket_init(&t);

  tix_ticket_add_label(&t, "foo");
  tix_ticket_add_label(&t, "bar");
  tix_ticket_add_label(&t, "foo");  /* duplicate */

  ASSERT_EQ(t.label_count, 2);
  ASSERT_TRUE(tix_ticket_has_label(&t, "foo"));
  ASSERT_TRUE(tix_ticket_has_label(&t, "bar"));

  TIX_PASS();
}

static void test_add_label_overflow(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_ticket_t t;
  tix_ticket_init(&t);

  /* fill up to max */
  for (u32 i = 0; i < TIX_MAX_LABELS; i++) {
    char label[32];
    snprintf(label, sizeof(label), "label-%u", i);
    tix_err_t err = tix_ticket_add_label(&t, label);
    ASSERT_OK(err);
  }
  ASSERT_EQ(t.label_count, TIX_MAX_LABELS);

  /* one more should fail */
  tix_err_t err = tix_ticket_add_label(&t, "one-too-many");
  ASSERT_ERR(err);
  ASSERT_EQ(t.label_count, TIX_MAX_LABELS);

  TIX_PASS();
}

static void test_add_label_null(TIX_TEST_ARGS()) {
  TIX_TEST();

  ASSERT_ERR(tix_ticket_add_label(NULL, "x"));

  tix_ticket_t t;
  tix_ticket_init(&t);
  ASSERT_ERR(tix_ticket_add_label(&t, NULL));
  ASSERT_ERR(tix_ticket_add_label(&t, ""));

  ASSERT_FALSE(tix_ticket_has_label(NULL, "x"));
  ASSERT_FALSE(tix_ticket_has_label(&t, NULL));

  TIX_PASS();
}

/* ---- JSON roundtrip ---- */

static void test_labels_json_roundtrip(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-label01");
  tix_ticket_set_name(&t, "Labels test");
  tix_ticket_add_label(&t, "module:parser");
  tix_ticket_add_label(&t, "epic:auth");
  tix_ticket_add_label(&t, "blocked");

  /* write to JSON */
  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&t, buf, sizeof(buf));
  ASSERT_GT(len, 0);

  /* verify JSON contains labels array */
  ASSERT_STR_CONTAINS(buf, "\"labels\":[");
  ASSERT_STR_CONTAINS(buf, "\"module:parser\"");
  ASSERT_STR_CONTAINS(buf, "\"epic:auth\"");
  ASSERT_STR_CONTAINS(buf, "\"blocked\"");

  /* parse it back */
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line(buf, &obj);
  ASSERT_OK(err);

  /* find the labels array field */
  int found = 0;
  for (u32 i = 0; i < obj.field_count; i++) {
    if (strcmp(obj.fields[i].key, "labels") == 0) {
      ASSERT_EQ(obj.fields[i].type, TIX_JSON_ARRAY);
      ASSERT_EQ(obj.fields[i].arr_count, 3);
      ASSERT_STR_EQ(obj.fields[i].arr_vals[0], "module:parser");
      ASSERT_STR_EQ(obj.fields[i].arr_vals[1], "epic:auth");
      ASSERT_STR_EQ(obj.fields[i].arr_vals[2], "blocked");
      found = 1;
      break;
    }
  }
  ASSERT_TRUE(found);

  TIX_PASS();
}

static void test_no_labels_json(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-nolabel");
  tix_ticket_set_name(&t, "No labels");

  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&t, buf, sizeof(buf));
  ASSERT_GT(len, 0);

  /* labels key should NOT appear when label_count == 0 */
  ASSERT_TRUE(strstr(buf, "\"labels\"") == NULL);

  TIX_PASS();
}

/* ---- DB roundtrip ---- */

static void test_labels_db_roundtrip(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-dblab01");
  tix_ticket_set_name(&t, "DB labels test");
  tix_ticket_add_label(&t, "module:db");
  tix_ticket_add_label(&t, "priority:urgent");

  tix_err_t err = tix_db_upsert_ticket(&db, &t);
  ASSERT_OK(err);

  /* read back */
  tix_ticket_t out;
  err = tix_db_get_ticket(&db, "t-dblab01", &out);
  ASSERT_OK(err);

  ASSERT_EQ(out.label_count, 2);
  /* labels are ordered alphabetically from DB */
  ASSERT_TRUE(tix_ticket_has_label(&out, "module:db"));
  ASSERT_TRUE(tix_ticket_has_label(&out, "priority:urgent"));

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

static void test_labels_db_update(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* create with initial labels */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-uplab01");
  tix_ticket_set_name(&t, "Update labels");
  tix_ticket_add_label(&t, "old-label");
  tix_db_upsert_ticket(&db, &t);

  /* update with new labels (replaces old) */
  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  snprintf(t2.id, sizeof(t2.id), "t-uplab01");
  tix_ticket_set_name(&t2, "Update labels");
  tix_ticket_add_label(&t2, "new-label-a");
  tix_ticket_add_label(&t2, "new-label-b");
  tix_db_upsert_ticket(&db, &t2);

  /* read back - should have only new labels */
  tix_ticket_t out;
  tix_err_t err = tix_db_get_ticket(&db, "t-uplab01", &out);
  ASSERT_OK(err);

  ASSERT_EQ(out.label_count, 2);
  ASSERT_TRUE(tix_ticket_has_label(&out, "new-label-a"));
  ASSERT_TRUE(tix_ticket_has_label(&out, "new-label-b"));
  ASSERT_FALSE(tix_ticket_has_label(&out, "old-label"));

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

static void test_labels_db_delete(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-dellab");
  tix_ticket_set_name(&t, "Delete labels");
  tix_ticket_add_label(&t, "will-be-deleted");
  tix_db_upsert_ticket(&db, &t);

  /* delete ticket */
  tix_err_t err = tix_db_delete_ticket(&db, "t-dellab");
  ASSERT_OK(err);

  /* ticket and its labels should be gone */
  tix_ticket_t out;
  err = tix_db_get_ticket(&db, "t-dellab", &out);
  ASSERT_ERR(err);

  /* verify labels table is also clean (check directly) */
  const char *sql =
      "SELECT COUNT(*) FROM ticket_labels WHERE ticket_id='t-dellab'";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db.handle, sql, -1, &stmt, NULL);
  ASSERT_EQ(rc, SQLITE_OK);
  ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
  ASSERT_EQ(sqlite3_column_int(stmt, 0), 0);
  sqlite3_finalize(stmt);

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

/* ---- JSONL replay ---- */

static void test_labels_replay(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  const char *jsonl =
    "{\"t\":\"task\",\"id\":\"t-rep01\",\"name\":\"Replay labels\","
    "\"s\":\"p\",\"labels\":[\"module:parser\",\"epic:auth\"]}";

  tix_err_t err = tix_db_replay_content(&db, jsonl);
  ASSERT_OK(err);

  tix_ticket_t out;
  err = tix_db_get_ticket(&db, "t-rep01", &out);
  ASSERT_OK(err);

  ASSERT_EQ(out.label_count, 2);
  ASSERT_TRUE(tix_ticket_has_label(&out, "module:parser"));
  ASSERT_TRUE(tix_ticket_has_label(&out, "epic:auth"));

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

static void test_labels_replay_update(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* first line adds with labels */
  const char *line1 =
    "{\"t\":\"task\",\"id\":\"t-rup01\",\"name\":\"Replay update\","
    "\"s\":\"p\",\"labels\":[\"old\"]}";

  /* second line updates with different labels (last-write-wins) */
  const char *line2 =
    "{\"t\":\"task\",\"id\":\"t-rup01\",\"name\":\"Replay update\","
    "\"s\":\"p\",\"labels\":[\"new-a\",\"new-b\"]}";

  char content[1024];
  snprintf(content, sizeof(content), "%s\n%s\n", line1, line2);

  tix_err_t err = tix_db_replay_content(&db, content);
  ASSERT_OK(err);

  tix_ticket_t out;
  err = tix_db_get_ticket(&db, "t-rup01", &out);
  ASSERT_OK(err);

  ASSERT_EQ(out.label_count, 2);
  ASSERT_TRUE(tix_ticket_has_label(&out, "new-a"));
  ASSERT_TRUE(tix_ticket_has_label(&out, "new-b"));
  ASSERT_FALSE(tix_ticket_has_label(&out, "old"));

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

/* ---- Backward compat: old JSONL without labels ---- */

static void test_old_jsonl_no_labels(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  const char *old_jsonl =
    "{\"t\":\"task\",\"id\":\"t-old02\",\"name\":\"No labels\",\"s\":\"p\"}";

  tix_err_t err = tix_db_replay_content(&db, old_jsonl);
  ASSERT_OK(err);

  tix_ticket_t out;
  err = tix_db_get_ticket(&db, "t-old02", &out);
  ASSERT_OK(err);

  ASSERT_EQ(out.label_count, 0);
  ASSERT_STR_EQ(out.name, "No labels");

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

/* ---- Filtered queries ---- */

static void test_filter_by_label(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* create 3 tasks with different labels */
  tix_ticket_t t1;
  tix_ticket_init(&t1);
  t1.type = TIX_TICKET_TASK;
  snprintf(t1.id, sizeof(t1.id), "t-filt01");
  tix_ticket_set_name(&t1, "Parser task");
  tix_ticket_add_label(&t1, "module:parser");
  tix_ticket_add_label(&t1, "epic:v2");
  tix_db_upsert_ticket(&db, &t1);

  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  snprintf(t2.id, sizeof(t2.id), "t-filt02");
  tix_ticket_set_name(&t2, "DB task");
  tix_ticket_add_label(&t2, "module:db");
  tix_ticket_add_label(&t2, "epic:v2");
  tix_db_upsert_ticket(&db, &t2);

  tix_ticket_t t3;
  tix_ticket_init(&t3);
  t3.type = TIX_TICKET_TASK;
  snprintf(t3.id, sizeof(t3.id), "t-filt03");
  tix_ticket_set_name(&t3, "No label task");
  tix_db_upsert_ticket(&db, &t3);

  /* filter by "module:parser" - should get 1 result */
  tix_db_filter_t filter;
  memset(&filter, 0, sizeof(filter));
  filter.type = TIX_TICKET_TASK;
  filter.status = TIX_STATUS_PENDING;
  filter.label = "module:parser";

  tix_ticket_t results[TIX_MAX_BATCH];
  u32 count = 0;
  tix_err_t err = tix_db_list_tickets_filtered(&db, &filter,
                                               results, &count,
                                               TIX_MAX_BATCH);
  ASSERT_OK(err);
  ASSERT_EQ(count, 1);
  ASSERT_STR_EQ(results[0].id, "t-filt01");

  /* filter by "epic:v2" - should get 2 results */
  filter.label = "epic:v2";
  count = 0;
  err = tix_db_list_tickets_filtered(&db, &filter,
                                     results, &count, TIX_MAX_BATCH);
  ASSERT_OK(err);
  ASSERT_EQ(count, 2);

  /* filter by non-existent label - should get 0 */
  filter.label = "nonexistent";
  count = 0;
  err = tix_db_list_tickets_filtered(&db, &filter,
                                     results, &count, TIX_MAX_BATCH);
  ASSERT_OK(err);
  ASSERT_EQ(count, 0);

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

static void test_filter_by_spec(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_ticket_t t1;
  tix_ticket_init(&t1);
  t1.type = TIX_TICKET_TASK;
  snprintf(t1.id, sizeof(t1.id), "t-spec01");
  tix_ticket_set_name(&t1, "Coverage task");
  tix_ticket_set_spec(&t1, "coverage.md");
  tix_db_upsert_ticket(&db, &t1);

  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  snprintf(t2.id, sizeof(t2.id), "t-spec02");
  tix_ticket_set_name(&t2, "Auth task");
  tix_ticket_set_spec(&t2, "auth.md");
  tix_db_upsert_ticket(&db, &t2);

  tix_db_filter_t filter;
  memset(&filter, 0, sizeof(filter));
  filter.type = TIX_TICKET_TASK;
  filter.status = TIX_STATUS_PENDING;
  filter.spec = "coverage.md";

  tix_ticket_t results[TIX_MAX_BATCH];
  u32 count = 0;
  tix_err_t err = tix_db_list_tickets_filtered(&db, &filter,
                                               results, &count,
                                               TIX_MAX_BATCH);
  ASSERT_OK(err);
  ASSERT_EQ(count, 1);
  ASSERT_STR_EQ(results[0].id, "t-spec01");

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

static void test_filter_by_author(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_ticket_t t1;
  tix_ticket_init(&t1);
  t1.type = TIX_TICKET_TASK;
  snprintf(t1.id, sizeof(t1.id), "t-auth01");
  tix_ticket_set_name(&t1, "Alice task");
  snprintf(t1.author, sizeof(t1.author), "Alice");
  tix_db_upsert_ticket(&db, &t1);

  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  snprintf(t2.id, sizeof(t2.id), "t-auth02");
  tix_ticket_set_name(&t2, "Bob task");
  snprintf(t2.author, sizeof(t2.author), "Bob");
  tix_db_upsert_ticket(&db, &t2);

  tix_db_filter_t filter;
  memset(&filter, 0, sizeof(filter));
  filter.type = TIX_TICKET_TASK;
  filter.status = TIX_STATUS_PENDING;
  filter.author = "Alice";

  tix_ticket_t results[TIX_MAX_BATCH];
  u32 count = 0;
  tix_err_t err = tix_db_list_tickets_filtered(&db, &filter,
                                               results, &count,
                                               TIX_MAX_BATCH);
  ASSERT_OK(err);
  ASSERT_EQ(count, 1);
  ASSERT_STR_EQ(results[0].id, "t-auth01");

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

static void test_filter_by_priority(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_ticket_t t1;
  tix_ticket_init(&t1);
  t1.type = TIX_TICKET_TASK;
  t1.priority = TIX_PRIORITY_HIGH;
  snprintf(t1.id, sizeof(t1.id), "t-prio01");
  tix_ticket_set_name(&t1, "High prio");
  tix_db_upsert_ticket(&db, &t1);

  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  t2.priority = TIX_PRIORITY_LOW;
  snprintf(t2.id, sizeof(t2.id), "t-prio02");
  tix_ticket_set_name(&t2, "Low prio");
  tix_db_upsert_ticket(&db, &t2);

  tix_db_filter_t filter;
  memset(&filter, 0, sizeof(filter));
  filter.type = TIX_TICKET_TASK;
  filter.status = TIX_STATUS_PENDING;
  filter.priority = TIX_PRIORITY_HIGH;
  filter.filter_priority = 1;

  tix_ticket_t results[TIX_MAX_BATCH];
  u32 count = 0;
  tix_err_t err = tix_db_list_tickets_filtered(&db, &filter,
                                               results, &count,
                                               TIX_MAX_BATCH);
  ASSERT_OK(err);
  ASSERT_EQ(count, 1);
  ASSERT_STR_EQ(results[0].id, "t-prio01");

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

static void test_filter_combined(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* t1: label=epic:v2, spec=coverage.md, priority=high */
  tix_ticket_t t1;
  tix_ticket_init(&t1);
  t1.type = TIX_TICKET_TASK;
  t1.priority = TIX_PRIORITY_HIGH;
  snprintf(t1.id, sizeof(t1.id), "t-comb01");
  tix_ticket_set_name(&t1, "Combined match");
  tix_ticket_set_spec(&t1, "coverage.md");
  tix_ticket_add_label(&t1, "epic:v2");
  tix_db_upsert_ticket(&db, &t1);

  /* t2: label=epic:v2, spec=auth.md, priority=high */
  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  t2.priority = TIX_PRIORITY_HIGH;
  snprintf(t2.id, sizeof(t2.id), "t-comb02");
  tix_ticket_set_name(&t2, "Partial match");
  tix_ticket_set_spec(&t2, "auth.md");
  tix_ticket_add_label(&t2, "epic:v2");
  tix_db_upsert_ticket(&db, &t2);

  /* t3: label=epic:v2, spec=coverage.md, priority=low */
  tix_ticket_t t3;
  tix_ticket_init(&t3);
  t3.type = TIX_TICKET_TASK;
  t3.priority = TIX_PRIORITY_LOW;
  snprintf(t3.id, sizeof(t3.id), "t-comb03");
  tix_ticket_set_name(&t3, "Wrong prio");
  tix_ticket_set_spec(&t3, "coverage.md");
  tix_ticket_add_label(&t3, "epic:v2");
  tix_db_upsert_ticket(&db, &t3);

  /* filter: label=epic:v2 AND spec=coverage.md AND priority=high */
  tix_db_filter_t filter;
  memset(&filter, 0, sizeof(filter));
  filter.type = TIX_TICKET_TASK;
  filter.status = TIX_STATUS_PENDING;
  filter.label = "epic:v2";
  filter.spec = "coverage.md";
  filter.priority = TIX_PRIORITY_HIGH;
  filter.filter_priority = 1;

  tix_ticket_t results[TIX_MAX_BATCH];
  u32 count = 0;
  tix_err_t err = tix_db_list_tickets_filtered(&db, &filter,
                                               results, &count,
                                               TIX_MAX_BATCH);
  ASSERT_OK(err);
  ASSERT_EQ(count, 1);
  ASSERT_STR_EQ(results[0].id, "t-comb01");

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

static void test_filter_no_filter(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_ticket_t t1;
  tix_ticket_init(&t1);
  t1.type = TIX_TICKET_TASK;
  snprintf(t1.id, sizeof(t1.id), "t-nofl01");
  tix_ticket_set_name(&t1, "Task A");
  tix_db_upsert_ticket(&db, &t1);

  tix_ticket_t t2;
  tix_ticket_init(&t2);
  t2.type = TIX_TICKET_TASK;
  snprintf(t2.id, sizeof(t2.id), "t-nofl02");
  tix_ticket_set_name(&t2, "Task B");
  tix_db_upsert_ticket(&db, &t2);

  /* no filters = all pending tasks */
  tix_db_filter_t filter;
  memset(&filter, 0, sizeof(filter));
  filter.type = TIX_TICKET_TASK;
  filter.status = TIX_STATUS_PENDING;

  tix_ticket_t results[TIX_MAX_BATCH];
  u32 count = 0;
  tix_err_t err = tix_db_list_tickets_filtered(&db, &filter,
                                               results, &count,
                                               TIX_MAX_BATCH);
  ASSERT_OK(err);
  ASSERT_EQ(count, 2);

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

/* ---- Full JSON -> DB -> JSON roundtrip with labels ---- */

static void test_full_labels_roundtrip(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* Step 1: create ticket with labels */
  tix_ticket_t original;
  tix_ticket_init(&original);
  original.type = TIX_TICKET_TASK;
  snprintf(original.id, sizeof(original.id), "t-flr01");
  tix_ticket_set_name(&original, "Full label roundtrip");
  tix_ticket_add_label(&original, "module:parser");
  tix_ticket_add_label(&original, "spec:coverage");
  tix_ticket_add_label(&original, "epic:auth");

  /* Step 2: write to JSON */
  char json_buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&original, json_buf, sizeof(json_buf));
  ASSERT_GT(len, 0);
  ASSERT_STR_CONTAINS(json_buf, "\"labels\":");

  /* Step 3: replay into DB */
  tix_err_t err = tix_db_replay_content(&db, json_buf);
  ASSERT_OK(err);

  /* Step 4: read from DB */
  tix_ticket_t from_db;
  err = tix_db_get_ticket(&db, "t-flr01", &from_db);
  ASSERT_OK(err);
  ASSERT_EQ(from_db.label_count, 3);
  ASSERT_TRUE(tix_ticket_has_label(&from_db, "module:parser"));
  ASSERT_TRUE(tix_ticket_has_label(&from_db, "spec:coverage"));
  ASSERT_TRUE(tix_ticket_has_label(&from_db, "epic:auth"));

  /* Step 5: write back to JSON */
  char json_buf2[TIX_MAX_LINE_LEN];
  sz len2 = tix_json_write_ticket(&from_db, json_buf2, sizeof(json_buf2));
  ASSERT_GT(len2, 0);
  ASSERT_STR_CONTAINS(json_buf2, "\"labels\":");
  ASSERT_STR_CONTAINS(json_buf2, "\"module:parser\"");
  ASSERT_STR_CONTAINS(json_buf2, "\"spec:coverage\"");
  ASSERT_STR_CONTAINS(json_buf2, "\"epic:auth\"");

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

/* ---- Filtered results include labels ---- */

static void test_filtered_results_have_labels(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup_env failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-frhl01");
  tix_ticket_set_name(&t, "Has labels");
  tix_ticket_add_label(&t, "module:json");
  tix_ticket_add_label(&t, "priority:p0");
  tix_db_upsert_ticket(&db, &t);

  tix_db_filter_t filter;
  memset(&filter, 0, sizeof(filter));
  filter.type = TIX_TICKET_TASK;
  filter.status = TIX_STATUS_PENDING;
  filter.label = "module:json";

  tix_ticket_t results[TIX_MAX_BATCH];
  u32 count = 0;
  tix_err_t err = tix_db_list_tickets_filtered(&db, &filter,
                                               results, &count,
                                               TIX_MAX_BATCH);
  ASSERT_OK(err);
  ASSERT_EQ(count, 1);
  /* the returned ticket should also have its full label set loaded */
  ASSERT_EQ(results[0].label_count, 2);
  ASSERT_TRUE(tix_ticket_has_label(&results[0], "module:json"));
  ASSERT_TRUE(tix_ticket_has_label(&results[0], "priority:p0"));

  tix_db_close(&db);
  cleanup_env(tmpdir);

  TIX_PASS();
}

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  /* label helpers */
  tix_testsuite_add(&suite, "add_label_basic", test_add_label_basic);
  tix_testsuite_add(&suite, "add_label_dedup", test_add_label_dedup);
  tix_testsuite_add(&suite, "add_label_overflow", test_add_label_overflow);
  tix_testsuite_add(&suite, "add_label_null", test_add_label_null);

  /* JSON roundtrip */
  tix_testsuite_add(&suite, "labels_json_roundtrip",
                    test_labels_json_roundtrip);
  tix_testsuite_add(&suite, "no_labels_json", test_no_labels_json);

  /* DB roundtrip */
  tix_testsuite_add(&suite, "labels_db_roundtrip",
                    test_labels_db_roundtrip);
  tix_testsuite_add(&suite, "labels_db_update", test_labels_db_update);
  tix_testsuite_add(&suite, "labels_db_delete", test_labels_db_delete);

  /* JSONL replay */
  tix_testsuite_add(&suite, "labels_replay", test_labels_replay);
  tix_testsuite_add(&suite, "labels_replay_update",
                    test_labels_replay_update);
  tix_testsuite_add(&suite, "old_jsonl_no_labels",
                    test_old_jsonl_no_labels);

  /* Filtered queries */
  tix_testsuite_add(&suite, "filter_by_label", test_filter_by_label);
  tix_testsuite_add(&suite, "filter_by_spec", test_filter_by_spec);
  tix_testsuite_add(&suite, "filter_by_author", test_filter_by_author);
  tix_testsuite_add(&suite, "filter_by_priority", test_filter_by_priority);
  tix_testsuite_add(&suite, "filter_combined", test_filter_combined);
  tix_testsuite_add(&suite, "filter_no_filter", test_filter_no_filter);

  /* Full roundtrip */
  tix_testsuite_add(&suite, "full_labels_roundtrip",
                    test_full_labels_roundtrip);
  tix_testsuite_add(&suite, "filtered_results_have_labels",
                    test_filtered_results_have_labels);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
