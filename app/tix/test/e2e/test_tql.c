/*
 * E2E tests for TQL (Tix Query Language):
 *  - Pipeline parsing (source, filters, stages)
 *  - SQL compilation with enum sugar
 *  - Filter operators (=, !=, >, <, >=, <=, ~)
 *  - Aggregates (count, sum, avg, min, max)
 *  - Group by
 *  - Sort and limit
 *  - Label join handling
 *  - Raw SQL passthrough
 *  - Error cases
 *  - End-to-end execution against a real SQLite DB
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "ticket.h"
#include "db.h"
#include "tql.h"
#include "json.h"

#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

/* ---- Test helpers ---- */

static int setup_env(char *tmpdir, sz tmpdir_len,
                     char *db_path, sz db_path_len) {
  snprintf(tmpdir, tmpdir_len, "/tmp/tix_tql_XXXXXX");
  if (mkdtemp(tmpdir) == NULL) { return -1; }

  char cmd[512];
  snprintf(cmd, sizeof(cmd),
           "cd \"%s\" && git init -q && git config user.email test@test && "
           "git config user.name \"Test\" && "
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

static void make_task(tix_ticket_t *t, const char *id, const char *name,
                      tix_status_e status, tix_priority_e prio,
                      const char *author) {
  tix_ticket_init(t);
  snprintf(t->id, TIX_MAX_ID_LEN, "%s", id);
  snprintf(t->name, TIX_MAX_NAME_LEN, "%s", name);
  t->type = TIX_TICKET_TASK;
  t->status = status;
  t->priority = prio;
  if (author != NULL) {
    snprintf(t->author, TIX_MAX_NAME_LEN, "%s", author);
  }
  t->created_at = 1700000000;
}

static void make_issue(tix_ticket_t *t, const char *id, const char *name) {
  tix_ticket_init(t);
  snprintf(t->id, TIX_MAX_ID_LEN, "%s", id);
  snprintf(t->name, TIX_MAX_NAME_LEN, "%s", name);
  t->type = TIX_TICKET_ISSUE;
  t->status = TIX_STATUS_PENDING;
  t->created_at = 1700000000;
}

/* ---- Parse tests ---- */

static void test_parse_simple_source(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks", &p, err, sizeof(err)));
  ASSERT_EQ(p.source, TQL_SOURCE_TASKS);
  ASSERT_EQ(p.has_source, 1);
  ASSERT_EQ(p.filter_count, 0);

  ASSERT_OK(tql_parse("issues", &p, err, sizeof(err)));
  ASSERT_EQ(p.source, TQL_SOURCE_ISSUES);

  ASSERT_OK(tql_parse("notes", &p, err, sizeof(err)));
  ASSERT_EQ(p.source, TQL_SOURCE_NOTES);

  ASSERT_OK(tql_parse("tickets", &p, err, sizeof(err)));
  ASSERT_EQ(p.source, TQL_SOURCE_TICKETS);

  TIX_PASS();
}

static void test_parse_source_with_inline_filters(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks status=done", &p, err, sizeof(err)));
  ASSERT_EQ(p.source, TQL_SOURCE_TASKS);
  ASSERT_EQ(p.filter_count, 1);
  ASSERT_STR_EQ(p.filters[0].field, "status");
  ASSERT_EQ(p.filters[0].op, TQL_OP_EQ);
  ASSERT_STR_EQ(p.filters[0].value, "done");

  TIX_PASS();
}

static void test_parse_piped_filters(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | status=pending author=alice", &p,
                       err, sizeof(err)));
  ASSERT_EQ(p.filter_count, 2);
  ASSERT_STR_EQ(p.filters[0].field, "status");
  ASSERT_STR_EQ(p.filters[0].value, "pending");
  ASSERT_STR_EQ(p.filters[1].field, "author");
  ASSERT_STR_EQ(p.filters[1].value, "alice");

  TIX_PASS();
}

