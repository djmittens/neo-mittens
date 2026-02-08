/*
 * E2E tests for TQL v2 features:
 *  - HAVING clause (post-aggregate filtering)
 *  - OFFSET (pagination)
 *  - DISTINCT
 *  - count_distinct aggregate
 *  - OR logic (comma-separated values: field=a,b,c)
 *  - NOT filter prefix (!field=val)
 *  - IS NULL / IS NOT NULL (empty-value filters)
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "ticket.h"
#include "db.h"
#include "tql.h"

#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

/* ---- Test helpers ---- */

static int setup_env(char *tmpdir, sz tmpdir_len,
                     char *db_path, sz db_path_len) {
  snprintf(tmpdir, tmpdir_len, "/tmp/tix_tql2_XXXXXX");
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

/* Count rows from a compiled TQL query against a db */
static int count_rows(tix_db_t *db, tql_compiled_t *c) {
  sqlite3_stmt *stmt = NULL;
  if (sqlite3_prepare_v2(db->handle, c->sql, -1, &stmt, NULL) != SQLITE_OK) {
    return -1;
  }
  for (u32 i = 0; i < c->bind_count; i++) {
    int idx = (int)(i + 1);
    if (c->binds[i].is_int) {
      sqlite3_bind_int64(stmt, idx, c->binds[i].ival);
    } else if (c->binds[i].is_double) {
      sqlite3_bind_double(stmt, idx, c->binds[i].dval);
    } else {
      sqlite3_bind_text(stmt, idx, c->binds[i].sval, -1, SQLITE_STATIC);
    }
  }
  int rows = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) { rows++; }
  sqlite3_finalize(stmt);
  return rows;
}

/* ---- Parse tests ---- */

static void test_parse_having(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse(
    "tasks | group author | count | having count>5",
    &p, err, sizeof(err)));
  ASSERT_EQ(p.has_group, 1);
  ASSERT_STR_EQ(p.group_by, "author");
  ASSERT_EQ(p.agg_count, 1);
  ASSERT_EQ(p.having_count, 1);
  ASSERT_STR_EQ(p.havings[0].column, "count");
  ASSERT_EQ(p.havings[0].op, TQL_OP_GT);
  ASSERT_STR_EQ(p.havings[0].value, "5");

  TIX_PASS();
}

static void test_parse_having_multiple(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse(
    "tasks | group author | count | sum cost | having count>=2 sum_cost<100",
    &p, err, sizeof(err)));
  ASSERT_EQ(p.having_count, 2);
  ASSERT_STR_EQ(p.havings[0].column, "count");
  ASSERT_EQ(p.havings[0].op, TQL_OP_GE);
  ASSERT_STR_EQ(p.havings[1].column, "sum_cost");
  ASSERT_EQ(p.havings[1].op, TQL_OP_LT);

  TIX_PASS();
}

static void test_parse_offset(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | limit 10 | offset 20", &p,
                       err, sizeof(err)));
  ASSERT_EQ(p.has_limit, 1);
  ASSERT_EQ(p.limit, 10);
  ASSERT_EQ(p.has_offset, 1);
  ASSERT_EQ(p.offset, 20);

  TIX_PASS();
}

static void test_parse_offset_without_limit(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | offset 5", &p, err, sizeof(err)));
  ASSERT_EQ(p.has_offset, 1);
  ASSERT_EQ(p.offset, 5);
  ASSERT_EQ(p.has_limit, 0);

  TIX_PASS();
}

static void test_parse_distinct(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | distinct | select author", &p,
                       err, sizeof(err)));
  ASSERT_EQ(p.has_distinct, 1);
  ASSERT_EQ(p.select_count, 1);
  ASSERT_STR_EQ(p.selects[0], "author");

  TIX_PASS();
}

static void test_parse_count_distinct(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse(
    "tasks | group spec | count_distinct author",
    &p, err, sizeof(err)));
  ASSERT_EQ(p.agg_count, 1);
  ASSERT_EQ(p.aggregates[0].func, TQL_AGG_COUNT_DISTINCT);
  ASSERT_STR_EQ(p.aggregates[0].field, "author");

  TIX_PASS();
}

