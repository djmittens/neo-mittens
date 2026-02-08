#include "cmd.h"
#include "report.h"

#include <stdio.h>
#include <string.h>

tix_err_t tix_cmd_report(tix_ctx_t *ctx, int argc, char **argv) {
  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  (void)argc;
  (void)argv;

  tix_report_t report;
  err = tix_report_generate(&ctx->db, &report);
  if (err != TIX_OK) { return err; }

  char buf[TIX_MAX_LINE_LEN * 2];
  err = tix_report_print(&report, buf, sizeof(buf));
  if (err != TIX_OK) { return err; }

  printf("%s", buf);
  return TIX_OK;
}