static void test_parse_all_operators(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tickets | priority!=none created_at>1700000000 "
                       "updated_at<1800000000 resolved_at>=5 compacted_at<=2 name~auth*",
                       &p, err, sizeof(err)));
  ASSERT_EQ(p.filter_count, 6);
  ASSERT_EQ(p.filters[0].op, TQL_OP_NE);
  ASSERT_EQ(p.filters[1].op, TQL_OP_GT);
  ASSERT_EQ(p.filters[2].op, TQL_OP_LT);
  ASSERT_EQ(p.filters[3].op, TQL_OP_GE);
  ASSERT_EQ(p.filters[4].op, TQL_OP_LE);
  ASSERT_EQ(p.filters[5].op, TQL_OP_LIKE);

  TIX_PASS();
}

static void test_parse_select(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | select id,name,author", &p,
                       err, sizeof(err)));
  ASSERT_EQ(p.select_count, 3);
  ASSERT_STR_EQ(p.selects[0], "id");
  ASSERT_STR_EQ(p.selects[1], "name");
  ASSERT_STR_EQ(p.selects[2], "author");

  TIX_PASS();
}

static void test_parse_group_count(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | group author | count", &p,
                       err, sizeof(err)));
  ASSERT_EQ(p.has_group, 1);
  ASSERT_STR_EQ(p.group_by, "author");
  ASSERT_EQ(p.agg_count, 1);
  ASSERT_EQ(p.aggregates[0].func, TQL_AGG_COUNT);

  TIX_PASS();
}

static void test_parse_aggregates(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | group author | count | sum created_at | avg created_at",
                       &p, err, sizeof(err)));
  ASSERT_EQ(p.agg_count, 3);
  ASSERT_EQ(p.aggregates[0].func, TQL_AGG_COUNT);
  ASSERT_EQ(p.aggregates[1].func, TQL_AGG_SUM);
  ASSERT_STR_EQ(p.aggregates[1].field, "created_at");
  ASSERT_EQ(p.aggregates[2].func, TQL_AGG_AVG);

  TIX_PASS();
}

static void test_parse_sort(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | sort created_at desc", &p,
                       err, sizeof(err)));
  ASSERT_EQ(p.sort_count, 1);
  ASSERT_STR_EQ(p.sorts[0].field, "created_at");
  ASSERT_EQ(p.sorts[0].dir, TQL_SORT_DESC);

  TIX_PASS();
}

static void test_parse_limit(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | limit 10", &p, err, sizeof(err)));
  ASSERT_EQ(p.has_limit, 1);
  ASSERT_EQ(p.limit, 10);

  TIX_PASS();
}

static void test_parse_full_pipeline(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse(
    "tasks | status=pending priority=high | group author | count "
    "| sort count desc | limit 5",
    &p, err, sizeof(err)));

  ASSERT_EQ(p.source, TQL_SOURCE_TASKS);
  ASSERT_EQ(p.filter_count, 2);
  ASSERT_EQ(p.has_group, 1);
  ASSERT_STR_EQ(p.group_by, "author");
  ASSERT_EQ(p.agg_count, 1);
  ASSERT_EQ(p.sort_count, 1);
  ASSERT_EQ(p.has_limit, 1);
  ASSERT_EQ(p.limit, 5);

  TIX_PASS();
}

/* ---- Parse error tests ---- */

static void test_parse_error_no_source(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  tix_err_t rc = tql_parse("| count", &p, err, sizeof(err));
  ASSERT_ERR(rc);

  TIX_PASS();
}

static void test_parse_error_bad_source(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  tix_err_t rc = tql_parse("foobar", &p, err, sizeof(err));
  ASSERT_ERR(rc);
  ASSERT_STR_CONTAINS(err, "unknown source");

  TIX_PASS();
}

static void test_parse_error_bad_field(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  tix_err_t rc = tql_parse("tasks | nonexistent=foo", &p,
                            err, sizeof(err));
  ASSERT_ERR(rc);
  ASSERT_STR_CONTAINS(err, "unknown field");

  TIX_PASS();
}

/* ---- Compile tests ---- */

static void test_compile_basic_tasks(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks", &c, err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "FROM tickets t");
  ASSERT_STR_CONTAINS(c.sql, "WHERE t.type=?");
  ASSERT_EQ(c.bind_count, 1);
  ASSERT_EQ(c.binds[0].ival, 0); /* TIX_TICKET_TASK */

  TIX_PASS();
}

