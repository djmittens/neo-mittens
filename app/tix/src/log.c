#include "log.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static tix_log_level_e tix_log_level = TIX_LOG_WARN;
static int tix_log_inited = 0;

static tix_log_level_e level_from_string(const char *s) {
  if (s == NULL) { return TIX_LOG_WARN; }
  if (strcmp(s, "error") == 0) { return TIX_LOG_ERROR; }
  if (strcmp(s, "warn") == 0)  { return TIX_LOG_WARN; }
  if (strcmp(s, "info") == 0)  { return TIX_LOG_INFO; }
  if (strcmp(s, "debug") == 0) { return TIX_LOG_DEBUG; }
  if (strcmp(s, "trace") == 0) { return TIX_LOG_TRACE; }
  return TIX_LOG_WARN;
}

void tix_log_init(void) {
  if (tix_log_inited) { return; }
  const char *env = getenv("TIX_LOG");
  tix_log_level = level_from_string(env);
  tix_log_inited = 1;
}

void tix_log_set_level(tix_log_level_e lvl) {
  tix_log_init();
  tix_log_level = lvl;
}

tix_log_level_e tix_log_get_level(void) {
  tix_log_init();
  return tix_log_level;
}

int tix_log_would_log(tix_log_level_e lvl) {
  tix_log_init();
  return lvl <= tix_log_level;
}

static const char *lvl_name(tix_log_level_e lvl) {
  switch (lvl) {
    case TIX_LOG_ERROR: return "ERROR";
    case TIX_LOG_WARN:  return "WARN";
    case TIX_LOG_INFO:  return "INFO";
    case TIX_LOG_DEBUG: return "DEBUG";
    case TIX_LOG_TRACE: return "TRACE";
  }
  return "?";
}

void tix_log(tix_log_level_e lvl, const char *file, int line,
             const char *func, const char *fmt, ...) {
  if (!tix_log_would_log(lvl)) { return; }
  FILE *out = stderr;  /* all log output to stderr to avoid corrupting JSON on stdout */
  fprintf(out, "[%s] %s:%d:%s | ", lvl_name(lvl), file, line, func);
  va_list va;
  va_start(va, fmt);
  vfprintf(out, fmt, va);
  va_end(va);
  fputc('\n', out);
}