static void test_parse_or_values(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | status=pending,done", &p,
                       err, sizeof(err)));
  ASSERT_EQ(p.filter_count, 1);
  ASSERT_EQ(p.filters[0].op, TQL_OP_IN);
  ASSERT_EQ(p.filters[0].or_count, 2);
  ASSERT_STR_EQ(p.filters[0].or_values[0], "pending");
  ASSERT_STR_EQ(p.filters[0].or_values[1], "done");

  TIX_PASS();
}

static void test_parse_or_values_ne(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | priority!=none,low", &p,
                       err, sizeof(err)));
  ASSERT_EQ(p.filter_count, 1);
  ASSERT_EQ(p.filters[0].op, TQL_OP_NOT_IN);
  ASSERT_EQ(p.filters[0].or_count, 2);

  TIX_PASS();
}

static void test_parse_not_prefix(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | !status=done", &p, err, sizeof(err)));
  ASSERT_EQ(p.filter_count, 1);
  ASSERT_EQ(p.filters[0].negated, 1);
  ASSERT_STR_EQ(p.filters[0].field, "status");
  ASSERT_EQ(p.filters[0].op, TQL_OP_EQ);
  ASSERT_STR_EQ(p.filters[0].value, "done");

  TIX_PASS();
}

static void test_parse_not_label(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | !label=blocked", &p, err, sizeof(err)));
  ASSERT_EQ(p.filter_count, 1);
  ASSERT_EQ(p.filters[0].negated, 1);
  ASSERT_STR_EQ(p.filters[0].field, "label");

  TIX_PASS();
}

static void test_parse_is_null(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  /* spec= means IS NULL */
  ASSERT_OK(tql_parse("tasks | spec=", &p, err, sizeof(err)));
  ASSERT_EQ(p.filter_count, 1);
  ASSERT_EQ(p.filters[0].op, TQL_OP_IS_NULL);
  ASSERT_STR_EQ(p.filters[0].field, "spec");

  TIX_PASS();
}

static void test_parse_is_not_null(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  /* spec!= means IS NOT NULL */
  ASSERT_OK(tql_parse("tasks | spec!=", &p, err, sizeof(err)));
  ASSERT_EQ(p.filter_count, 1);
  ASSERT_EQ(p.filters[0].op, TQL_OP_IS_NOT_NULL);
  ASSERT_STR_EQ(p.filters[0].field, "spec");

  TIX_PASS();
}

/* ---- Compile tests ---- */

static void test_compile_having(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare(
    "tasks | group author | count | having count>5",
    &c, err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "HAVING");
  ASSERT_STR_CONTAINS(c.sql, "GROUP BY t.author");
  /* count is column 2 (author=1, count=2), so HAVING 2 > ? */
  ASSERT_EQ(c.is_aggregate, 1);

  TIX_PASS();
}

static void test_compile_offset(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | limit 10 | offset 20", &c,
                          err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "LIMIT 10");
  ASSERT_STR_CONTAINS(c.sql, "OFFSET 20");

  TIX_PASS();
}

static void test_compile_offset_implicit_limit(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | offset 5", &c, err, sizeof(err)));
  /* Should add implicit LIMIT -1 before OFFSET */
  ASSERT_STR_CONTAINS(c.sql, "LIMIT -1");
  ASSERT_STR_CONTAINS(c.sql, "OFFSET 5");

  TIX_PASS();
}

static void test_compile_distinct(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | distinct | select author", &c,
                          err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "SELECT DISTINCT");
  ASSERT_STR_CONTAINS(c.sql, "t.author");

  TIX_PASS();
}

static void test_compile_count_distinct(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare(
    "tasks | group spec | count_distinct author",
    &c, err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "COUNT(DISTINCT t.author)");
  ASSERT_STR_CONTAINS(c.sql, "GROUP BY t.spec");
  /* Column name should be count_distinct_author */
  ASSERT_EQ(c.column_count, 2);
  ASSERT_STR_EQ(c.columns[0], "spec");
  ASSERT_STR_EQ(c.columns[1], "count_distinct_author");

  TIX_PASS();
}