static void test_compile_tickets_no_type_filter(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tickets", &c, err, sizeof(err)));
  /* "tickets" source should NOT have a type filter */
  ASSERT_EQ(c.bind_count, 0);

  TIX_PASS();
}

static void test_compile_enum_sugar(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | status=done", &c, err, sizeof(err)));
  /* status=done should translate to integer 1 */
  ASSERT_EQ(c.bind_count, 2); /* type + status */
  ASSERT_EQ(c.binds[1].is_int, 1);
  ASSERT_EQ(c.binds[1].ival, 1); /* TIX_STATUS_DONE */

  TIX_PASS();
}

static void test_compile_priority_enum(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | priority=high", &c, err, sizeof(err)));
  ASSERT_EQ(c.binds[1].is_int, 1);
  ASSERT_EQ(c.binds[1].ival, 3); /* TIX_PRIORITY_HIGH */

  TIX_PASS();
}

static void test_compile_label_join(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | label=blocked", &c, err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "INNER JOIN ticket_labels tl");
  ASSERT_STR_CONTAINS(c.sql, "tl.label");

  TIX_PASS();
}

static void test_compile_like_pattern(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | name~auth*", &c, err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "LIKE ?");
  /* * should be converted to % */
  ASSERT_STR_EQ(c.binds[1].sval, "auth%");

  TIX_PASS();
}

static void test_compile_select(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | select id,name,author", &c,
                         err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "t.id");
  ASSERT_STR_CONTAINS(c.sql, "t.name");
  ASSERT_STR_CONTAINS(c.sql, "t.author");
  ASSERT_EQ(c.column_count, 3);

  TIX_PASS();
}

static void test_compile_group_count(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | group author | count", &c,
                         err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "t.author");
  ASSERT_STR_CONTAINS(c.sql, "COUNT(*)");
  ASSERT_STR_CONTAINS(c.sql, "GROUP BY t.author");
  ASSERT_EQ(c.is_aggregate, 1);
  ASSERT_EQ(c.column_count, 2); /* author, count */

  TIX_PASS();
}

static void test_compile_sum(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | group author | sum created_at", &c,
                         err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "SUM(t.created_at)");
  ASSERT_STR_CONTAINS(c.sql, "GROUP BY t.author");

  TIX_PASS();
}

static void test_compile_sort_limit(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | sort created_at desc | limit 5", &c,
                         err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "ORDER BY t.created_at DESC");
  ASSERT_STR_CONTAINS(c.sql, "LIMIT 5");

  TIX_PASS();
}

/* ---- E2E execution tests ---- */

