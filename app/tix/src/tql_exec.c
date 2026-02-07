/*
 * TQL execution - runs compiled TQL queries against SQLite
 * and streams JSON results to stdout.
 *
 * Separated from db.c to respect the 1000-line file limit.
 */

#include "db.h"
#include "json.h"
#include "log.h"

#include <stdio.h>
#include <string.h>
#include <strings.h>  /* strncasecmp */

/* Escape and print a string value as JSON */
static void print_json_string(const char *s) {
  char escaped[TIX_MAX_DESC_LEN];
  tix_json_escape(s, escaped, sizeof(escaped));
  printf("\"%s\"", escaped);
}

/* Print a single column value as JSON based on SQLite type */
static void print_column_value(sqlite3_stmt *stmt, int col) {
  int col_type = sqlite3_column_type(stmt, col);
  switch (col_type) {
    case SQLITE_INTEGER:
      printf("%lld", (long long)sqlite3_column_int64(stmt, col));
      break;
    case SQLITE_FLOAT:
      printf("%.6g", sqlite3_column_double(stmt, col));
      break;
    case SQLITE_NULL:
      printf("null");
      break;
    case SQLITE_TEXT: {
      const char *text = (const char *)sqlite3_column_text(stmt, col);
      if (text != NULL) {
        print_json_string(text);
      } else {
        printf("null");
      }
      break;
    }
    default:
      printf("null");
      break;
  }
}

tix_err_t tix_db_exec_tql(tix_db_t *db, const tql_compiled_t *compiled) {
  if (db == NULL || compiled == NULL) { return TIX_ERR_INVALID_ARG; }

  TIX_DEBUG("TQL SQL: %s", compiled->sql);

  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, compiled->sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    fprintf(stderr, "error: SQL prepare failed: %s\n",
            sqlite3_errmsg(db->handle));
    return TIX_ERR_DB;
  }

  /* Bind parameters */
  for (u32 i = 0; i < compiled->bind_count; i++) {
    int idx = (int)(i + 1);
    if (compiled->binds[i].is_int) {
      sqlite3_bind_int64(stmt, idx, compiled->binds[i].ival);
    } else if (compiled->binds[i].is_double) {
      sqlite3_bind_double(stmt, idx, compiled->binds[i].dval);
    } else {
      sqlite3_bind_text(stmt, idx, compiled->binds[i].sval, -1,
                        SQLITE_STATIC);
    }
  }

  int col_count = sqlite3_column_count(stmt);

  printf("[");
  int row_idx = 0;

  while (sqlite3_step(stmt) == SQLITE_ROW) {
    if (row_idx > 0) { printf(","); }
    printf("{");

    if (compiled->column_count > 0) {
      /* Use known column names from compilation */
      u32 limit = compiled->column_count;
      if ((int)limit > col_count) { limit = (u32)col_count; }
      for (u32 c = 0; c < limit; c++) {
        if (c > 0) { printf(","); }
        printf("\"%s\":", compiled->columns[c]);
        print_column_value(stmt, (int)c);
      }
    } else {
      /* Use SQLite column names (for SELECT *) */
      for (int c = 0; c < col_count; c++) {
        if (c > 0) { printf(","); }
        const char *name = sqlite3_column_name(stmt, c);
        printf("\"%s\":", name != NULL ? name : "?");
        print_column_value(stmt, c);
      }
    }

    printf("}");
    row_idx++;
  }

  printf("]\n");
  sqlite3_finalize(stmt);

  return TIX_OK;
}

tix_err_t tix_db_exec_raw_sql(tix_db_t *db, const char *sql) {
  if (db == NULL || sql == NULL) { return TIX_ERR_INVALID_ARG; }

  /* Safety: reject obviously destructive statements */
  const char *p = sql;
  while (*p == ' ' || *p == '\t' || *p == '\n') { p++; }

  /* Only allow SELECT and WITH (for CTEs) */
  if (strncasecmp(p, "SELECT", 6) != 0 &&
      strncasecmp(p, "WITH", 4) != 0) {
    fprintf(stderr, "error: only SELECT/WITH statements allowed in raw SQL\n");
    return TIX_ERR_INVALID_ARG;
  }

  TIX_DEBUG("Raw SQL: %s", sql);

  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    fprintf(stderr, "error: SQL prepare failed: %s\n",
            sqlite3_errmsg(db->handle));
    return TIX_ERR_DB;
  }

  int col_count = sqlite3_column_count(stmt);

  printf("[");
  int row_idx = 0;

  while (sqlite3_step(stmt) == SQLITE_ROW) {
    if (row_idx > 0) { printf(","); }
    printf("{");

    for (int c = 0; c < col_count; c++) {
      if (c > 0) { printf(","); }
      const char *name = sqlite3_column_name(stmt, c);
      printf("\"%s\":", name != NULL ? name : "?");
      print_column_value(stmt, c);
    }

    printf("}");
    row_idx++;
  }

  printf("]\n");
  sqlite3_finalize(stmt);

  return TIX_OK;
}
