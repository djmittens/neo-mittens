#include "log.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static tix_log_level_e tix_log_level = TIX_LOG_WARN;
static int tix_log_inited = 0;
static int tix_log_color  = 0;

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

  /* Enable color for stderr if TTY and NO_COLOR not set */
  const char *no_color = getenv("NO_COLOR");
  const char *term = getenv("TERM");
  int no_color_set = (no_color != NULL && no_color[0] != '\0');
  int dumb_term = (term != NULL && strcmp(term, "dumb") == 0);
  tix_log_color = (!no_color_set && !dumb_term && isatty(STDERR_FILENO));
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

static const char *lvl_color(tix_log_level_e lvl) {
  switch (lvl) {
    case TIX_LOG_ERROR: return "\033[1;91m";  /* bold bright red */
    case TIX_LOG_WARN:  return "\033[1;33m";  /* bold yellow */
    case TIX_LOG_INFO:  return "\033[36m";     /* cyan */
    case TIX_LOG_DEBUG: return "\033[2m";      /* dim */
    case TIX_LOG_TRACE: return "\033[2m";      /* dim */
  }
  return "";
}

void tix_log(tix_log_level_e lvl, const char *file, int line,
             const char *func, const char *fmt, ...) {
  if (!tix_log_would_log(lvl)) { return; }
  FILE *out = stderr;  /* all log output to stderr to avoid corrupting JSON on stdout */
  if (tix_log_color) {
    fprintf(out, "%s[%s]\033[0m \033[2m%s:%d:%s\033[0m | ",
            lvl_color(lvl), lvl_name(lvl), file, line, func);
  } else {
    fprintf(out, "[%s] %s:%d:%s | ", lvl_name(lvl), file, line, func);
  }
  va_list va;
  va_start(va, fmt);
  vfprintf(out, fmt, va);
  va_end(va);
  fputc('\n', out);
}