static void test_exec_basic_query(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  ASSERT_OK(tix_db_open(&db, db_path));
  ASSERT_OK(tix_db_init_schema(&db));

  /* Insert test data */
  tix_ticket_t t1, t2, t3;
  make_task(&t1, "T001", "Build parser", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Write tests", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "bob");
  make_task(&t3, "T003", "Deploy", TIX_STATUS_DONE,
            TIX_PRIORITY_LOW, "alice");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));

  /* Compile and execute a simple query */
  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("tasks | status=pending", &c, err, sizeof(err)));

  /* Just verify the SQL compiled successfully and can be prepared */
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL);
  ASSERT_EQ(rc, SQLITE_OK);

  /* Bind and count results */
  for (u32 i = 0; i < c.bind_count; i++) {
    if (c.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), c.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), c.binds[i].sval, -1,
                        SQLITE_STATIC);
    }
  }

  int row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 2); /* T001 and T002 are pending */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_filter_by_author(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  ASSERT_OK(tix_db_open(&db, db_path));
  ASSERT_OK(tix_db_init_schema(&db));

  tix_ticket_t t1, t2, t3;
  make_task(&t1, "T001", "Parser", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Tests", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "bob");
  make_task(&t3, "T003", "Docs", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "alice");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));

  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("tasks | author=alice", &c, err, sizeof(err)));

  sqlite3_stmt *stmt = NULL;
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL), SQLITE_OK);
  for (u32 i = 0; i < c.bind_count; i++) {
    if (c.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), c.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), c.binds[i].sval, -1,
                        SQLITE_STATIC);
    }
  }

  int row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 2); /* alice has T001 and T003 */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_group_by_author(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  ASSERT_OK(tix_db_open(&db, db_path));
  ASSERT_OK(tix_db_init_schema(&db));

  tix_ticket_t t1, t2, t3;
  make_task(&t1, "T001", "Parser", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Tests", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "bob");
  make_task(&t3, "T003", "Docs", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "alice");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));

  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("tasks | group author | count",
                         &c, err, sizeof(err)));

  sqlite3_stmt *stmt = NULL;
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL), SQLITE_OK);
  for (u32 i = 0; i < c.bind_count; i++) {
    if (c.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), c.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), c.binds[i].sval, -1,
                        SQLITE_STATIC);
    }
  }

  int row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 2); /* alice and bob */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_label_filter(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  ASSERT_OK(tix_db_open(&db, db_path));
  ASSERT_OK(tix_db_init_schema(&db));

  tix_ticket_t t1, t2;
  make_task(&t1, "T001", "Blocked task", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  tix_ticket_add_label(&t1, "blocked");
  tix_ticket_add_label(&t1, "module:parser");

  make_task(&t2, "T002", "Free task", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "bob");
  tix_ticket_add_label(&t2, "module:parser");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));

  /* Query for blocked tasks */
  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("tasks | label=blocked", &c, err, sizeof(err)));

  sqlite3_stmt *stmt = NULL;
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL), SQLITE_OK);
  for (u32 i = 0; i < c.bind_count; i++) {
    if (c.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), c.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), c.binds[i].sval, -1,
                        SQLITE_STATIC);
    }
  }

  int row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 1); /* only T001 is blocked */

  /* Query for module:parser - should get both */
  ASSERT_OK(tql_prepare("tasks | label=module:parser", &c,
                         err, sizeof(err)));
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL), SQLITE_OK);
  for (u32 i = 0; i < c.bind_count; i++) {
    if (c.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), c.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), c.binds[i].sval, -1,
                        SQLITE_STATIC);
    }
  }

  row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 2);

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_limit(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  ASSERT_OK(tix_db_open(&db, db_path));
  ASSERT_OK(tix_db_init_schema(&db));

  /* Insert 5 tasks */
  for (int i = 0; i < 5; i++) {
    tix_ticket_t t;
    char id[16], name[64];
    snprintf(id, sizeof(id), "T%03d", i + 1);
    snprintf(name, sizeof(name), "Task %d", i + 1);
    make_task(&t, id, name, TIX_STATUS_PENDING, TIX_PRIORITY_MEDIUM, "alice");
    t.created_at = 1700000000 + (i64)i;
    ASSERT_OK(tix_db_upsert_ticket(&db, &t));
  }

  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("tasks | limit 3", &c, err, sizeof(err)));

  sqlite3_stmt *stmt = NULL;
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL), SQLITE_OK);
  for (u32 i = 0; i < c.bind_count; i++) {
    if (c.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), c.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), c.binds[i].sval, -1,
                        SQLITE_STATIC);
    }
  }

  int row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 3);

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_issues_source(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  ASSERT_OK(tix_db_open(&db, db_path));
  ASSERT_OK(tix_db_init_schema(&db));

  tix_ticket_t t1, i1;
  make_task(&t1, "T001", "A task", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_issue(&i1, "I001", "A bug");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &i1));

  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("issues", &c, err, sizeof(err)));

  sqlite3_stmt *stmt = NULL;
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL), SQLITE_OK);
  for (u32 i = 0; i < c.bind_count; i++) {
    if (c.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), c.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), c.binds[i].sval, -1,
                        SQLITE_STATIC);
    }
  }

  int row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 1); /* only the issue */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_tickets_all(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  ASSERT_OK(tix_db_open(&db, db_path));
  ASSERT_OK(tix_db_init_schema(&db));

  tix_ticket_t t1, i1;
  make_task(&t1, "T001", "A task", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_issue(&i1, "I001", "A bug");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &i1));

  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("tickets", &c, err, sizeof(err)));

  sqlite3_stmt *stmt = NULL;
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL), SQLITE_OK);

  int row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 2); /* both task and issue */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_ne_operator(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  ASSERT_OK(tix_db_open(&db, db_path));
  ASSERT_OK(tix_db_init_schema(&db));

  tix_ticket_t t1, t2;
  make_task(&t1, "T001", "High", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Low", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "bob");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));

  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("tasks | priority!=high", &c, err, sizeof(err)));

  sqlite3_stmt *stmt = NULL;
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL), SQLITE_OK);
  for (u32 i = 0; i < c.bind_count; i++) {
    if (c.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), c.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), c.binds[i].sval, -1,
                        SQLITE_STATIC);
    }
  }

  int row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 1); /* only T002 (low priority) */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_like_filter(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  ASSERT_OK(tix_db_open(&db, db_path));
  ASSERT_OK(tix_db_init_schema(&db));

  tix_ticket_t t1, t2;
  make_task(&t1, "T001", "Build parser", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Deploy service", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "bob");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));

  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("tasks | name~Build*", &c, err, sizeof(err)));

  sqlite3_stmt *stmt = NULL;
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL), SQLITE_OK);
  for (u32 i = 0; i < c.bind_count; i++) {
    if (c.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), c.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), c.binds[i].sval, -1,
                        SQLITE_STATIC);
    }
  }

  int row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 1); /* only "Build parser" */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_raw_sql(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  ASSERT_OK(tix_db_open(&db, db_path));
  ASSERT_OK(tix_db_init_schema(&db));

  tix_ticket_t t1, t2;
  make_task(&t1, "T001", "Parser", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Tests", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "alice");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));

  /* store cost in ticket_meta */
  tix_db_set_ticket_meta_num(&db, "T001", "cost", 1.50);
  tix_db_set_ticket_meta_num(&db, "T002", "cost", 2.50);

  /* Verify raw SQL works by preparing it directly */
  const char *sql = "SELECT t.author, SUM(m.value_num) as total "
                    "FROM tickets t "
                    "LEFT JOIN ticket_meta m ON m.ticket_id=t.id AND m.key='cost' "
                    "GROUP BY t.author";
  sqlite3_stmt *stmt = NULL;
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, sql, -1, &stmt, NULL), SQLITE_OK);

  int row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    row_count++;
    const char *author = (const char *)sqlite3_column_text(stmt, 0);
    double total = sqlite3_column_double(stmt, 1);
    ASSERT_STR_EQ(author, "alice");
    ASSERT_TRUE(total > 3.9 && total < 4.1); /* 1.50 + 2.50 = 4.00 */
  }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 1);

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_group_by_label(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  ASSERT_OK(tix_db_open(&db, db_path));
  ASSERT_OK(tix_db_init_schema(&db));

  tix_ticket_t t1, t2, t3;
  make_task(&t1, "T001", "Parser", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  tix_ticket_add_label(&t1, "module:parser");

  make_task(&t2, "T002", "Lexer", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "bob");
  tix_ticket_add_label(&t2, "module:parser");

  make_task(&t3, "T003", "API", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "alice");
  tix_ticket_add_label(&t3, "module:api");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));

  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("tasks | group label | count", &c,
                         err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "ticket_labels");
  ASSERT_STR_CONTAINS(c.sql, "GROUP BY tl.label");

  sqlite3_stmt *stmt = NULL;
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL), SQLITE_OK);
  for (u32 i = 0; i < c.bind_count; i++) {
    if (c.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), c.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), c.binds[i].sval, -1,
                        SQLITE_STATIC);
    }
  }

  int row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 2); /* module:parser and module:api */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_multiple_filters(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  ASSERT_OK(tix_db_open(&db, db_path));
  ASSERT_OK(tix_db_init_schema(&db));

  tix_ticket_t t1, t2, t3;
  make_task(&t1, "T001", "Parser", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Tests", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "bob");
  make_task(&t3, "T003", "Deploy", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "alice");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));

  /* Filter by both author and priority */
  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("tasks | author=alice priority=high", &c,
                         err, sizeof(err)));

  sqlite3_stmt *stmt = NULL;
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL), SQLITE_OK);
  for (u32 i = 0; i < c.bind_count; i++) {
    if (c.binds[i].is_int) {
      sqlite3_bind_int64(stmt, (int)(i + 1), c.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, (int)(i + 1), c.binds[i].sval, -1,
                        SQLITE_STATIC);
    }
  }

  int row_count = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { row_count++; }
  sqlite3_finalize(stmt);

  ASSERT_EQ(row_count, 1); /* only T001: alice + high */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

