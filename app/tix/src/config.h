#pragma once

#include "types.h"
#include "common.h"

typedef struct {
  char main_branch[TIX_MAX_BRANCH_LEN];
  int color;
  int auto_rebuild;
  char plan_file[TIX_MAX_PATH_LEN];
} tix_config_t;

void tix_config_defaults(tix_config_t *cfg);
tix_err_t tix_config_load(tix_config_t *cfg, const char *path);
tix_err_t tix_config_save(const tix_config_t *cfg, const char *path);
tix_err_t tix_config_ensure_dir(const char *dir_path);
