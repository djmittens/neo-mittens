#include "git.h"
#include "log.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Reject shell metacharacters to prevent command injection via popen.
 * Allow: alphanumeric, space, /, ., -, _, :, @, =, +, ~, comma
 * Reject: ", $, `, \, !, (, ), ;, |, &, >, <, ', newline, etc. */
int tix_git_is_shell_safe(const char *s) {
  for (; *s != '\0'; s++) {
    unsigned char c = (unsigned char)*s;
    if (c < 0x20 && c != '\t') { return 0; }  /* control chars */
    if (c == '"' || c == '\'' || c == '`') { return 0; }
    if (c == '$' || c == '\\' || c == '!') { return 0; }
    if (c == '(' || c == ')') { return 0; }
    if (c == ';' || c == '|' || c == '&') { return 0; }
    if (c == '>' || c == '<') { return 0; }
    if (c == '\n' || c == '\r') { return 0; }
  }
  return 1;
}

int tix_git_run_cmd(const char *cmd, char *out, sz out_len) {
  if (cmd == NULL) { return -1; }

  FILE *fp = popen(cmd, "r");
  if (fp == NULL) { return -1; }

  sz total = 0;
  if (out != NULL && out_len > 0) {
    out[0] = '\0';
    while (total < out_len - 1) {
      int ch = fgetc(fp);
      if (ch == EOF) { break; }
      out[total] = (char)ch;
      total++;
    }
    out[total] = '\0';
    /* trim trailing newline */
    if (total > 0 && out[total - 1] == '\n') {
      out[total - 1] = '\0';
    }
  }

  int status = pclose(fp);
  return status;
}

tix_err_t tix_git_rev_parse_head(char *out, sz out_len) {
  if (out == NULL || out_len < 8) { return TIX_ERR_INVALID_ARG; }

  int status = tix_git_run_cmd("git rev-parse --short HEAD", out, out_len);
  if (status != 0) {
    TIX_ERROR("git rev-parse HEAD failed (status=%d)", status);
    return TIX_ERR_GIT;
  }
  return TIX_OK;
}

tix_err_t tix_git_user_name(char *out, sz out_len) {
  if (out == NULL || out_len < 2) { return TIX_ERR_INVALID_ARG; }

  int status = tix_git_run_cmd("git config user.name", out, out_len);
  if (status != 0 || out[0] == '\0') {
    TIX_DEBUG("git config user.name not set (status=%d)", status);
    out[0] = '\0';
    return TIX_ERR_NOT_FOUND;
  }
  return TIX_OK;
}

tix_err_t tix_git_current_branch(char *out, sz out_len) {
  if (out == NULL || out_len < 4) { return TIX_ERR_INVALID_ARG; }

  int status = tix_git_run_cmd(
      "git rev-parse --abbrev-ref HEAD", out, out_len);
  if (status != 0) {
    TIX_ERROR("git rev-parse --abbrev-ref HEAD failed (status=%d)", status);
    return TIX_ERR_GIT;
  }
  return TIX_OK;
}

int tix_git_is_detached_head(void) {
  char buf[TIX_MAX_BRANCH_LEN];
  tix_err_t err = tix_git_current_branch(buf, sizeof(buf));
  if (err != TIX_OK) { return 0; }
  return strcmp(buf, "HEAD") == 0;
}

tix_err_t tix_git_is_clean(int *is_clean) {
  if (is_clean == NULL) { return TIX_ERR_INVALID_ARG; }

  char buf[16];
  int status = tix_git_run_cmd("git status --porcelain", buf, sizeof(buf));
  if (status != 0) {
    TIX_ERROR("git status failed (status=%d)", status);
    return TIX_ERR_GIT;
  }
  *is_clean = (buf[0] == '\0') ? 1 : 0;
  return TIX_OK;
}

tix_err_t tix_git_add(const char *file) {
  if (file == NULL) { return TIX_ERR_INVALID_ARG; }
  if (!tix_git_is_shell_safe(file)) {
    TIX_ERROR("git add: path contains unsafe characters: %s", file);
    return TIX_ERR_INVALID_ARG;
  }

  char cmd[TIX_MAX_PATH_LEN + 16];
  int n = snprintf(cmd, sizeof(cmd), "git add '%s'", file);
  if (n < 0 || (sz)n >= sizeof(cmd)) { return TIX_ERR_OVERFLOW; }

  int status = tix_git_run_cmd(cmd, NULL, 0);
  if (status != 0) {
    TIX_ERROR("git add %s failed (status=%d)", file, status);
    return TIX_ERR_GIT;
  }
  return TIX_OK;
}