static void test_compile_or_values(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | status=pending,done", &c,
                          err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "IN (?,?)");
  /* type bind + 2 status IN binds = 3 */
  ASSERT_EQ(c.bind_count, 3);
  /* The IN values should be translated via enum sugar */
  ASSERT_EQ(c.binds[1].is_int, 1);
  ASSERT_EQ(c.binds[1].ival, 0); /* pending=0 */
  ASSERT_EQ(c.binds[2].is_int, 1);
  ASSERT_EQ(c.binds[2].ival, 1); /* done=1 */

  TIX_PASS();
}

static void test_compile_not_prefix(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | !status=done", &c, err, sizeof(err)));
  /* !field=val should compile to field != ? */
  ASSERT_STR_CONTAINS(c.sql, "t.status != ?");

  TIX_PASS();
}

static void test_compile_not_label(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | !label=blocked", &c, err, sizeof(err)));
  /* Negated label should use NOT EXISTS subquery */
  ASSERT_STR_CONTAINS(c.sql, "NOT EXISTS");
  ASSERT_STR_CONTAINS(c.sql, "ticket_labels nl");
  ASSERT_STR_CONTAINS(c.sql, "nl.label = ?");

  TIX_PASS();
}

static void test_compile_is_null(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | spec=", &c, err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "t.spec IS NULL");
  /* IS NULL needs no bind for the value (just type bind) */
  ASSERT_EQ(c.bind_count, 1);

  TIX_PASS();
}

static void test_compile_is_not_null(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | spec!=", &c, err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "t.spec IS NOT NULL");
  ASSERT_EQ(c.bind_count, 1);

  TIX_PASS();
}

/* ---- E2E execution tests ---- */

