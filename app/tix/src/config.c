#include "config.h"
#include "log.h"

#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

void tix_config_defaults(tix_config_t *cfg) {
  if (cfg == NULL) { return; }
  memset(cfg, 0, sizeof(*cfg));
  snprintf(cfg->main_branch, sizeof(cfg->main_branch), "main");
  cfg->color = 1;
  cfg->auto_rebuild = 1;
  snprintf(cfg->plan_file, sizeof(cfg->plan_file), ".tix/plan.jsonl");
}

static void trim_trailing(char *s) {
  sz len = strlen(s);
  while (len > 0 && (s[len - 1] == ' ' || s[len - 1] == '\t' ||
         s[len - 1] == '\n' || s[len - 1] == '\r' || s[len - 1] == '"')) {
    s[--len] = '\0';
  }
}

static const char *skip_prefix(const char *line, const char *prefix) {
  sz plen = strlen(prefix);
  if (strncmp(line, prefix, plen) == 0) { return line + plen; }
  return NULL;
}

tix_err_t tix_config_load(tix_config_t *cfg, const char *path) {
  if (cfg == NULL || path == NULL) { return TIX_ERR_INVALID_ARG; }

  FILE *fp = fopen(path, "r");
  if (fp == NULL) {
    TIX_DEBUG("config file not found: %s, using defaults", path);
    return TIX_OK;
  }

  char section[64] = {0};
  char line[512];

  while (fgets(line, (int)sizeof(line), fp) != NULL) {
    /* skip comments and empty lines */
    char *p = line;
    while (*p == ' ' || *p == '\t') { p++; }
    if (*p == '#' || *p == '\n' || *p == '\0') { continue; }

    /* section header */
    if (*p == '[') {
      char *end = strchr(p, ']');
      if (end != NULL) {
        *end = '\0';
        snprintf(section, sizeof(section), "%s", p + 1);
      }
      continue;
    }

    /* key = value */
    char *eq = strchr(p, '=');
    if (eq == NULL) { continue; }

    *eq = '\0';
    char *key = p;
    char *val = eq + 1;

    /* trim key */
    trim_trailing(key);

    /* trim value - skip leading spaces and quotes */
    while (*val == ' ' || *val == '\t') { val++; }
    if (*val == '"') { val++; }
    trim_trailing(val);

    /* apply values based on section.key */
    if (strcmp(section, "repo") == 0) {
      if (strcmp(key, "main_branch") == 0) {
        snprintf(cfg->main_branch, sizeof(cfg->main_branch), "%s", val);
      }
      if (strcmp(key, "plan_file") == 0) {
        snprintf(cfg->plan_file, sizeof(cfg->plan_file), "%s", val);
      }
    }
    if (strcmp(section, "display") == 0) {
      if (strcmp(key, "color") == 0) {
        cfg->color = (strcmp(val, "true") == 0) ? 1 : 0;
      }
    }
    if (strcmp(section, "cache") == 0) {
      if (strcmp(key, "auto_rebuild") == 0) {
        cfg->auto_rebuild = (strcmp(val, "true") == 0) ? 1 : 0;
      }
    }

    TIX_UNUSED(skip_prefix);
  }

  fclose(fp);
  return TIX_OK;
}

tix_err_t tix_config_save(const tix_config_t *cfg, const char *path) {
  if (cfg == NULL || path == NULL) { return TIX_ERR_INVALID_ARG; }

  FILE *fp = fopen(path, "w");
  if (fp == NULL) { return TIX_ERR_IO; }

  fprintf(fp, "[repo]\n");
  fprintf(fp, "main_branch = \"%s\"\n", cfg->main_branch);
  fprintf(fp, "plan_file = \"%s\"\n", cfg->plan_file);
  fprintf(fp, "\n[display]\n");
  fprintf(fp, "color = %s\n", cfg->color ? "true" : "false");
  fprintf(fp, "\n[cache]\n");
  fprintf(fp, "auto_rebuild = %s\n", cfg->auto_rebuild ? "true" : "false");

  fclose(fp);
  return TIX_OK;
}

tix_err_t tix_config_ensure_dir(const char *dir_path) {
  if (dir_path == NULL) { return TIX_ERR_INVALID_ARG; }

  struct stat st;
  if (stat(dir_path, &st) == 0) { return TIX_OK; }

  int rc = mkdir(dir_path, 0755);
  if (rc != 0) {
    TIX_ERROR("mkdir(%s) failed", dir_path);
    return TIX_ERR_IO;
  }
  return TIX_OK;
}
