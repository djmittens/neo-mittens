#include "cmd.h"
#include "batch.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

tix_err_t tix_cmd_batch(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 1) {
    fprintf(stderr, "usage: tix batch <file|json>\n");
    return TIX_ERR_INVALID_ARG;
  }

  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  tix_batch_result_t result;

  /* if arg starts with '[', treat as inline JSON */
  if (argv[0][0] == '[') {
    err = tix_batch_execute_json(&ctx->db, ctx->plan_path,
                                 argv[0], &result);
  } else {
    err = tix_batch_execute(&ctx->db, ctx->plan_path,
                            argv[0], &result);
  }

  printf("{\"success\":%u,\"errors\":%u", result.success_count,
         result.error_count);
  if (result.last_error[0] != '\0') {
    printf(",\"last_error\":\"%s\"", result.last_error);
  }
  printf("}\n");

  return err;
}