static void test_exec_or_values(TIX_TEST_ARGS()) {
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
  make_task(&t1, "T001", "Task 1", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Task 2", TIX_STATUS_DONE,
            TIX_PRIORITY_MEDIUM, "bob");
  make_task(&t3, "T003", "Task 3", TIX_STATUS_ACCEPTED,
            TIX_PRIORITY_LOW, "alice");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));

  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("tasks | status=pending,done", &c,
                          err, sizeof(err)));

  ASSERT_EQ(count_rows(&db, &c), 2); /* T001 and T002 */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_or_authors(TIX_TEST_ARGS()) {
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
  make_task(&t1, "T001", "Task 1", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Task 2", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "bob");
  make_task(&t3, "T003", "Task 3", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "charlie");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));

  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("tasks | author=alice,charlie", &c,
                          err, sizeof(err)));

  ASSERT_EQ(count_rows(&db, &c), 2); /* alice + charlie */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_not_status(TIX_TEST_ARGS()) {
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
  make_task(&t1, "T001", "Task 1", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Task 2", TIX_STATUS_DONE,
            TIX_PRIORITY_MEDIUM, "bob");
  make_task(&t3, "T003", "Task 3", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "charlie");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));

  char err[256] = {0};
  tql_compiled_t c;
  /* !status=done -> status != done -> should get pending ones */
  ASSERT_OK(tql_prepare("tasks | !status=done", &c, err, sizeof(err)));

  ASSERT_EQ(count_rows(&db, &c), 2); /* T001 and T003 */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_not_label(TIX_TEST_ARGS()) {
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
  make_task(&t1, "T001", "Blocked", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  tix_ticket_add_label(&t1, "blocked");

  make_task(&t2, "T002", "Free", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "bob");

  make_task(&t3, "T003", "Also free", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "charlie");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));

  char err[256] = {0};
  tql_compiled_t c;
  /* !label=blocked -> tasks that do NOT have the "blocked" label */
  ASSERT_OK(tql_prepare("tasks | !label=blocked", &c, err, sizeof(err)));

  ASSERT_EQ(count_rows(&db, &c), 2); /* T002 and T003 */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_is_null(TIX_TEST_ARGS()) {
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
  make_task(&t1, "T001", "With spec", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  snprintf(t1.spec, TIX_MAX_PATH_LEN, "feature.md");

  make_task(&t2, "T002", "No spec", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "bob");
  /* t2.spec left as empty string (which DB stores as empty/null-like) */

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));

  char err[256] = {0};
  tql_compiled_t c;
  /* branch is a field that's actually NULL/empty when not set.
     Use branch= to test IS NULL. */
  ASSERT_OK(tql_prepare("tasks | branch=", &c, err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "IS NULL");

  /* Both tasks have no branch, so both should match */
  ASSERT_EQ(count_rows(&db, &c), 2);

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_is_not_null(TIX_TEST_ARGS()) {
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
  make_task(&t1, "T001", "Has spec", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  snprintf(t1.spec, TIX_MAX_PATH_LEN, "feature.md");

  make_task(&t2, "T002", "No spec", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "bob");
  /* t2.spec left empty */

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));

  char err[256] = {0};
  tql_compiled_t c;
  /* spec!= -> spec IS NOT NULL (and not empty) */
  ASSERT_OK(tql_prepare("tasks | spec!=", &c, err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "IS NOT NULL");

  /* Only t1 has spec set */
  ASSERT_EQ(count_rows(&db, &c), 1);

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_offset(TIX_TEST_ARGS()) {
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

  /* Page 1: limit 2, offset 0 */
  ASSERT_OK(tql_prepare("tasks | sort created_at asc | limit 2",
                          &c, err, sizeof(err)));
  ASSERT_EQ(count_rows(&db, &c), 2);

  /* Page 2: limit 2, offset 2 */
  ASSERT_OK(tql_prepare("tasks | sort created_at asc | limit 2 | offset 2",
                          &c, err, sizeof(err)));
  ASSERT_EQ(count_rows(&db, &c), 2);

  /* Page 3: limit 2, offset 4 */
  ASSERT_OK(tql_prepare("tasks | sort created_at asc | limit 2 | offset 4",
                          &c, err, sizeof(err)));
  ASSERT_EQ(count_rows(&db, &c), 1); /* only 1 remaining */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_distinct(TIX_TEST_ARGS()) {
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
  make_task(&t1, "T001", "Task 1", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Task 2", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "alice");
  make_task(&t3, "T003", "Task 3", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "bob");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));

  char err[256] = {0};
  tql_compiled_t c;
  /* DISTINCT select author -> should get 2 rows (alice, bob) */
  ASSERT_OK(tql_prepare("tasks | distinct | select author", &c,
                          err, sizeof(err)));

  ASSERT_EQ(count_rows(&db, &c), 2);

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_count_distinct(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  ASSERT_OK(tix_db_open(&db, db_path));
  ASSERT_OK(tix_db_init_schema(&db));

  tix_ticket_t t1, t2, t3, t4;
  make_task(&t1, "T001", "Task 1", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  snprintf(t1.spec, TIX_MAX_PATH_LEN, "spec-a.md");
  make_task(&t2, "T002", "Task 2", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "alice");
  snprintf(t2.spec, TIX_MAX_PATH_LEN, "spec-a.md");
  make_task(&t3, "T003", "Task 3", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "bob");
  snprintf(t3.spec, TIX_MAX_PATH_LEN, "spec-a.md");
  make_task(&t4, "T004", "Task 4", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "bob");
  snprintf(t4.spec, TIX_MAX_PATH_LEN, "spec-b.md");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t4));

  char err[256] = {0};
  tql_compiled_t c;
  /* count_distinct author grouped by spec */
  ASSERT_OK(tql_prepare(
    "tasks | group spec | count_distinct author",
    &c, err, sizeof(err)));

  /* spec-a.md has alice+bob (2 distinct), spec-b.md has bob (1 distinct) */
  sqlite3_stmt *stmt = NULL;
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL),
            SQLITE_OK);
  for (u32 i = 0; i < c.bind_count; i++) {
    int idx = (int)(i + 1);
    if (c.binds[i].is_int) {
      sqlite3_bind_int64(stmt, idx, c.binds[i].ival);
    } else {
      sqlite3_bind_text(stmt, idx, c.binds[i].sval, -1, SQLITE_STATIC);
    }
  }

  int rows = 0;
  int found_a = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    rows++;
    const char *spec = (const char *)sqlite3_column_text(stmt, 0);
    int cnt = sqlite3_column_int(stmt, 1);
    if (spec != NULL && strcmp(spec, "spec-a.md") == 0) {
      ASSERT_EQ(cnt, 2); /* alice + bob */
      found_a = 1;
    }
  }
  sqlite3_finalize(stmt);

  ASSERT_EQ(rows, 2);
  ASSERT_EQ(found_a, 1);

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_having(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup_env(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  ASSERT_OK(tix_db_open(&db, db_path));
  ASSERT_OK(tix_db_init_schema(&db));

  /* alice: 3 tasks, bob: 1 task, charlie: 2 tasks */
  const char *authors[] = {"alice", "alice", "alice", "bob", "charlie",
                           "charlie"};
  for (int i = 0; i < 6; i++) {
    tix_ticket_t t;
    char id[16], name[64];
    snprintf(id, sizeof(id), "T%03d", i + 1);
    snprintf(name, sizeof(name), "Task %d", i + 1);
    make_task(&t, id, name, TIX_STATUS_PENDING, TIX_PRIORITY_MEDIUM,
              authors[i]);
    t.created_at = 1700000000 + (i64)i;
    ASSERT_OK(tix_db_upsert_ticket(&db, &t));
  }

  char err[256] = {0};
  tql_compiled_t c;
  /* Having count >= 2 -> alice(3) and charlie(2), not bob(1) */
  ASSERT_OK(tql_prepare(
    "tasks | group author | count | having count>=2",
    &c, err, sizeof(err)));

  ASSERT_EQ(count_rows(&db, &c), 2); /* alice and charlie */

  /* Having count > 2 -> only alice */
  ASSERT_OK(tql_prepare(
    "tasks | group author | count | having count>2",
    &c, err, sizeof(err)));

  ASSERT_EQ(count_rows(&db, &c), 1); /* only alice */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

static void test_exec_not_in(TIX_TEST_ARGS()) {
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
  make_task(&t1, "T001", "Task 1", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Task 2", TIX_STATUS_DONE,
            TIX_PRIORITY_MEDIUM, "bob");
  make_task(&t3, "T003", "Task 3", TIX_STATUS_ACCEPTED,
            TIX_PRIORITY_LOW, "charlie");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));

  char err[256] = {0};
  tql_compiled_t c;
  /* priority!=low,none -> should get only high and medium */
  ASSERT_OK(tql_prepare("tasks | priority!=low,none", &c,
                          err, sizeof(err)));

  ASSERT_EQ(count_rows(&db, &c), 2); /* T001 (high) + T002 (medium) */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

/* ---- Meta field tests ---- */

static void test_parse_meta_filter(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | meta.cost>1.0", &p, err, sizeof(err)));
  ASSERT_EQ(p.filter_count, 1);
  ASSERT_STR_EQ(p.filters[0].field, "meta.cost");
  ASSERT_EQ(p.filters[0].op, TQL_OP_GT);
  ASSERT_STR_EQ(p.filters[0].value, "1.0");

  TIX_PASS();
}

static void test_parse_meta_select(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_pipeline_t p;

  ASSERT_OK(tql_parse("tasks | select id,name,meta.cost,meta.model",
                       &p, err, sizeof(err)));
  ASSERT_EQ(p.select_count, 4);
  ASSERT_STR_EQ(p.selects[2], "meta.cost");
  ASSERT_STR_EQ(p.selects[3], "meta.model");

  TIX_PASS();
}

static void test_compile_meta_filter(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | meta.cost>1.0", &c, err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "LEFT JOIN ticket_meta m0");
  ASSERT_STR_CONTAINS(c.sql, "m0.key = ?");
  ASSERT_STR_CONTAINS(c.sql, "m0.value_num > ?");

  TIX_PASS();
}

static void test_compile_meta_select(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | select id,meta.model", &c,
                         err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "LEFT JOIN ticket_meta m0");
  ASSERT_STR_CONTAINS(c.sql, "COALESCE(m0.value_text");
  ASSERT_EQ(c.column_count, 2);
  ASSERT_STR_EQ(c.columns[1], "meta.model");

  TIX_PASS();
}

