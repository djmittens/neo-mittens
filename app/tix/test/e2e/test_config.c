/*
 * E2E test: config save/load roundtrip and directory creation
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "config.h"

#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int mktemp_dir(char *buf, size_t len) {
  snprintf(buf, len, "/tmp/tix_cfg_XXXXXX");
  return mkdtemp(buf) != NULL ? 0 : -1;
}

static void cleanup(const char *d) {
  char cmd[512];
  snprintf(cmd, sizeof(cmd), "rm -rf \"%s\"", d);
  system(cmd);
}

static void test_config_defaults(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_config_t cfg;
  tix_config_defaults(&cfg);

  ASSERT_STR_EQ(cfg.main_branch, "main");
  ASSERT_STR_EQ(cfg.plan_file, "ralph/plan.jsonl");
  ASSERT_EQ(cfg.color, 1);
  ASSERT_EQ(cfg.auto_rebuild, 1);

  TIX_PASS();
}

static void test_config_save_load(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (mktemp_dir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mktemp_dir failed");
    return;
  }

  char path[512];
  snprintf(path, sizeof(path), "%s/config.toml", tmpdir);

  /* save with custom values */
  tix_config_t cfg;
  tix_config_defaults(&cfg);
  snprintf(cfg.main_branch, sizeof(cfg.main_branch), "develop");
  snprintf(cfg.plan_file, sizeof(cfg.plan_file), "tasks/plan.jsonl");
  cfg.color = 0;
  cfg.auto_rebuild = 0;

  tix_err_t err = tix_config_save(&cfg, path);
  ASSERT_OK(err);

  /* load into fresh config */
  tix_config_t loaded;
  tix_config_defaults(&loaded);
  err = tix_config_load(&loaded, path);
  ASSERT_OK(err);

  ASSERT_STR_EQ(loaded.main_branch, "develop");
  ASSERT_STR_EQ(loaded.plan_file, "tasks/plan.jsonl");
  ASSERT_EQ(loaded.color, 0);
  ASSERT_EQ(loaded.auto_rebuild, 0);

  cleanup(tmpdir);
  TIX_PASS();
}

static void test_config_load_missing(TIX_TEST_ARGS()) {
  TIX_TEST();

  tix_config_t cfg;
  tix_config_defaults(&cfg);

  /* loading a non-existent file should return OK and keep defaults */
  tix_err_t err = tix_config_load(&cfg, "/tmp/nonexistent_tix_config.toml");
  ASSERT_OK(err);
  ASSERT_STR_EQ(cfg.main_branch, "main");

  TIX_PASS();
}

static void test_ensure_dir(TIX_TEST_ARGS()) {
  TIX_TEST();

  char tmpdir[256];
  if (mktemp_dir(tmpdir, sizeof(tmpdir)) != 0) {
    TIX_FAIL_MSG("mktemp_dir failed");
    return;
  }

  char subdir[512];
  snprintf(subdir, sizeof(subdir), "%s/newdir", tmpdir);

  struct stat st;
  ASSERT_TRUE(stat(subdir, &st) != 0); /* doesn't exist yet */

  tix_err_t err = tix_config_ensure_dir(subdir);
  ASSERT_OK(err);
  ASSERT_TRUE(stat(subdir, &st) == 0); /* now exists */

  /* calling again should be idempotent */
  err = tix_config_ensure_dir(subdir);
  ASSERT_OK(err);

  cleanup(tmpdir);
  TIX_PASS();
}

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  tix_testsuite_add(&suite, "config_defaults", test_config_defaults);
  tix_testsuite_add(&suite, "config_save_load", test_config_save_load);
  tix_testsuite_add(&suite, "config_load_missing", test_config_load_missing);
  tix_testsuite_add(&suite, "ensure_dir", test_ensure_dir);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
