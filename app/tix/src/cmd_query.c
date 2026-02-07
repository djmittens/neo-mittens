/*
 * tix query command - TQL pipeline, raw SQL, and legacy filter modes.
 *
 * Usage:
 *   tix q "tasks | status=pending | count"      -- TQL pipeline
 *   tix q sql "SELECT author, COUNT(*) ..."      -- raw SQL
 *   tix query tasks --label foo                   -- legacy filter flags
 *   tix query full                                -- full dump (legacy)
 *
 * The "q" and "query" aliases are handled in main.c (same handler).
 */

#include "cmd.h"
#include "tql.h"
#include "git.h"
#include "json.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

/* ---- Legacy filter mode (backward compat) ---- */

typedef struct {
  int show_done;
  const char *label;
  const char *spec;
  const char *author;
  const char *priority;
  int has_filters;
} query_flags_t;

static void parse_flags(int argc, char **argv, query_flags_t *flags) {
  memset(flags, 0, sizeof(*flags));
  for (int i = 0; i < argc; i++) {
    if (strcmp(argv[i], "--done") == 0) {
      flags->show_done = 1;
    } else if (strcmp(argv[i], "--label") == 0 && i + 1 < argc) {
      flags->label = argv[++i];
      flags->has_filters = 1;
    } else if (strcmp(argv[i], "--spec") == 0 && i + 1 < argc) {
      flags->spec = argv[++i];
      flags->has_filters = 1;
    } else if (strcmp(argv[i], "--author") == 0 && i + 1 < argc) {
      flags->author = argv[++i];
      flags->has_filters = 1;
    } else if (strcmp(argv[i], "--priority") == 0 && i + 1 < argc) {
      flags->priority = argv[++i];
      flags->has_filters = 1;
    }
  }
}

static void print_ticket_array(tix_ticket_t *tickets, u32 count) {
  printf("[");
  for (u32 i = 0; i < count; i++) {
    if (i > 0) { printf(","); }
    char buf[TIX_MAX_LINE_LEN];
    tix_json_write_ticket(&tickets[i], buf, sizeof(buf));
    printf("%s", buf);
  }
  printf("]\n");
}

static tix_err_t query_full(tix_ctx_t *ctx) {
  tix_ticket_t tickets[TIX_MAX_BATCH];
  u32 count = 0;

  printf("{\"tasks\":{\"pending\":[");
  tix_db_list_tickets(&ctx->db, TIX_TICKET_TASK, TIX_STATUS_PENDING,
                      tickets, &count, TIX_MAX_BATCH);
  for (u32 i = 0; i < count; i++) {
    if (i > 0) { printf(","); }
    char buf[TIX_MAX_LINE_LEN];
    tix_json_write_ticket(&tickets[i], buf, sizeof(buf));
    printf("%s", buf);
  }

  printf("],\"done\":[");
  count = 0;
  tix_db_list_tickets(&ctx->db, TIX_TICKET_TASK, TIX_STATUS_DONE,
                      tickets, &count, TIX_MAX_BATCH);
  for (u32 i = 0; i < count; i++) {
    if (i > 0) { printf(","); }
    char buf[TIX_MAX_LINE_LEN];
    tix_json_write_ticket(&tickets[i], buf, sizeof(buf));
    printf("%s", buf);
  }

  printf("]},\"issues\":[");
  count = 0;
  tix_db_list_tickets(&ctx->db, TIX_TICKET_ISSUE, TIX_STATUS_PENDING,
                      tickets, &count, TIX_MAX_BATCH);
  for (u32 i = 0; i < count; i++) {
    if (i > 0) { printf(","); }
    char buf[TIX_MAX_LINE_LEN];
    tix_json_write_ticket(&tickets[i], buf, sizeof(buf));
    printf("%s", buf);
  }

  printf("],\"notes\":[");
  count = 0;
  tix_db_list_tickets(&ctx->db, TIX_TICKET_NOTE, TIX_STATUS_PENDING,
                      tickets, &count, TIX_MAX_BATCH);
  for (u32 i = 0; i < count; i++) {
    if (i > 0) { printf(","); }
    char buf[TIX_MAX_LINE_LEN];
    tix_json_write_ticket(&tickets[i], buf, sizeof(buf));
    printf("%s", buf);
  }

  char branch[TIX_MAX_BRANCH_LEN];
  tix_git_current_branch(branch, sizeof(branch));

  char head[TIX_MAX_HASH_LEN];
  tix_git_rev_parse_head(head, sizeof(head));

  printf("],\"meta\":{\"branch\":\"%s\",\"commit\":\"%s\"}}\n",
         branch, head);

  return TIX_OK;
}

static tix_err_t query_tasks_legacy(tix_ctx_t *ctx,
                                    const query_flags_t *flags) {
  tix_ticket_t tickets[TIX_MAX_BATCH];
  u32 count = 0;
  tix_status_e status = flags->show_done ? TIX_STATUS_DONE
                                         : TIX_STATUS_PENDING;

  if (flags->has_filters) {
    tix_db_filter_t filter;
    memset(&filter, 0, sizeof(filter));
    filter.type = TIX_TICKET_TASK;
    filter.status = status;
    filter.label = flags->label;
    filter.spec = flags->spec;
    filter.author = flags->author;
    if (flags->priority != NULL) {
      filter.priority = tix_priority_from_str(flags->priority);
      filter.filter_priority = 1;
    }
    tix_db_list_tickets_filtered(&ctx->db, &filter,
                                 tickets, &count, TIX_MAX_BATCH);
  } else {
    tix_db_list_tickets(&ctx->db, TIX_TICKET_TASK, status,
                        tickets, &count, TIX_MAX_BATCH);
  }

  print_ticket_array(tickets, count);
  return TIX_OK;
}