static void test_compile_meta_sum(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | group author | sum meta.cost",
                         &c, err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "LEFT JOIN ticket_meta m0");
  ASSERT_STR_CONTAINS(c.sql, "SUM(m0.value_num)");

  TIX_PASS();
}

static void test_compile_meta_is_null(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | meta.cost=", &c, err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "m0.key IS NULL");

  ASSERT_OK(tql_prepare("tasks | meta.cost!=", &c, err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "m0.key IS NOT NULL");

  TIX_PASS();
}

static void test_compile_meta_sort(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | sort meta.cost desc", &c,
                         err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "LEFT JOIN ticket_meta m0");
  ASSERT_STR_CONTAINS(c.sql, "m0.value_num DESC");

  TIX_PASS();
}

static void test_compile_meta_two_keys(TIX_TEST_ARGS()) {
  TIX_TEST();
  char err[256] = {0};
  tql_compiled_t c;

  ASSERT_OK(tql_prepare("tasks | meta.cost>0 meta.model=gpt-4o",
                         &c, err, sizeof(err)));
  ASSERT_STR_CONTAINS(c.sql, "LEFT JOIN ticket_meta m0");
  ASSERT_STR_CONTAINS(c.sql, "LEFT JOIN ticket_meta m1");
  ASSERT_STR_CONTAINS(c.sql, "m0.value_num > ?");
  ASSERT_STR_CONTAINS(c.sql, "m1.value_text = ?");

  TIX_PASS();
}

