#pragma once

#include "types.h"
#include "common.h"

typedef struct {
  char hash[TIX_MAX_HASH_LEN];
  char author[TIX_MAX_NAME_LEN];
  char message[TIX_MAX_DESC_LEN];
  i64 timestamp;
} tix_git_log_entry_t;

tix_err_t tix_git_rev_parse_head(char *out, sz out_len);
tix_err_t tix_git_current_branch(char *out, sz out_len);
tix_err_t tix_git_is_clean(int *is_clean);
tix_err_t tix_git_commit(const char *message, const char *file);
tix_err_t tix_git_add(const char *file);
tix_err_t tix_git_toplevel(char *out, sz out_len);
tix_err_t tix_git_log_file(const char *file, tix_git_log_entry_t *entries,
                           u32 *count, u32 max_entries);

int tix_git_run_cmd(const char *cmd, char *out, sz out_len);

/* Check if a string is safe to embed in a shell command (no metacharacters) */
int tix_git_is_shell_safe(const char *s);
