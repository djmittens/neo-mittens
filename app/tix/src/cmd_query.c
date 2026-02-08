/*
 * tix query command - TQL pipeline and raw SQL modes.
 *
 * Usage:
 *   tix q "tasks | status=pending | count"      -- TQL pipeline
 *   tix q sql "SELECT author, COUNT(*) ..."      -- raw SQL
 *
 * The "q" and "query" aliases are handled in main.c (same handler).
 */

#include "cmd.h"
#include "tql.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

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

  if (argc < 1) {
    fprintf(stderr,
      "usage:\n"
      "  tix q \"<tql-query>\"          TQL pipeline query\n"
      "  tix q sql \"<sql>\"            Raw SQL query\n");
    return TIX_ERR_INVALID_ARG;
  }

  const char *sub = argv[0];

  /* "sql" subcommand: raw SQL passthrough */
  if (strcmp(sub, "sql") == 0) {
    return query_raw_sql(ctx, argc - 1, argv + 1);
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
    "  tix q sql \"<sql>\"            Raw SQL query\n",
    sub);
  return TIX_ERR_INVALID_ARG;
}