/* E2E: filter meta.cost > threshold */
static void test_exec_meta_filter_num(TIX_TEST_ARGS()) {
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
  make_task(&t1, "T001", "Cheap", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Expensive", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "bob");
  make_task(&t3, "T003", "No cost", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "charlie");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));

  /* Set metadata */
  ASSERT_OK(tix_db_set_ticket_meta_num(&db, "T001", "cost", 0.50));
  ASSERT_OK(tix_db_set_ticket_meta_num(&db, "T002", "cost", 5.00));
  /* T003 has no cost metadata */

  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("tasks | meta.cost>1.0", &c, err, sizeof(err)));
  ASSERT_EQ(count_rows(&db, &c), 1); /* only T002 */

  ASSERT_OK(tql_prepare("tasks | meta.cost>0", &c, err, sizeof(err)));
  ASSERT_EQ(count_rows(&db, &c), 2); /* T001 + T002 */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

/* E2E: filter meta.model = string */
static void test_exec_meta_filter_str(TIX_TEST_ARGS()) {
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
  make_task(&t1, "T001", "GPT task", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Claude task", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "bob");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));

  ASSERT_OK(tix_db_set_ticket_meta_str(&db, "T001", "model", "gpt-4o"));
  ASSERT_OK(tix_db_set_ticket_meta_str(&db, "T002", "model", "claude-3"));

  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare("tasks | meta.model=gpt-4o", &c, err, sizeof(err)));
  ASSERT_EQ(count_rows(&db, &c), 1);

  TIX_PASS();
}

/* E2E: meta.cost IS NULL / IS NOT NULL */
static void test_exec_meta_is_null(TIX_TEST_ARGS()) {
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
  make_task(&t1, "T001", "Has cost", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "No cost", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "bob");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_set_ticket_meta_num(&db, "T001", "cost", 1.23));

  char err[256] = {0};
  tql_compiled_t c;

  /* meta.cost= -> IS NULL (no cost metadata) */
  ASSERT_OK(tql_prepare("tasks | meta.cost=", &c, err, sizeof(err)));
  ASSERT_EQ(count_rows(&db, &c), 1); /* only T002 */

  /* meta.cost!= -> IS NOT NULL (has cost metadata) */
  ASSERT_OK(tql_prepare("tasks | meta.cost!=", &c, err, sizeof(err)));
  ASSERT_EQ(count_rows(&db, &c), 1); /* only T001 */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

