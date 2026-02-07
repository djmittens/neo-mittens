#include "cmd.h"
#include "config.h"
#include "git.h"
#include "log.h"

#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

tix_err_t tix_cmd_init(int argc, char **argv) {
  TIX_UNUSED(argc);
  TIX_UNUSED(argv);

  char repo_root[TIX_MAX_PATH_LEN];
  tix_err_t err = tix_git_toplevel(repo_root, sizeof(repo_root));
  if (err != TIX_OK) {
    fprintf(stderr, "error: not in a git repository\n");
    return err;
  }

  char tix_dir[TIX_MAX_PATH_LEN];
  int n = snprintf(tix_dir, sizeof(tix_dir), "%s/.tix", repo_root);
  if (n < 0 || (sz)n >= sizeof(tix_dir)) { return TIX_ERR_OVERFLOW; }

  err = tix_config_ensure_dir(tix_dir);
  if (err != TIX_OK) {
    fprintf(stderr, "error: could not create .tix/ directory\n");
    return err;
  }

  char config_path[TIX_MAX_PATH_LEN];
  n = snprintf(config_path, sizeof(config_path), "%s/config.toml", tix_dir);
  if (n < 0 || (sz)n >= sizeof(config_path)) { return TIX_ERR_OVERFLOW; }

  struct stat st;
  tix_config_t cfg;
  tix_config_defaults(&cfg);

  /* detect legacy ralph/plan.jsonl and use it if present */
  char legacy_path[TIX_MAX_PATH_LEN];
  n = snprintf(legacy_path, sizeof(legacy_path),
               "%s/ralph/plan.jsonl", repo_root);
  if (n < 0 || (sz)n >= sizeof(legacy_path)) { return TIX_ERR_OVERFLOW; }

  if (stat(legacy_path, &st) == 0) {
    snprintf(cfg.plan_file, sizeof(cfg.plan_file), "ralph/plan.jsonl");
    printf("found legacy %s, using it\n", legacy_path);
  }

  if (stat(config_path, &st) != 0) {
    err = tix_config_save(&cfg, config_path);
    if (err != TIX_OK) {
      fprintf(stderr, "error: could not write config.toml\n");
      return err;
    }
    printf("created %s\n", config_path);
  }

  /* ensure plan.jsonl exists at configured location */
  char plan_path[TIX_MAX_PATH_LEN];
  n = snprintf(plan_path, sizeof(plan_path),
               "%s/%s", repo_root, cfg.plan_file);
  if (n < 0 || (sz)n >= sizeof(plan_path)) { return TIX_ERR_OVERFLOW; }

  /* ensure parent directory exists (e.g. .tix/ or ralph/) */
  char plan_dir[TIX_MAX_PATH_LEN];
  snprintf(plan_dir, sizeof(plan_dir), "%s", plan_path);
  char *last_slash = strrchr(plan_dir, '/');
  if (last_slash != NULL) {
    *last_slash = '\0';
    tix_config_ensure_dir(plan_dir);
  }

  if (stat(plan_path, &st) != 0) {
    FILE *fp = fopen(plan_path, "w");
    if (fp != NULL) {
      fclose(fp);
      printf("created %s\n", plan_path);
    }
  }

  /* init sqlite cache */
  char db_path[TIX_MAX_PATH_LEN];
  n = snprintf(db_path, sizeof(db_path), "%s/cache.db", tix_dir);
  if (n < 0 || (sz)n >= sizeof(db_path)) { return TIX_ERR_OVERFLOW; }

  tix_db_t db;
  err = tix_db_open(&db, db_path);
  if (err != TIX_OK) { return err; }

  err = tix_db_init_schema(&db);
  tix_db_close(&db);
  if (err != TIX_OK) { return err; }

  printf("tix initialized in %s\n", tix_dir);
  return TIX_OK;
}
