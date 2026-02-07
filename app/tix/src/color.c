#include "color.h"

#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int g_color_enabled = 0;
static int g_color_inited  = 0;

void tix_color_init(int config_color, int fd) {
  g_color_inited = 1;

  /* Config says no color */
  if (!config_color) {
    g_color_enabled = 0;
    return;
  }

  /* NO_COLOR env var (no-color.org): if set and non-empty, disable */
  const char *no_color = getenv("NO_COLOR");
  if (no_color != NULL && no_color[0] != '\0') {
    g_color_enabled = 0;
    return;
  }

  /* TERM=dumb: disable color */
  const char *term = getenv("TERM");
  if (term != NULL && strcmp(term, "dumb") == 0) {
    g_color_enabled = 0;
    return;
  }

  /* Not a TTY: disable color (piped output) */
  if (!isatty(fd)) {
    g_color_enabled = 0;
    return;
  }

  g_color_enabled = 1;
}

int tix_color_enabled(void) {
  /* If never initialized, default to off (safe for programmatic use) */
  if (!g_color_inited) { return 0; }
  return g_color_enabled;
}