/* E2E: group by meta.model + sum meta.cost */
static void test_exec_meta_group_sum(TIX_TEST_ARGS()) {
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
  make_task(&t1, "T001", "Task 1", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Task 2", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "bob");
  make_task(&t3, "T003", "Task 3", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "charlie");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));

  ASSERT_OK(tix_db_set_ticket_meta_str(&db, "T001", "model", "gpt-4o"));
  ASSERT_OK(tix_db_set_ticket_meta_num(&db, "T001", "cost", 1.00));
  ASSERT_OK(tix_db_set_ticket_meta_str(&db, "T002", "model", "gpt-4o"));
  ASSERT_OK(tix_db_set_ticket_meta_num(&db, "T002", "cost", 2.00));
  ASSERT_OK(tix_db_set_ticket_meta_str(&db, "T003", "model", "claude-3"));
  ASSERT_OK(tix_db_set_ticket_meta_num(&db, "T003", "cost", 0.50));

  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare(
    "tasks | group meta.model | sum meta.cost | sort sum_meta.cost desc",
    &c, err, sizeof(err)));

  /* Execute and verify */
  sqlite3_stmt *stmt = NULL;
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL),
            SQLITE_OK);
  for (u32 bi = 0; bi < c.bind_count; bi++) {
    int idx = (int)(bi + 1);
    if (c.binds[bi].is_int) {
      sqlite3_bind_int64(stmt, idx, c.binds[bi].ival);
    } else if (c.binds[bi].is_double) {
      sqlite3_bind_double(stmt, idx, c.binds[bi].dval);
    } else {
      sqlite3_bind_text(stmt, idx, c.binds[bi].sval, -1, SQLITE_STATIC);
    }
  }

  int rows = 0;
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    const char *model = (const char *)sqlite3_column_text(stmt, 0);
    double total = sqlite3_column_double(stmt, 1);
    if (rows == 0) {
      /* First row: gpt-4o with sum=3.0 (sorted desc) */
      ASSERT_STR_EQ(model, "gpt-4o");
      ASSERT_TRUE(total > 2.9 && total < 3.1);
    }
    rows++;
  }
  sqlite3_finalize(stmt);
  ASSERT_EQ(rows, 2); /* gpt-4o + claude-3 */

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

/* E2E: sort by meta.cost */
static void test_exec_meta_sort(TIX_TEST_ARGS()) {
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
  make_task(&t1, "T001", "Cheap", TIX_STATUS_PENDING,
            TIX_PRIORITY_HIGH, "alice");
  make_task(&t2, "T002", "Expensive", TIX_STATUS_PENDING,
            TIX_PRIORITY_MEDIUM, "bob");
  make_task(&t3, "T003", "Mid", TIX_STATUS_PENDING,
            TIX_PRIORITY_LOW, "charlie");

  ASSERT_OK(tix_db_upsert_ticket(&db, &t1));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t2));
  ASSERT_OK(tix_db_upsert_ticket(&db, &t3));

  ASSERT_OK(tix_db_set_ticket_meta_num(&db, "T001", "cost", 0.50));
  ASSERT_OK(tix_db_set_ticket_meta_num(&db, "T002", "cost", 5.00));
  ASSERT_OK(tix_db_set_ticket_meta_num(&db, "T003", "cost", 2.00));

  char err[256] = {0};
  tql_compiled_t c;
  ASSERT_OK(tql_prepare(
    "tasks | sort meta.cost desc | select id,meta.cost",
    &c, err, sizeof(err)));

  sqlite3_stmt *stmt = NULL;
  ASSERT_EQ(sqlite3_prepare_v2(db.handle, c.sql, -1, &stmt, NULL),
            SQLITE_OK);
  for (u32 bi = 0; bi < c.bind_count; bi++) {
    int idx = (int)(bi + 1);
    if (c.binds[bi].is_int) {
      sqlite3_bind_int64(stmt, idx, c.binds[bi].ival);
    } else if (c.binds[bi].is_double) {
      sqlite3_bind_double(stmt, idx, c.binds[bi].dval);
    } else {
      sqlite3_bind_text(stmt, idx, c.binds[bi].sval, -1, SQLITE_STATIC);
    }
  }

  /* First row should be T002 (cost=5.00, highest) */
  ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
  const char *first_id = (const char *)sqlite3_column_text(stmt, 0);
  ASSERT_STR_EQ(first_id, "T002");
  sqlite3_finalize(stmt);

  tix_db_close(&db);
  cleanup_env(tmpdir);
  TIX_PASS();
}

