#include "cmd.h"
#include "json.h"
#include "search.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

tix_err_t tix_cmd_search(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 1) {
    fprintf(stderr, "usage: tix search <query>\n");
    return TIX_ERR_INVALID_ARG;
  }

  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  tix_search_result_t results[20];
  u32 count = 0;

  err = tix_search_query(&ctx->db, argv[0], results, &count, 20);
  if (err != TIX_OK) { return err; }

  char esc_query[TIX_MAX_QUERY_LEN * 2];
  tix_json_escape(argv[0], esc_query, sizeof(esc_query));
  printf("{\"query\":\"%s\",\"results\":[", esc_query);
  for (u32 i = 0; i < count; i++) {
    if (i > 0) { printf(","); }
    char esc_name[TIX_MAX_NAME_LEN * 2];
    tix_json_escape(results[i].name, esc_name, sizeof(esc_name));
    printf("{\"id\":\"%s\",\"name\":\"%s\",\"score\":%.2f}",
           results[i].id, esc_name, results[i].score);
  }
  printf("],\"keyword_cloud\":");

  char cloud_buf[TIX_MAX_LINE_LEN];
  tix_search_keyword_cloud(&ctx->db, cloud_buf, sizeof(cloud_buf));
  printf("%s}\n", cloud_buf);

  return TIX_OK;
}
