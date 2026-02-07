#include "cmd.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

static void print_usage(void) {
  fprintf(stderr,
    "tix - git-based ticketing & workflow system\n"
    "\n"
    "usage: tix <command> [args...]\n"
    "\n"
    "commands:\n"
    "  init                  Initialize .tix/ in current repo\n"
    "  task <sub> [args]     Task operations (add|done|accept|reject|delete|prioritize)\n"
    "  issue <sub> [args]    Issue operations (add|done|done-all|done-ids)\n"
    "  note <sub> [args]     Note operations (add|list|done)\n"
    "  query [sub] [args]    Query state (tasks|issues|full)\n"
    "  status                Human-readable dashboard\n"
    "  log                   Git history of plan changes\n"
    "  tree [id]             Dependency tree visualization\n"
    "  report                Progress tracking report\n"
    "  search <query>        Search tickets by keywords\n"
    "  validate              Validate history integrity\n"
    "  batch <file|json>     Execute batch operations\n"
    "  sync [branch|--all]   Sync cache from git history\n"
    "  compact               Sync + compact plan.jsonl\n"
    "\n"
    "environment:\n"
    "  TIX_LOG=<level>       Set log level (error|warn|info|debug|trace)\n"
  );
}

int main(int argc, char **argv) {
  tix_log_init();

  if (argc < 2) {
    print_usage();
    return 1;
  }

  const char *cmd = argv[1];

  /* init is special - doesn't require existing .tix/ */
  if (strcmp(cmd, "init") == 0) {
    tix_err_t err = tix_cmd_init(argc - 2, argv + 2);
    return (err == TIX_OK) ? 0 : 1;
  }

  if (strcmp(cmd, "help") == 0 || strcmp(cmd, "--help") == 0 ||
      strcmp(cmd, "-h") == 0) {
    print_usage();
    return 0;
  }

  /* all other commands require initialized context */
  tix_ctx_t ctx;
  tix_err_t err = tix_ctx_init(&ctx);
  if (err != TIX_OK) { return 1; }

  int remaining_argc = argc - 2;
  char **remaining_argv = argv + 2;

  if (strcmp(cmd, "task") == 0) {
    err = tix_cmd_task(&ctx, remaining_argc, remaining_argv);
  } else if (strcmp(cmd, "issue") == 0) {
    err = tix_cmd_issue(&ctx, remaining_argc, remaining_argv);
  } else if (strcmp(cmd, "note") == 0) {
    err = tix_cmd_note(&ctx, remaining_argc, remaining_argv);
  } else if (strcmp(cmd, "query") == 0) {
    err = tix_cmd_query(&ctx, remaining_argc, remaining_argv);
  } else if (strcmp(cmd, "status") == 0) {
    err = tix_cmd_status(&ctx, remaining_argc, remaining_argv);
  } else if (strcmp(cmd, "log") == 0) {
    err = tix_cmd_log(&ctx, remaining_argc, remaining_argv);
  } else if (strcmp(cmd, "tree") == 0) {
    err = tix_cmd_tree(&ctx, remaining_argc, remaining_argv);
  } else if (strcmp(cmd, "report") == 0) {
    err = tix_cmd_report(&ctx, remaining_argc, remaining_argv);
  } else if (strcmp(cmd, "search") == 0) {
    err = tix_cmd_search(&ctx, remaining_argc, remaining_argv);
  } else if (strcmp(cmd, "validate") == 0) {
    err = tix_cmd_validate(&ctx, remaining_argc, remaining_argv);
  } else if (strcmp(cmd, "batch") == 0) {
    err = tix_cmd_batch(&ctx, remaining_argc, remaining_argv);
  } else if (strcmp(cmd, "sync") == 0) {
    err = tix_cmd_sync(&ctx, remaining_argc, remaining_argv);
  } else if (strcmp(cmd, "compact") == 0) {
    err = tix_cmd_compact(&ctx, remaining_argc, remaining_argv);
  } else {
    fprintf(stderr, "error: unknown command: %s\n", cmd);
    print_usage();
    err = TIX_ERR_INVALID_ARG;
  }

  tix_ctx_close(&ctx);
  return (err == TIX_OK) ? 0 : 1;
}
