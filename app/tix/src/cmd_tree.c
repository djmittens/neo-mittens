#include "cmd.h"
#include "tree.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

tix_err_t tix_cmd_tree(tix_ctx_t *ctx, int argc, char **argv) {
  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  char buf[TIX_MAX_LINE_LEN * 4];

  if (argc >= 1) {
    err = tix_tree_render(&ctx->db, argv[0], buf, sizeof(buf));
  } else {
    err = tix_tree_render_all(&ctx->db, buf, sizeof(buf));
  }

  if (err != TIX_OK) { return err; }
  printf("%s", buf);
  return TIX_OK;
}