/* ---- Test suite ---- */

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  /* Parse tests */
  tix_testsuite_add(&suite, "parse_simple_source",
                    test_parse_simple_source);
  tix_testsuite_add(&suite, "parse_source_with_inline_filters",
                    test_parse_source_with_inline_filters);
  tix_testsuite_add(&suite, "parse_piped_filters",
                    test_parse_piped_filters);
  tix_testsuite_add(&suite, "parse_all_operators",
                    test_parse_all_operators);
  tix_testsuite_add(&suite, "parse_select",
                    test_parse_select);
  tix_testsuite_add(&suite, "parse_group_count",
                    test_parse_group_count);
  tix_testsuite_add(&suite, "parse_aggregates",
                    test_parse_aggregates);
  tix_testsuite_add(&suite, "parse_sort",
                    test_parse_sort);
  tix_testsuite_add(&suite, "parse_limit",
                    test_parse_limit);
  tix_testsuite_add(&suite, "parse_full_pipeline",
                    test_parse_full_pipeline);

  /* Parse error tests */
  tix_testsuite_add(&suite, "parse_error_no_source",
                    test_parse_error_no_source);
  tix_testsuite_add(&suite, "parse_error_bad_source",
                    test_parse_error_bad_source);
  tix_testsuite_add(&suite, "parse_error_bad_field",
                    test_parse_error_bad_field);

  /* Compile tests */
  tix_testsuite_add(&suite, "compile_basic_tasks",
                    test_compile_basic_tasks);
  tix_testsuite_add(&suite, "compile_tickets_no_type_filter",
                    test_compile_tickets_no_type_filter);
  tix_testsuite_add(&suite, "compile_enum_sugar",
                    test_compile_enum_sugar);
  tix_testsuite_add(&suite, "compile_priority_enum",
                    test_compile_priority_enum);
  tix_testsuite_add(&suite, "compile_label_join",
                    test_compile_label_join);
  tix_testsuite_add(&suite, "compile_like_pattern",
                    test_compile_like_pattern);
  tix_testsuite_add(&suite, "compile_select",
                    test_compile_select);
  tix_testsuite_add(&suite, "compile_group_count",
                    test_compile_group_count);
  tix_testsuite_add(&suite, "compile_sum",
                    test_compile_sum);
  tix_testsuite_add(&suite, "compile_sort_limit",
                    test_compile_sort_limit);

  /* E2E execution tests */
  tix_testsuite_add(&suite, "exec_basic_query",
                    test_exec_basic_query);
  tix_testsuite_add(&suite, "exec_filter_by_author",
                    test_exec_filter_by_author);
  tix_testsuite_add(&suite, "exec_group_by_author",
                    test_exec_group_by_author);
  tix_testsuite_add(&suite, "exec_label_filter",
                    test_exec_label_filter);
  tix_testsuite_add(&suite, "exec_limit",
                    test_exec_limit);
  tix_testsuite_add(&suite, "exec_issues_source",
                    test_exec_issues_source);
  tix_testsuite_add(&suite, "exec_tickets_all",
                    test_exec_tickets_all);
  tix_testsuite_add(&suite, "exec_ne_operator",
                    test_exec_ne_operator);
  tix_testsuite_add(&suite, "exec_like_filter",
                    test_exec_like_filter);
  tix_testsuite_add(&suite, "exec_raw_sql",
                    test_exec_raw_sql);
  tix_testsuite_add(&suite, "exec_group_by_label",
                    test_exec_group_by_label);
  tix_testsuite_add(&suite, "exec_multiple_filters",
                    test_exec_multiple_filters);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
