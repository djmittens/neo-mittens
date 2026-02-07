/*
 * E2E test: git integration (rev-parse, branch, toplevel)
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "git.h"

#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int setup(char *tmpdir, size_t tlen) {
  snprintf(tmpdir, tlen, "/tmp/tix_git_XXXXXX");
  if (mkdtemp(tmpdir) == NULL) { return -1; }
  char cmd[512];
  snprintf(cmd, sizeof(cmd),
           "cd \"%s\" && git init -q && git config user.email t@t && "
           "git config user.name t && "
           "touch x && git add -A && git commit -q -m initial", tmpdir);
  if (system(cmd) != 0) { return -1; }
  return 0;
}

static void teardown(const char *d) {
  char cmd[512];
  snprintf(cmd, sizeof(cmd), "rm -rf \"%s\"", d);
  system(cmd);
}

static void test_git_toplevel(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (setup(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  /* chdir to the temp git repo */
  char original_cwd[4096];
  if (getcwd(original_cwd, sizeof(original_cwd)) == NULL) {
    TIX_FAIL_MSG("getcwd failed");
    teardown(tmpdir);
    return;
  }

  if (chdir(tmpdir) != 0) {
    TIX_FAIL_MSG("chdir failed");
    teardown(tmpdir);
    return;
  }

  char toplevel[4096];
  tix_err_t err = tix_git_toplevel(toplevel, sizeof(toplevel));
  ASSERT_OK(err);
  ASSERT_GT(strlen(toplevel), 0);

  /* restore cwd */
  chdir(original_cwd);
  teardown(tmpdir);
  TIX_PASS();
}

static void test_git_branch(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (setup(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  char original_cwd[4096];
  if (getcwd(original_cwd, sizeof(original_cwd)) == NULL) {
    TIX_FAIL_MSG("getcwd failed");
    teardown(tmpdir);
    return;
  }

  if (chdir(tmpdir) != 0) {
    TIX_FAIL_MSG("chdir failed");
    teardown(tmpdir);
    return;
  }

  char branch[256];
  tix_err_t err = tix_git_current_branch(branch, sizeof(branch));
  ASSERT_OK(err);
  /* default branch should be main or master */
  ASSERT_GT(strlen(branch), 0);

  chdir(original_cwd);
  teardown(tmpdir);
  TIX_PASS();
}

static void test_git_rev_parse(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (setup(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  char original_cwd[4096];
  if (getcwd(original_cwd, sizeof(original_cwd)) == NULL) {
    TIX_FAIL_MSG("getcwd failed");
    teardown(tmpdir);
    return;
  }

  if (chdir(tmpdir) != 0) {
    TIX_FAIL_MSG("chdir failed");
    teardown(tmpdir);
    return;
  }

  char head[64];
  tix_err_t err = tix_git_rev_parse_head(head, sizeof(head));
  ASSERT_OK(err);
  /* should be a short hash, at least 7 chars */
  ASSERT_GE(strlen(head), 7);

  chdir(original_cwd);
  teardown(tmpdir);
  TIX_PASS();
}

static void test_git_is_clean(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (setup(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("setup failed");
    return;
  }

  char original_cwd[4096];
  if (getcwd(original_cwd, sizeof(original_cwd)) == NULL) {
    TIX_FAIL_MSG("getcwd failed");
    teardown(tmpdir);
    return;
  }

  if (chdir(tmpdir) != 0) {
    TIX_FAIL_MSG("chdir failed");
    teardown(tmpdir);
    return;
  }

  int clean = 0;
  tix_err_t err = tix_git_is_clean(&clean);
  ASSERT_OK(err);
  ASSERT_EQ(clean, 1); /* fresh repo should be clean */

  chdir(original_cwd);
  teardown(tmpdir);
  TIX_PASS();
}

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  tix_testsuite_add(&suite, "git_toplevel", test_git_toplevel);
  tix_testsuite_add(&suite, "git_branch", test_git_branch);
  tix_testsuite_add(&suite, "git_rev_parse", test_git_rev_parse);
  tix_testsuite_add(&suite, "git_is_clean", test_git_is_clean);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
