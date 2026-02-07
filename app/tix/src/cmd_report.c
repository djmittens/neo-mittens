#include "cmd.h"
#include "report.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

static tix_err_t report_progress(tix_ctx_t *ctx) {
  tix_report_t report;
  tix_err_t err = tix_report_generate(&ctx->db, &report);
  if (err != TIX_OK) { return err; }

  char buf[TIX_MAX_LINE_LEN * 2];
  err = tix_report_print(&report, buf, sizeof(buf));
  if (err != TIX_OK) { return err; }

  printf("%s", buf);
  return TIX_OK;
}

static tix_err_t report_velocity(tix_ctx_t *ctx) {
  tix_velocity_report_t report;
  tix_err_t err = tix_report_velocity(&ctx->db, &report);
  if (err != TIX_OK) { return err; }

  char buf[TIX_MAX_LINE_LEN * 2];
  err = tix_report_velocity_print(&report, buf, sizeof(buf));
  if (err != TIX_OK) { return err; }

  printf("%s", buf);
  return TIX_OK;
}

static tix_err_t report_actors(tix_ctx_t *ctx) {
  tix_actors_report_t report;
  tix_err_t err = tix_report_actors(&ctx->db, &report);
  if (err != TIX_OK) { return err; }

  char buf[TIX_MAX_LINE_LEN * 4];
  err = tix_report_actors_print(&report, buf, sizeof(buf));
  if (err != TIX_OK) { return err; }

  printf("%s", buf);
  return TIX_OK;
}

static tix_err_t report_models(tix_ctx_t *ctx) {
  tix_models_report_t report;
  tix_err_t err = tix_report_models(&ctx->db, &report);
  if (err != TIX_OK) { return err; }

  char buf[TIX_MAX_LINE_LEN * 4];
  err = tix_report_models_print(&report, buf, sizeof(buf));
  if (err != TIX_OK) { return err; }

  printf("%s", buf);
  return TIX_OK;
}

tix_err_t tix_cmd_report(tix_ctx_t *ctx, int argc, char **argv) {
  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  /* no subcommand = progress report (backward compatible) */
  if (argc < 1) {
    return report_progress(ctx);
  }

  const char *sub = argv[0];
  if (strcmp(sub, "velocity") == 0) {
    return report_velocity(ctx);
  }
  if (strcmp(sub, "actors") == 0) {
    return report_actors(ctx);
  }
  if (strcmp(sub, "models") == 0) {
    return report_models(ctx);
  }

  fprintf(stderr,
          "usage: tix report [velocity|actors|models]\n"
          "  (no args)  Progress summary\n"
          "  velocity   Throughput, cost, and cycle time metrics\n"
          "  actors     Per-author breakdown\n"
          "  models     Per-model breakdown\n");
  return TIX_ERR_INVALID_ARG;
}
