#pragma once

/*
 * ANSI color support for tix human-readable output.
 *
 * Design principles (from clig.dev, no-color.org, bettercli.org):
 *   - Respect NO_COLOR environment variable
 *   - Detect TTY via isatty() on the target fd
 *   - Respect config.toml [display] color = true/false
 *   - Use only basic 16 ANSI colors (theme-aware, universal)
 *   - Provide both fprintf and buffer-snprintf helpers
 */

#include <stdio.h>
#include <unistd.h>

#include "types.h"
#include "common.h"
#include "ticket.h"

/* ---- ANSI escape sequences ---- */

#define TIX_RESET       "\033[0m"
#define TIX_BOLD        "\033[1m"
#define TIX_DIM         "\033[2m"
#define TIX_UNDERLINE   "\033[4m"

/* foreground colors */
#define TIX_RED         "\033[31m"
#define TIX_GREEN       "\033[32m"
#define TIX_YELLOW      "\033[33m"
#define TIX_BLUE        "\033[34m"
#define TIX_MAGENTA     "\033[35m"
#define TIX_CYAN        "\033[36m"
#define TIX_WHITE       "\033[37m"

/* bright foreground */
#define TIX_BRIGHT_RED      "\033[91m"
#define TIX_BRIGHT_GREEN    "\033[92m"
#define TIX_BRIGHT_YELLOW   "\033[93m"
#define TIX_BRIGHT_BLUE     "\033[94m"
#define TIX_BRIGHT_CYAN     "\033[96m"

/* ---- Global color state ---- */

/*
 * Call once at startup after loading config.
 * Checks: config.color, isatty(fd), NO_COLOR env, TERM=dumb.
 * fd is typically STDOUT_FILENO for main output, STDERR_FILENO for logs.
 */
void tix_color_init(int config_color, int fd);

/* Returns 1 if color is enabled, 0 otherwise. */
int tix_color_enabled(void);

/* ---- Convenience: color strings that resolve to "" when disabled ---- */

static inline const char *tix_c(const char *code) {
  return tix_color_enabled() ? code : "";
}

/* ---- Semantic color helpers ---- */

/* Status colors: pending=yellow, done=green, accepted=bright green */
static inline const char *tix_status_color(tix_status_e s) {
  if (!tix_color_enabled()) { return ""; }
  switch (s) {
    case TIX_STATUS_PENDING:  return TIX_YELLOW;
    case TIX_STATUS_DONE:     return TIX_GREEN;
    case TIX_STATUS_ACCEPTED: return TIX_BRIGHT_GREEN;
  }
  return "";
}

/* Priority colors: high=red, medium=yellow, low=dim, none="" */
static inline const char *tix_priority_color(tix_priority_e p) {
  if (!tix_color_enabled()) { return ""; }
  switch (p) {
    case TIX_PRIORITY_HIGH:   return TIX_BRIGHT_RED;
    case TIX_PRIORITY_MEDIUM: return TIX_YELLOW;
    case TIX_PRIORITY_LOW:    return TIX_DIM;
    case TIX_PRIORITY_NONE:   return "";
  }
  return "";
}

/* ---- Buffer-safe color printf ----
 * Like TIX_BUF_PRINTF but wraps content in color codes.
 * Usage: TIX_BUF_COLOR(p, end, ret, TIX_RED, "error: %s", msg);
 */
#define TIX_BUF_COLOR(p, end, overflow_ret, color, ...)                \
  do {                                                                 \
    if (tix_color_enabled()) {                                         \
      TIX_BUF_PRINTF((p), (end), (overflow_ret), "%s", (color));      \
    }                                                                  \
    TIX_BUF_PRINTF((p), (end), (overflow_ret), __VA_ARGS__);          \
    if (tix_color_enabled()) {                                         \
      TIX_BUF_PRINTF((p), (end), (overflow_ret), "%s", TIX_RESET);   \
    }                                                                  \
  } while (0)

/* Progress bar: renders [========>   ] style into buffer.
 * width is the inner width (not including brackets). */
static inline tix_err_t tix_progress_bar(char *buf, sz buf_len,
                                         int pct, int width) {
  if (buf == NULL || width < 3) { return TIX_ERR_INVALID_ARG; }
  char *p = buf;
  char *end = buf + buf_len;

  int filled = (pct * width) / 100;
  if (filled > width) { filled = width; }

  const char *bar_color = TIX_GREEN;
  if (pct < 25)      { bar_color = TIX_RED; }
  else if (pct < 50) { bar_color = TIX_YELLOW; }
  else if (pct < 75) { bar_color = TIX_BRIGHT_YELLOW; }

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "%s[", tix_c(TIX_DIM));
  if (tix_color_enabled()) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "%s%s",
                   TIX_RESET, bar_color);
  }

  for (int i = 0; i < filled; i++) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "%s",
                   (i == filled - 1 && filled < width) ? ">" : "=");
  }
  if (tix_color_enabled()) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "%s", TIX_RESET);
  }
  for (int i = filled; i < width; i++) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, " ");
  }
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "%s]%s",
                 tix_c(TIX_DIM), tix_c(TIX_RESET));

  return TIX_OK;
}