static tix_err_t query_issues_legacy(tix_ctx_t *ctx,
                                     const query_flags_t *flags) {
  tix_ticket_t tickets[TIX_MAX_BATCH];
  u32 count = 0;

  if (flags->has_filters) {
    tix_db_filter_t filter;
    memset(&filter, 0, sizeof(filter));
    filter.type = TIX_TICKET_ISSUE;
    filter.status = TIX_STATUS_PENDING;
    filter.label = flags->label;
    filter.spec = flags->spec;
    filter.author = flags->author;
    tix_db_list_tickets_filtered(&ctx->db, &filter,
                                 tickets, &count, TIX_MAX_BATCH);
  } else {
    tix_db_list_tickets(&ctx->db, TIX_TICKET_ISSUE, TIX_STATUS_PENDING,
                        tickets, &count, TIX_MAX_BATCH);
  }

  print_ticket_array(tickets, count);
  return TIX_OK;
}

/* ---- TQL pipeline mode ---- */

static tix_err_t query_tql(tix_ctx_t *ctx, const char *query_str) {
  char err_buf[256];
  tql_compiled_t compiled;

  tix_err_t err = tql_prepare(query_str, &compiled, err_buf, sizeof(err_buf));
  if (err != TIX_OK) {
    fprintf(stderr, "error: %s\n", err_buf);
    return err;
  }

  return tix_db_exec_tql(&ctx->db, &compiled);
}

/* ---- Raw SQL mode ---- */

static tix_err_t query_raw_sql(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 1) {
    fprintf(stderr, "error: sql subcommand requires a SQL string\n");
    return TIX_ERR_INVALID_ARG;
  }

  /* Concatenate all remaining args as the SQL query */
  char sql_buf[TQL_MAX_SQL_LEN];
  char *p = sql_buf;
  char *end = sql_buf + sizeof(sql_buf);
  for (int i = 0; i < argc; i++) {
    if (i > 0) {
      int n = snprintf(p, (sz)(end - p), " ");
      if (n < 0 || p + n >= end) { return TIX_ERR_OVERFLOW; }
      p += n;
    }
    int n = snprintf(p, (sz)(end - p), "%s", argv[i]);
    if (n < 0 || p + n >= end) { return TIX_ERR_OVERFLOW; }
    p += n;
  }

  return tix_db_exec_raw_sql(&ctx->db, sql_buf);
}

/* ---- Detect if first arg looks like a TQL query ---- */

static int is_tql_query(const char *arg) {
  /* TQL queries start with a source keyword and may contain pipes */
  if (strncmp(arg, "tasks", 5) == 0) { return 1; }
  if (strncmp(arg, "issues", 6) == 0) { return 1; }
  if (strncmp(arg, "notes", 5) == 0) { return 1; }
  if (strncmp(arg, "tickets", 7) == 0) { return 1; }
  return 0;
}

/* ---- Main dispatcher ---- */

tix_err_t tix_cmd_query(tix_ctx_t *ctx, int argc, char **argv) {
  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  /* No args: full dump */
  if (argc < 1) { return query_full(ctx); }

  const char *sub = argv[0];

  /* "sql" subcommand: raw SQL passthrough */
  if (strcmp(sub, "sql") == 0) {
    return query_raw_sql(ctx, argc - 1, argv + 1);
  }

  /* "full" subcommand: legacy full dump */
  if (strcmp(sub, "full") == 0) {
    return query_full(ctx);
  }

  /* Legacy flag-based subcommands */
  if (strcmp(sub, "tasks") == 0 || strcmp(sub, "issues") == 0) {
    /* Check for legacy --flag style args */
    int has_legacy_flags = 0;
    for (int i = 1; i < argc; i++) {
      if (argv[i][0] == '-') { has_legacy_flags = 1; break; }
    }

    if (has_legacy_flags) {
      query_flags_t flags;
      parse_flags(argc - 1, argv + 1, &flags);
      if (strcmp(sub, "tasks") == 0) {
        return query_tasks_legacy(ctx, &flags);
      }
      return query_issues_legacy(ctx, &flags);
    }

    /* No flags but bare "tasks" or "issues" -> treat as TQL source */
    if (argc == 1) {
      return query_tql(ctx, sub);
    }
  }

  /* If it looks like a TQL query (starts with source keyword), run as TQL.
     The entire arg string is the query (user passes it quoted). */
  if (is_tql_query(sub)) {
    /* Reconstruct full query from all args */
    char query_buf[TQL_MAX_SQL_LEN];
    char *p = query_buf;
    char *end = query_buf + sizeof(query_buf);
    for (int i = 0; i < argc; i++) {
      if (i > 0) {
        int n = snprintf(p, (sz)(end - p), " ");
        if (n < 0 || p + n >= end) { return TIX_ERR_OVERFLOW; }
        p += n;
      }
      int n = snprintf(p, (sz)(end - p), "%s", argv[i]);
      if (n < 0 || p + n >= end) { return TIX_ERR_OVERFLOW; }
      p += n;
    }
    return query_tql(ctx, query_buf);
  }

  fprintf(stderr,
    "error: unknown query subcommand: %s\n"
    "usage:\n"
    "  tix q \"<tql-query>\"          TQL pipeline query\n"
    "  tix q sql \"<sql>\"            Raw SQL query\n"
    "  tix q tasks [--flags]        Legacy filter query\n"
    "  tix q issues [--flags]       Legacy filter query\n"
    "  tix q full                   Full state dump\n",
    sub);
  return TIX_ERR_INVALID_ARG;
}
