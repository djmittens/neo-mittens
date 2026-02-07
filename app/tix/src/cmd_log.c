#include "cmd.h"
#include "git.h"
#include "json.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

tix_err_t tix_cmd_log(tix_ctx_t *ctx, int argc, char **argv) {
  TIX_UNUSED(argc);
  TIX_UNUSED(argv);

  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  tix_git_log_entry_t entries[20];
  u32 count = 0;

  err = tix_git_log_file(ctx->plan_path, entries, &count, 20);
  if (err != TIX_OK) { return err; }

  printf("[");
  for (u32 i = 0; i < count; i++) {
    if (i > 0) { printf(","); }
    char esc_author[TIX_MAX_NAME_LEN * 2];
    char esc_msg[TIX_MAX_DESC_LEN * 2];
    tix_json_escape(entries[i].author, esc_author, sizeof(esc_author));
    tix_json_escape(entries[i].message, esc_msg, sizeof(esc_msg));
    printf("{\"hash\":\"%s\",\"author\":\"%s\",\"message\":\"%s\","
           "\"timestamp\":%lld}",
           entries[i].hash, esc_author, esc_msg, entries[i].timestamp);
  }
  printf("]\n");

  return TIX_OK;
}
