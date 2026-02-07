#include "cmd.h"
#include "validate.h"
#include "log.h"

#include <stdio.h>

tix_err_t tix_cmd_validate(tix_ctx_t *ctx, int argc, char **argv) {
  TIX_UNUSED(argc);
  TIX_UNUSED(argv);

  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  tix_validation_result_t result;
  err = tix_validate_history(&ctx->db, ctx->plan_path, &result);
  if (err != TIX_OK) { return err; }

  char buf[TIX_MAX_LINE_LEN * 2];
  err = tix_validate_print(&result, buf, sizeof(buf));
  if (err != TIX_OK) { return err; }

  printf("%s", buf);
  return result.valid ? TIX_OK : TIX_ERR_VALIDATION;
}
