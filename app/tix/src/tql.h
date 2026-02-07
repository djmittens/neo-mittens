#pragma once

/*
 * TQL - Tix Query Language
 *
 * A simple pipe-based query DSL that compiles to SQL.
 * Designed for agent consumption: composable, domain-aware, JSON output.
 *
 * Syntax:  source | filters | stage | stage ...
 *
 * Sources:   tasks, issues, notes, tickets (all types)
 * Filters:   field=val, field!=val, field>val, field<val, field~pattern
 * Stages:    select f1,f2  |  group field  |  count  |  sum field
 *            avg field  |  min field  |  max field  |  sort field [asc|desc]
 *            limit N
 *
 * Enum sugar: status=pending -> status=0, priority=high -> priority=3, etc.
 * Label filter: label=foo triggers JOIN on ticket_labels table.
 *
 * Raw SQL escape hatch:  tix q sql "SELECT ..."
 */

#include "types.h"
#include "common.h"

/* ---- Limits ---- */

#define TQL_MAX_FILTERS    16
#define TQL_MAX_SELECT     16
#define TQL_MAX_SORTS       4
#define TQL_MAX_AGGREGATES  8
#define TQL_MAX_HAVINGS     8
#define TQL_MAX_OR_VALUES   8
#define TQL_MAX_FIELD_LEN  64
#define TQL_MAX_VALUE_LEN 256
#define TQL_MAX_SQL_LEN  4096
#define TQL_MAX_BINDS      48

/* ---- Filter operators ---- */

typedef enum {
  TQL_OP_EQ = 0,   /* field=value */
  TQL_OP_NE,       /* field!=value */
  TQL_OP_GT,       /* field>value */
  TQL_OP_LT,       /* field<value */
  TQL_OP_GE,       /* field>=value */
  TQL_OP_LE,       /* field<=value */
  TQL_OP_LIKE,     /* field~pattern (prefix/suffix/contains) */
  TQL_OP_IS_NULL,  /* field= (empty value -> IS NULL) */
  TQL_OP_IS_NOT_NULL, /* field!= (empty value -> IS NOT NULL) */
  TQL_OP_IN,       /* field=val1,val2,val3 (OR logic) */
  TQL_OP_NOT_IN,   /* field!=val1,val2,val3 (NOT IN) */
} tql_op_e;

/* ---- Aggregate functions ---- */

typedef enum {
  TQL_AGG_COUNT = 0,
  TQL_AGG_SUM,
  TQL_AGG_AVG,
  TQL_AGG_MIN,
  TQL_AGG_MAX,
  TQL_AGG_COUNT_DISTINCT,
} tql_agg_e;

/* ---- Sort direction ---- */

typedef enum {
  TQL_SORT_ASC = 0,
  TQL_SORT_DESC,
} tql_sort_dir_e;

/* ---- AST nodes (all stack-allocated) ---- */

typedef struct {
  char field[TQL_MAX_FIELD_LEN];
  tql_op_e op;
  char value[TQL_MAX_VALUE_LEN];
  int negated;  /* 1 if prefixed with ! (NOT) */
  /* For IN/NOT_IN: multiple comma-separated values */
  char or_values[TQL_MAX_OR_VALUES][TQL_MAX_VALUE_LEN];
  u32 or_count;
} tql_filter_t;

typedef struct {
  tql_agg_e func;
  char field[TQL_MAX_FIELD_LEN]; /* empty for COUNT(*) */
} tql_aggregate_t;

typedef struct {
  char field[TQL_MAX_FIELD_LEN];
  tql_sort_dir_e dir;
} tql_sort_t;

/* ---- HAVING filter (post-aggregate) ---- */

typedef struct {
  char column[TQL_MAX_FIELD_LEN];  /* aggregate alias: count, sum_cost, etc. */
  tql_op_e op;
  char value[TQL_MAX_VALUE_LEN];
} tql_having_t;

/* ---- Parsed pipeline ---- */

typedef enum {
  TQL_SOURCE_TASKS = 0,
  TQL_SOURCE_ISSUES,
  TQL_SOURCE_NOTES,
  TQL_SOURCE_TICKETS,  /* all types */
} tql_source_e;

typedef struct {
  /* source */
  tql_source_e source;
  int has_source;

  /* filters (WHERE clauses) */
  tql_filter_t filters[TQL_MAX_FILTERS];
  u32 filter_count;

  /* select fields (empty = SELECT *) */
  char selects[TQL_MAX_SELECT][TQL_MAX_FIELD_LEN];
  u32 select_count;

  /* group by */
  char group_by[TQL_MAX_FIELD_LEN];
  int has_group;

  /* aggregates */
  tql_aggregate_t aggregates[TQL_MAX_AGGREGATES];
  u32 agg_count;

  /* HAVING filters (post-aggregate) */
  tql_having_t havings[TQL_MAX_HAVINGS];
  u32 having_count;

  /* order by */
  tql_sort_t sorts[TQL_MAX_SORTS];
  u32 sort_count;

  /* limit */
  u32 limit;
  int has_limit;

  /* offset (pagination) */
  u32 offset;
  int has_offset;

  /* distinct */
  int has_distinct;
} tql_pipeline_t;

/* ---- Compiled SQL + bind values ---- */

typedef struct {
  int is_int;
  int is_double;
  i64 ival;
  double dval;
  char sval[TQL_MAX_VALUE_LEN];
} tql_bind_t;

typedef struct {
  char sql[TQL_MAX_SQL_LEN];
  tql_bind_t binds[TQL_MAX_BINDS];
  u32 bind_count;

  /* result column names (for JSON keys in output) */
  char columns[TQL_MAX_SELECT + TQL_MAX_AGGREGATES][TQL_MAX_FIELD_LEN];
  u32 column_count;
  int is_aggregate;  /* true if result has aggregates (changes output format) */
} tql_compiled_t;

/* ---- API ---- */

/* Initialize a pipeline to defaults */
void tql_pipeline_init(tql_pipeline_t *p);

/* Parse a TQL query string into a pipeline. Returns TIX_OK or TIX_ERR_PARSE.
   On error, writes a message to err_buf. */
tix_err_t tql_parse(const char *query, tql_pipeline_t *out,
                    char *err_buf, sz err_len);

/* Compile a parsed pipeline to SQL. Returns TIX_OK or TIX_ERR_OVERFLOW.
   On error, writes a message to err_buf. */
tix_err_t tql_compile(const tql_pipeline_t *p, tql_compiled_t *out,
                      char *err_buf, sz err_len);

/* Convenience: parse + compile in one call. */
tix_err_t tql_prepare(const char *query, tql_compiled_t *out,
                      char *err_buf, sz err_len);