tix_err_t tix_git_commit(const char *message, const char *file) {
  if (message == NULL) { return TIX_ERR_INVALID_ARG; }

  tix_err_t err;
  if (file != NULL) {
    err = tix_git_add(file);
    if (err != TIX_OK) { return err; }
  }

  if (!tix_git_is_shell_safe(message)) {
    TIX_ERROR("git commit: message contains unsafe characters%s", "");
    return TIX_ERR_INVALID_ARG;
  }

  char cmd[TIX_MAX_DESC_LEN + 32];
  int n = snprintf(cmd, sizeof(cmd), "git commit -m '%s'", message);
  if (n < 0 || (sz)n >= sizeof(cmd)) { return TIX_ERR_OVERFLOW; }

  int status = tix_git_run_cmd(cmd, NULL, 0);
  if (status != 0) {
    TIX_DEBUG("git commit failed (status=%d), may be nothing to commit",
              status);
    return TIX_ERR_GIT;
  }
  return TIX_OK;
}

tix_err_t tix_git_toplevel(char *out, sz out_len) {
  if (out == NULL || out_len < 2) { return TIX_ERR_INVALID_ARG; }

  int status = tix_git_run_cmd(
      "git rev-parse --show-toplevel", out, out_len);
  if (status != 0) {
    TIX_ERROR("git rev-parse --show-toplevel failed (status=%d)", status);
    return TIX_ERR_GIT;
  }
  return TIX_OK;
}

tix_err_t tix_git_log_file(const char *file, tix_git_log_entry_t *entries,
                           u32 *count, u32 max_entries) {
  if (file == NULL || entries == NULL || count == NULL) {
    return TIX_ERR_INVALID_ARG;
  }

  if (!tix_git_is_shell_safe(file)) {
    TIX_ERROR("git log: path contains unsafe characters: %s", file);
    return TIX_ERR_INVALID_ARG;
  }

  char cmd[TIX_MAX_PATH_LEN + 128];
  int n = snprintf(cmd, sizeof(cmd),
      "git log --format='%%H|%%an|%%s|%%ct' -n %u -- '%s'",
      max_entries, file);
  if (n < 0 || (sz)n >= sizeof(cmd)) { return TIX_ERR_OVERFLOW; }

  char output[TIX_MAX_LINE_LEN];
  int status = tix_git_run_cmd(cmd, output, sizeof(output));
  if (status != 0) {
    TIX_DEBUG("git log for %s returned status=%d", file, status);
    *count = 0;
    return TIX_OK;
  }

  *count = 0;
  char *line = output;
  u32 idx = 0;

  while (*line != '\0' && idx < max_entries) {
    char *nl = strchr(line, '\n');
    if (nl != NULL) { *nl = '\0'; }

    /* parse: hash|author|message|timestamp */
    char *p1 = strchr(line, '|');
    if (p1 == NULL) { break; }
    *p1 = '\0';

    char *p2 = strchr(p1 + 1, '|');
    if (p2 == NULL) { break; }
    *p2 = '\0';

    char *p3 = strchr(p2 + 1, '|');
    if (p3 == NULL) { break; }
    *p3 = '\0';

    strncpy(entries[idx].hash, line, TIX_MAX_HASH_LEN - 1);
    entries[idx].hash[TIX_MAX_HASH_LEN - 1] = '\0';
    strncpy(entries[idx].author, p1 + 1, TIX_MAX_NAME_LEN - 1);
    entries[idx].author[TIX_MAX_NAME_LEN - 1] = '\0';
    strncpy(entries[idx].message, p2 + 1, TIX_MAX_DESC_LEN - 1);
    entries[idx].message[TIX_MAX_DESC_LEN - 1] = '\0';
    entries[idx].timestamp = strtoll(p3 + 1, NULL, 10);

    idx++;
    line = (nl != NULL) ? nl + 1 : line + strlen(line);
  }

  *count = idx;
  return TIX_OK;
}
