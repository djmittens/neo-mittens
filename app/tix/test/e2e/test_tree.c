/*
 * E2E test: tree rendering
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "ticket.h"
#include "db.h"
#include "tree.h"

#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int setup(char *tmpdir, size_t tlen, char *dbp, size_t dlen) {
  snprintf(tmpdir, tlen, "/tmp/tix_tree_XXXXXX");
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

static void test_tree_empty(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  char buf[4096];
  tix_err_t err = tix_tree_render_all(&db, buf, sizeof(buf));
  ASSERT_OK(err);

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

static void test_tree_parent_child(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256], db_path[512];
  if (setup(tmpdir, sizeof(tmpdir), db_path, sizeof(db_path)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  tix_db_t db;
  tix_db_open(&db, db_path);
  tix_db_init_schema(&db);

  /* parent task */
  tix_ticket_t parent;
  tix_ticket_init(&parent);
  parent.type = TIX_TICKET_TASK;
  snprintf(parent.id, sizeof(parent.id), "t-parent");
  tix_ticket_set_name(&parent, "Parent task");
  tix_db_upsert_ticket(&db, &parent);

  /* child task - depends on parent (tree renders via deps) */
  tix_ticket_t child;
  tix_ticket_init(&child);
  child.type = TIX_TICKET_TASK;
  snprintf(child.id, sizeof(child.id), "t-child1");
  tix_ticket_set_name(&child, "Child task");
  tix_ticket_add_dep(&child, "t-parent");
  tix_db_upsert_ticket(&db, &child);

  char buf[4096];
  tix_err_t err = tix_tree_render(&db, "t-parent", buf, sizeof(buf));
  ASSERT_OK(err);
  ASSERT_GT(strlen(buf), 0);
  ASSERT_STR_CONTAINS(buf, "Parent task");
  ASSERT_STR_CONTAINS(buf, "Child task");

  tix_db_close(&db);
  teardown(tmpdir);
  TIX_PASS();
}

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  tix_testsuite_add(&suite, "tree_empty", test_tree_empty);
  tix_testsuite_add(&suite, "tree_parent_child", test_tree_parent_child);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