/* ---- Test suite ---- */

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  /* Parse tests */
  tix_testsuite_add(&suite, "parse_having",
                    test_parse_having);
  tix_testsuite_add(&suite, "parse_having_multiple",
                    test_parse_having_multiple);
  tix_testsuite_add(&suite, "parse_offset",
                    test_parse_offset);
  tix_testsuite_add(&suite, "parse_offset_without_limit",
                    test_parse_offset_without_limit);
  tix_testsuite_add(&suite, "parse_distinct",
                    test_parse_distinct);
  tix_testsuite_add(&suite, "parse_count_distinct",
                    test_parse_count_distinct);
  tix_testsuite_add(&suite, "parse_or_values",
                    test_parse_or_values);
  tix_testsuite_add(&suite, "parse_or_values_ne",
                    test_parse_or_values_ne);
  tix_testsuite_add(&suite, "parse_not_prefix",
                    test_parse_not_prefix);
  tix_testsuite_add(&suite, "parse_not_label",
                    test_parse_not_label);
  tix_testsuite_add(&suite, "parse_is_null",
                    test_parse_is_null);
  tix_testsuite_add(&suite, "parse_is_not_null",
                    test_parse_is_not_null);

  /* Compile tests */
  tix_testsuite_add(&suite, "compile_having",
                    test_compile_having);
  tix_testsuite_add(&suite, "compile_offset",
                    test_compile_offset);
  tix_testsuite_add(&suite, "compile_offset_implicit_limit",
                    test_compile_offset_implicit_limit);
  tix_testsuite_add(&suite, "compile_distinct",
                    test_compile_distinct);
  tix_testsuite_add(&suite, "compile_count_distinct",
                    test_compile_count_distinct);
  tix_testsuite_add(&suite, "compile_or_values",
                    test_compile_or_values);
  tix_testsuite_add(&suite, "compile_not_prefix",
                    test_compile_not_prefix);
  tix_testsuite_add(&suite, "compile_not_label",
                    test_compile_not_label);
  tix_testsuite_add(&suite, "compile_is_null",
                    test_compile_is_null);
  tix_testsuite_add(&suite, "compile_is_not_null",
                    test_compile_is_not_null);

  /* E2E execution tests */
  tix_testsuite_add(&suite, "exec_or_values",
                    test_exec_or_values);
  tix_testsuite_add(&suite, "exec_or_authors",
                    test_exec_or_authors);
  tix_testsuite_add(&suite, "exec_not_status",
                    test_exec_not_status);
  tix_testsuite_add(&suite, "exec_not_label",
                    test_exec_not_label);
  tix_testsuite_add(&suite, "exec_is_null",
                    test_exec_is_null);
  tix_testsuite_add(&suite, "exec_is_not_null",
                    test_exec_is_not_null);
  tix_testsuite_add(&suite, "exec_offset",
                    test_exec_offset);
  tix_testsuite_add(&suite, "exec_distinct",
                    test_exec_distinct);
  tix_testsuite_add(&suite, "exec_count_distinct",
                    test_exec_count_distinct);
  tix_testsuite_add(&suite, "exec_having",
                    test_exec_having);
  tix_testsuite_add(&suite, "exec_not_in",
                    test_exec_not_in);

  /* Meta field tests */
  tix_testsuite_add(&suite, "parse_meta_filter",
                    test_parse_meta_filter);
  tix_testsuite_add(&suite, "parse_meta_select",
                    test_parse_meta_select);
  tix_testsuite_add(&suite, "compile_meta_filter",
                    test_compile_meta_filter);
  tix_testsuite_add(&suite, "compile_meta_select",
                    test_compile_meta_select);
  tix_testsuite_add(&suite, "compile_meta_sum",
                    test_compile_meta_sum);
  tix_testsuite_add(&suite, "compile_meta_is_null",
                    test_compile_meta_is_null);
  tix_testsuite_add(&suite, "compile_meta_sort",
                    test_compile_meta_sort);
  tix_testsuite_add(&suite, "compile_meta_two_keys",
                    test_compile_meta_two_keys);
  tix_testsuite_add(&suite, "exec_meta_filter_num",
                    test_exec_meta_filter_num);
  tix_testsuite_add(&suite, "exec_meta_filter_str",
                    test_exec_meta_filter_str);
  tix_testsuite_add(&suite, "exec_meta_is_null",
                    test_exec_meta_is_null);
  tix_testsuite_add(&suite, "exec_meta_group_sum",
                    test_exec_meta_group_sum);
  tix_testsuite_add(&suite, "exec_meta_sort",
                    test_exec_meta_sort);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
