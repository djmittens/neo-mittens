#include "cmd.h"
#include "config.h"
#include "git.h"
#include "log.h"

#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

static const char CACHE_DB_PATTERN[] = ".tix/cache.db";

/* Ensure .tix/cache.db is listed in the repo .gitignore.
 * Scans existing lines; appends only if not already present. */
static tix_err_t ensure_gitignore(const char *repo_root) {
  char gi_path[TIX_MAX_PATH_LEN];
  int n = snprintf(gi_path, sizeof(gi_path), "%s/.gitignore", repo_root);
  if (n < 0 || (sz)n >= sizeof(gi_path)) { return TIX_ERR_OVERFLOW; }

  /* scan existing .gitignore for the pattern */
  FILE *fp = fopen(gi_path, "r");
  if (fp != NULL) {
    char line[TIX_MAX_LINE_LEN];
    while (fgets(line, (int)sizeof(line), fp) != NULL) {
      /* strip trailing newline for comparison */
      sz len = strlen(line);
      while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r')) {
        line[--len] = '\0';
      }
      if (strcmp(line, CACHE_DB_PATTERN) == 0) {
        fclose(fp);
        return TIX_OK; /* already present */
      }
    }
    fclose(fp);
  }

  /* append the pattern */
  fp = fopen(gi_path, "a");
  if (fp == NULL) {
    fprintf(stderr, "warning: could not open .gitignore for writing\n");
    return TIX_ERR_IO;
  }
  fprintf(fp, "%s\n", CACHE_DB_PATTERN);
  fclose(fp);
  printf("added %s to .gitignore\n", CACHE_DB_PATTERN);
  return TIX_OK;
}

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

  /* ensure parent directory exists for plan file */
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

  /* ensure cache.db is gitignored */
  ensure_gitignore(repo_root);

  printf("tix initialized in %s\n", tix_dir);
  return TIX_OK;
}
