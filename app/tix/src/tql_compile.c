/*
 * TQL SQL Compiler
 *
 * Compiles a parsed TQL pipeline (tql_pipeline_t) into parameterized SQL
 * with bind values. Separated from tql.c (parser) to respect the
 * 1000-line file limit.
 */

#include "tql.h"
#include "log.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---- Enum translation tables (shared with parser) ---- */

typedef struct {
  const char *name;
  int value;
} tql_compile_enum_t;

static const tql_compile_enum_t STATUS_MAP[] = {
  {"pending",  0},
  {"done",     1},
  {"accepted", 2},
  {"rejected", 3},
  {"deleted",  4},
  {NULL, 0}
};

static const tql_compile_enum_t TYPE_MAP[] = {
  {"task",  0},
  {"issue", 1},
  {"note",  2},
  {NULL, 0}
};

static const tql_compile_enum_t PRIORITY_MAP[] = {
  {"none",   0},
  {"low",    1},
  {"medium", 2},
  {"high",   3},
  {NULL, 0}
};

static const char *INT_FIELDS[] = {
  "type", "status", "priority", "created_at", "updated_at",
  "resolved_at", "compacted_at",
  NULL
};

static int is_int_field(const char *field) {
  for (int i = 0; INT_FIELDS[i] != NULL; i++) {
    if (strcmp(field, INT_FIELDS[i]) == 0) { return 1; }
  }
  return 0;
}

static int is_double_field(const char *field) {
  (void)field;
  /* DOUBLE_FIELDS is currently empty (no double columns).
     Return 0 directly to avoid clang-analyzer array-bound warning
     on the NULL-only sentinel array. Re-add the loop if double
     fields are introduced in the future. */
  return 0;
}

/* ---- Meta field helpers ---- */

static int is_meta_field(const char *field) {
  return (strncmp(field, "meta.", 5) == 0 && field[5] != '\0');
}

/* Extract key from "meta.key" -> "key". Returns pointer into field. */
static const char *meta_key(const char *field) {
  return field + 5;
}

/* Check if a string looks like a number (integer or decimal). */
static int looks_numeric(const char *s) {
  if (*s == '-') { s++; }
  if (*s == '\0') { return 0; }
  int has_digit = 0;
  int has_dot = 0;
  while (*s != '\0') {
    if (*s >= '0' && *s <= '9') { has_digit = 1; }
    else if (*s == '.' && !has_dot) { has_dot = 1; }
    else { return 0; }
    s++;
  }
  return has_digit;
}

/* Meta join tracking: unique meta keys and their aliases (m0, m1, ...) */
typedef struct {
  char keys[TQL_MAX_META_JOINS][TQL_MAX_FIELD_LEN];
  u32 count;
} meta_joins_t;

/* Find or register a meta key. Returns the join index (0..count-1),
   or -1 if the limit is exceeded. */
static int meta_join_index(meta_joins_t *mj, const char *key) {
  for (u32 i = 0; i < mj->count; i++) {
    if (strcmp(mj->keys[i], key) == 0) { return (int)i; }
  }
  if (mj->count >= TQL_MAX_META_JOINS) { return -1; }
  snprintf(mj->keys[mj->count], TQL_MAX_FIELD_LEN, "%s", key);
  mj->count++;
  return (int)(mj->count - 1);
}

static int translate_enum(const char *field, const char *value, int *out) {
  const tql_compile_enum_t *map = NULL;

  if (strcmp(field, "status") == 0) { map = STATUS_MAP; }
  else if (strcmp(field, "type") == 0) { map = TYPE_MAP; }
  else if (strcmp(field, "priority") == 0) { map = PRIORITY_MAP; }
  else { return 0; }

  for (int i = 0; map[i].name != NULL; i++) {
    if (strcmp(value, map[i].name) == 0) {
      *out = map[i].value;
      return 1;
    }
  }
  return 0;
}

/* ---- Meta column expression helpers ---- */

/* Emit a meta column expression for SELECT or GROUP BY.
   Uses COALESCE to return either the text or numeric value as text. */
static int emit_meta_select(char *p, char *end, int join_idx) {
  return snprintf(p, (sz)(end - p),
    "COALESCE(m%d.value_text, CAST(m%d.value_num AS TEXT))",
    join_idx, join_idx);
}

/* Emit a meta column for a numeric context (SUM, AVG, sort, numeric filter). */
static int emit_meta_num(char *p, char *end, int join_idx) {
  return snprintf(p, (sz)(end - p), "m%d.value_num", join_idx);
}

/* Collect all meta keys used in the pipeline and register them. */
static void collect_meta_keys(const tql_pipeline_t *p, meta_joins_t *mj) {
  mj->count = 0;
  /* filters */
  for (u32 i = 0; i < p->filter_count; i++) {
    if (is_meta_field(p->filters[i].field)) {
      meta_join_index(mj, meta_key(p->filters[i].field));
    }
  }
  /* selects */
  for (u32 i = 0; i < p->select_count; i++) {
    if (is_meta_field(p->selects[i])) {
      meta_join_index(mj, meta_key(p->selects[i]));
    }
  }
  /* group by */
  if (p->has_group && is_meta_field(p->group_by)) {
    meta_join_index(mj, meta_key(p->group_by));
  }
  /* sorts */
  for (u32 i = 0; i < p->sort_count; i++) {
    if (is_meta_field(p->sorts[i].field)) {
      meta_join_index(mj, meta_key(p->sorts[i].field));
    }
  }
  /* aggregates */
  for (u32 i = 0; i < p->agg_count; i++) {
    if (is_meta_field(p->aggregates[i].field)) {
      meta_join_index(mj, meta_key(p->aggregates[i].field));
    }
  }
}

/* ---- Compiler helpers ---- */

static void convert_like_pattern(const char *src, char *dst, sz dst_len) {
  sz j = 0;
  for (sz i = 0; src[i] != '\0' && j < dst_len - 1; i++) {
    if (src[i] == '*') {
      dst[j++] = '%';
    } else if (src[i] == '?') {
      dst[j++] = '_';
    } else {
      dst[j++] = src[i];
    }
  }
  dst[j] = '\0';
}

static const char *op_to_sql(tql_op_e op) {
  switch (op) {
    case TQL_OP_EQ:          return "=";
    case TQL_OP_NE:          return "!=";
    case TQL_OP_GT:          return ">";
    case TQL_OP_LT:          return "<";
    case TQL_OP_GE:          return ">=";
    case TQL_OP_LE:          return "<=";
    case TQL_OP_LIKE:        return "LIKE";
    case TQL_OP_IS_NULL:     return "IS NULL";
    case TQL_OP_IS_NOT_NULL: return "IS NOT NULL";
    case TQL_OP_IN:          return "IN";
    case TQL_OP_NOT_IN:      return "NOT IN";
  }
  return "=";
}

static const char *agg_to_sql(tql_agg_e func) {
  switch (func) {
    case TQL_AGG_COUNT:          return "COUNT";
    case TQL_AGG_SUM:            return "SUM";
    case TQL_AGG_AVG:            return "AVG";
    case TQL_AGG_MIN:            return "MIN";
    case TQL_AGG_MAX:            return "MAX";
    case TQL_AGG_COUNT_DISTINCT: return "COUNT";
  }
  return "COUNT";
}

/* ---- Bind a single filter value ---- */

static void bind_value(tql_compiled_t *out, const char *field,
                       const char *value) {
  int enum_val;
  if (translate_enum(field, value, &enum_val)) {
    out->binds[out->bind_count].is_int = 1;
    out->binds[out->bind_count].ival = (i64)enum_val;
  } else if (is_int_field(field)) {
    out->binds[out->bind_count].is_int = 1;
    out->binds[out->bind_count].ival = strtoll(value, NULL, 10);
  } else if (is_double_field(field)) {
    out->binds[out->bind_count].is_double = 1;
    out->binds[out->bind_count].dval = strtod(value, NULL);
  } else {
    out->binds[out->bind_count].is_int = 0;
    out->binds[out->bind_count].is_double = 0;
    snprintf(out->binds[out->bind_count].sval, TQL_MAX_VALUE_LEN,
             "%s", value);
  }
  out->bind_count++;
}

static void bind_string(tql_compiled_t *out, const char *value) {
  out->binds[out->bind_count].is_int = 0;
  out->binds[out->bind_count].is_double = 0;
  snprintf(out->binds[out->bind_count].sval, TQL_MAX_VALUE_LEN, "%s", value);
  out->bind_count++;
}

/* ---- Main compiler ---- */

tix_err_t tql_compile(const tql_pipeline_t *p, tql_compiled_t *out,
                      char *err_buf, sz err_len) {
  if (p == NULL || out == NULL) { return TIX_ERR_INVALID_ARG; }
  TIX_UNUSED(err_buf);
  TIX_UNUSED(err_len);
  memset(out, 0, sizeof(*out));

  char *sql = out->sql;
  char *end = sql + sizeof(out->sql);
  int need_label_join = 0;
  meta_joins_t mj;
  collect_meta_keys(p, &mj);

  /* Check if any filter references "label" (non-negated) */
  for (u32 i = 0; i < p->filter_count; i++) {
    if (strcmp(p->filters[i].field, "label") == 0 && !p->filters[i].negated) {
      need_label_join = 1;
      break;
    }
  }

  /* Also check group by on label */
  if (p->has_group && strcmp(p->group_by, "label") == 0) {
    need_label_join = 1;
  }

  /* SELECT clause */
  if (p->has_distinct) {
    TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "SELECT DISTINCT ");
  } else {
    TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "SELECT ");
  }

  if (p->agg_count > 0 || p->has_group) {
    out->is_aggregate = 1;
    int first = 1;

    /* Group-by column first */
    if (p->has_group) {
      if (strcmp(p->group_by, "label") == 0) {
        TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "tl.label");
      } else if (is_meta_field(p->group_by)) {
        int mi = meta_join_index(&mj, meta_key(p->group_by));
        {
          int mn = emit_meta_select(sql, end, mi);
          if (mn < 0 || sql + mn >= end) { return TIX_ERR_OVERFLOW; }
          sql += mn;
        }
      } else {
        TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "t.%s", p->group_by);
      }
      snprintf(out->columns[out->column_count], TQL_MAX_FIELD_LEN,
               "%s", p->group_by);
      out->column_count++;
      first = 0;
    }

    /* Aggregate expressions */
    for (u32 i = 0; i < p->agg_count; i++) {
      if (!first) { TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, ", "); }
      first = 0;

      if (p->aggregates[i].field[0] == '\0') {
        TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "COUNT(*)");
        snprintf(out->columns[out->column_count], TQL_MAX_FIELD_LEN,
                 "count");
      } else if (p->aggregates[i].func == TQL_AGG_COUNT_DISTINCT) {
        if (is_meta_field(p->aggregates[i].field)) {
          int mi = meta_join_index(&mj, meta_key(p->aggregates[i].field));
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "COUNT(DISTINCT ");
          {
            int mn = emit_meta_select(sql, end, mi);
            if (mn < 0 || sql + mn >= end) { return TIX_ERR_OVERFLOW; }
            sql += mn;
          }
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, ")");
        } else {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "COUNT(DISTINCT t.%s)", p->aggregates[i].field);
        }
        int cn = snprintf(out->columns[out->column_count],
                          TQL_MAX_FIELD_LEN, "count_distinct_%.50s",
                          p->aggregates[i].field);
        if (cn < 0 || cn >= TQL_MAX_FIELD_LEN) {
          out->columns[out->column_count][TQL_MAX_FIELD_LEN - 1] = '\0';
        }
      } else {
        const char *func = agg_to_sql(p->aggregates[i].func);
        if (is_meta_field(p->aggregates[i].field)) {
          int mi = meta_join_index(&mj, meta_key(p->aggregates[i].field));
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "%s(", func);
          {
            int mn = emit_meta_num(sql, end, mi);
            if (mn < 0 || sql + mn >= end) { return TIX_ERR_OVERFLOW; }
            sql += mn;
          }
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, ")");
        } else {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s(t.%s)", func, p->aggregates[i].field);
        }
        const char *fn_lower = "count";
        switch (p->aggregates[i].func) {
          case TQL_AGG_COUNT:          fn_lower = "count"; break;
          case TQL_AGG_SUM:            fn_lower = "sum"; break;
          case TQL_AGG_AVG:            fn_lower = "avg"; break;
          case TQL_AGG_MIN:            fn_lower = "min"; break;
          case TQL_AGG_MAX:            fn_lower = "max"; break;
          case TQL_AGG_COUNT_DISTINCT: fn_lower = "count_distinct"; break;
        }
        int cn = snprintf(out->columns[out->column_count],
                          TQL_MAX_FIELD_LEN, "%s_%.50s",
                          fn_lower, p->aggregates[i].field);
        if (cn < 0 || cn >= TQL_MAX_FIELD_LEN) {
          out->columns[out->column_count][TQL_MAX_FIELD_LEN - 1] = '\0';
        }
      }
      out->column_count++;
    }
  } else if (p->select_count > 0) {
    for (u32 i = 0; i < p->select_count; i++) {
      if (i > 0) { TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, ", "); }
      if (strcmp(p->selects[i], "label") == 0) {
        TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "tl.label");
      } else if (is_meta_field(p->selects[i])) {
        int mi = meta_join_index(&mj, meta_key(p->selects[i]));
        {
          int mn = emit_meta_select(sql, end, mi);
          if (mn < 0 || sql + mn >= end) { return TIX_ERR_OVERFLOW; }
          sql += mn;
        }
      } else {
        TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "t.%s", p->selects[i]);
      }
      snprintf(out->columns[out->column_count], TQL_MAX_FIELD_LEN,
               "%s", p->selects[i]);
      out->column_count++;
    }
  } else {
    if (need_label_join) {
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "DISTINCT t.*");
    } else {
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "t.*");
    }
  }

  /* FROM clause */
  TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, " FROM tickets t");

  if (need_label_join) {
    int label_in_filter = 0;
    for (u32 i = 0; i < p->filter_count; i++) {
      if (strcmp(p->filters[i].field, "label") == 0 &&
          !p->filters[i].negated) {
        label_in_filter = 1;
        break;
      }
    }
    if (label_in_filter) {
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                      " INNER JOIN ticket_labels tl ON t.id = tl.ticket_id");
    } else {
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                      " LEFT JOIN ticket_labels tl ON t.id = tl.ticket_id");
    }
  }

  /* Meta LEFT JOINs: one per unique meta key */
  for (u32 mi = 0; mi < mj.count; mi++) {
    TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                    " LEFT JOIN ticket_meta m%u"
                    " ON t.id = m%u.ticket_id AND m%u.key = ?",
                    mi, mi, mi);
    bind_string(out, mj.keys[mi]);
  }

  /* WHERE clause */
  int has_where = 0;

  if (p->source != TQL_SOURCE_TICKETS) {
    TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, " WHERE t.type=?");
    has_where = 1;
    out->binds[out->bind_count].is_int = 1;
    out->binds[out->bind_count].ival = (i64)p->source;
    out->bind_count++;
  }

  /* Default: exclude resolved tickets unless 'all' modifier is set
     or user has an explicit status filter. */
  if (!p->has_all) {
    int has_status_filter = 0;
    for (u32 i = 0; i < p->filter_count; i++) {
      if (strcmp(p->filters[i].field, "status") == 0) {
        has_status_filter = 1;
        break;
      }
    }
    if (!has_status_filter) {
      const char *conj = has_where ? " AND" : " WHERE";
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                      "%s t.status < 2", conj);
      has_where = 1;
    }
  }

  /* User filters */
  for (u32 i = 0; i < p->filter_count; i++) {
    const tql_filter_t *f = &p->filters[i];
    const char *conj = has_where ? " AND" : " WHERE";
    int is_label = (strcmp(f->field, "label") == 0);
    int is_meta = is_meta_field(f->field);
    const char *cpfx = is_label ? "tl." : "t.";
    const char *cname = is_label ? "label" : f->field;

    /* Meta field filter: uses LEFT JOINed ticket_meta alias */
    if (is_meta) {
      int mi = meta_join_index(&mj, meta_key(f->field));
      if (f->op == TQL_OP_IS_NULL) {
        if (f->negated) {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s m%d.key IS NOT NULL", conj, mi);
        } else {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s m%d.key IS NULL", conj, mi);
        }
      } else if (f->op == TQL_OP_IS_NOT_NULL) {
        if (f->negated) {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s m%d.key IS NULL", conj, mi);
        } else {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s m%d.key IS NOT NULL", conj, mi);
        }
      } else if (f->op == TQL_OP_IN || f->op == TQL_OP_NOT_IN) {
        int use_num = (f->or_count > 0 && looks_numeric(f->or_values[0]));
        const char *col = use_num ? "value_num" : "value_text";
        const char *kw = (f->op == TQL_OP_IN) ? "IN" : "NOT IN";
        if (f->negated) {
          kw = (f->op == TQL_OP_IN) ? "NOT IN" : "IN";
        }
        TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                        "%s m%d.%s %s (", conj, mi, col, kw);
        for (u32 v = 0; v < f->or_count; v++) {
          if (v > 0) { TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, ","); }
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "?");
          if (use_num) {
            out->binds[out->bind_count].is_double = 1;
            out->binds[out->bind_count].dval = strtod(f->or_values[v], NULL);
            out->bind_count++;
          } else {
            bind_string(out, f->or_values[v]);
          }
        }
        TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, ")");
      } else if (f->op == TQL_OP_LIKE) {
        const char *kw = f->negated ? "NOT LIKE" : "LIKE";
        TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                        "%s m%d.value_text %s ?", conj, mi, kw);
        char pat[TQL_MAX_VALUE_LEN];
        convert_like_pattern(f->value, pat, sizeof(pat));
        bind_string(out, pat);
      } else {
        /* Standard comparison: numeric if value looks numeric */
        int use_num = looks_numeric(f->value);
        const char *op_str = op_to_sql(f->op);
        if (f->negated) {
          switch (f->op) {
            case TQL_OP_EQ: op_str = "!="; break;
            case TQL_OP_NE: op_str = "="; break;
            case TQL_OP_GT: op_str = "<="; break;
            case TQL_OP_LT: op_str = ">="; break;
            case TQL_OP_GE: op_str = "<"; break;
            case TQL_OP_LE: op_str = ">"; break;
            default: break;
          }
        }
        if (use_num) {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s m%d.value_num %s ?", conj, mi, op_str);
          out->binds[out->bind_count].is_double = 1;
          out->binds[out->bind_count].dval = strtod(f->value, NULL);
          out->bind_count++;
        } else {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s m%d.value_text %s ?", conj, mi, op_str);
          bind_string(out, f->value);
        }
      }
      has_where = 1;
      continue;
    }

    /* Negated label: NOT EXISTS subquery */
    if (is_label && f->negated) {
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                      "%s NOT EXISTS (SELECT 1 FROM ticket_labels nl "
                      "WHERE nl.ticket_id = t.id AND nl.label", conj);
      if (f->op == TQL_OP_LIKE) {
        TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, " LIKE ?)");
        char pat[TQL_MAX_VALUE_LEN];
        convert_like_pattern(f->value, pat, sizeof(pat));
        bind_string(out, pat);
      } else {
        TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, " = ?)");
        bind_string(out, f->value);
      }
      has_where = 1;
      continue;
    }

    /* IS NULL / IS NOT NULL.
       For string fields, tix stores empty strings as '' not NULL,
       so we check both (IS NULL OR = '') for "unset" semantics.
       For numeric fields, we check (IS NULL OR = 0). */
    if (f->op == TQL_OP_IS_NULL) {
      if (f->negated) {
        /* Negated IS NULL = IS NOT NULL */
        if (is_int_field(cname) || is_double_field(cname)) {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s (%s%s IS NOT NULL AND %s%s != 0)",
                          conj, cpfx, cname, cpfx, cname);
        } else {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s (%s%s IS NOT NULL AND %s%s != '')",
                          conj, cpfx, cname, cpfx, cname);
        }
      } else {
        if (is_int_field(cname) || is_double_field(cname)) {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s (%s%s IS NULL OR %s%s = 0)",
                          conj, cpfx, cname, cpfx, cname);
        } else {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s (%s%s IS NULL OR %s%s = '')",
                          conj, cpfx, cname, cpfx, cname);
        }
      }
      has_where = 1;
      continue;
    }
    if (f->op == TQL_OP_IS_NOT_NULL) {
      if (f->negated) {
        /* Negated IS NOT NULL = IS NULL */
        if (is_int_field(cname) || is_double_field(cname)) {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s (%s%s IS NULL OR %s%s = 0)",
                          conj, cpfx, cname, cpfx, cname);
        } else {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s (%s%s IS NULL OR %s%s = '')",
                          conj, cpfx, cname, cpfx, cname);
        }
      } else {
        if (is_int_field(cname) || is_double_field(cname)) {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s (%s%s IS NOT NULL AND %s%s != 0)",
                          conj, cpfx, cname, cpfx, cname);
        } else {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                          "%s (%s%s IS NOT NULL AND %s%s != '')",
                          conj, cpfx, cname, cpfx, cname);
        }
      }
      has_where = 1;
      continue;
    }

    /* IN / NOT IN */
    if (f->op == TQL_OP_IN || f->op == TQL_OP_NOT_IN) {
      const char *kw = (f->op == TQL_OP_IN) ? "IN" : "NOT IN";
      if (f->negated) {
        kw = (f->op == TQL_OP_IN) ? "NOT IN" : "IN";
      }
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                      "%s %s%s %s (", conj, cpfx, cname, kw);
      for (u32 v = 0; v < f->or_count; v++) {
        if (v > 0) { TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, ","); }
        TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "?");
        bind_value(out, f->field, f->or_values[v]);
      }
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, ")");
      has_where = 1;
      continue;
    }

    /* LIKE filter */
    if (f->op == TQL_OP_LIKE) {
      const char *kw = f->negated ? "NOT LIKE" : "LIKE";
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                      "%s %s%s %s ?", conj, cpfx, cname, kw);
      char pat[TQL_MAX_VALUE_LEN];
      convert_like_pattern(f->value, pat, sizeof(pat));
      bind_string(out, pat);
      has_where = 1;
      continue;
    }

    /* Standard comparison */
    {
      const char *op_str = op_to_sql(f->op);
      if (f->negated) {
        switch (f->op) {
          case TQL_OP_EQ: op_str = "!="; break;
          case TQL_OP_NE: op_str = "="; break;
          case TQL_OP_GT: op_str = "<="; break;
          case TQL_OP_LT: op_str = ">="; break;
          case TQL_OP_GE: op_str = "<"; break;
          case TQL_OP_LE: op_str = ">"; break;
          default: break;
        }
      }
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                      "%s %s%s %s ?", conj, cpfx, cname, op_str);
      bind_value(out, f->field, f->value);
    }
    has_where = 1;
  }

  /* GROUP BY */
  if (p->has_group) {
    if (strcmp(p->group_by, "label") == 0) {
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, " GROUP BY tl.label");
    } else if (is_meta_field(p->group_by)) {
      int mi = meta_join_index(&mj, meta_key(p->group_by));
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, " GROUP BY ");
      {
        int mn = emit_meta_select(sql, end, mi);
        if (mn < 0 || sql + mn >= end) { return TIX_ERR_OVERFLOW; }
        sql += mn;
      }
    } else {
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, " GROUP BY t.%s",
                      p->group_by);
    }
  }

  /* HAVING: map column aliases back to aggregate expressions.
     SQLite does not support ordinal references in HAVING, so we must
     repeat the aggregate expression (e.g., HAVING COUNT(*) >= ?). */
  for (u32 i = 0; i < p->having_count; i++) {
    const tql_having_t *h = &p->havings[i];
    const char *hconj = (i == 0) ? " HAVING" : " AND";

    /* Find matching aggregate and emit its SQL expression */
    int found = 0;

    /* Check "count" alias -> COUNT(*) */
    if (strcmp(h->column, "count") == 0) {
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                      "%s COUNT(*) %s ?", hconj, op_to_sql(h->op));
      found = 1;
    }

    /* Check aggregate aliases: sum_field, avg_field, etc. */
    if (!found) {
      for (u32 a = 0; a < p->agg_count && !found; a++) {
        if (p->aggregates[a].field[0] == '\0') { continue; }

        /* Build expected alias name and compare */
        char alias[TQL_MAX_FIELD_LEN];
        const char *prefix = "count";
        switch (p->aggregates[a].func) {
          case TQL_AGG_COUNT:          prefix = "count"; break;
          case TQL_AGG_SUM:            prefix = "sum"; break;
          case TQL_AGG_AVG:            prefix = "avg"; break;
          case TQL_AGG_MIN:            prefix = "min"; break;
          case TQL_AGG_MAX:            prefix = "max"; break;
          case TQL_AGG_COUNT_DISTINCT: prefix = "count_distinct"; break;
        }
        int alen = snprintf(alias, sizeof(alias), "%s_%.40s",
                           prefix, p->aggregates[a].field);
        if (alen < 0 || (sz)alen >= sizeof(alias)) {
          alias[sizeof(alias) - 1] = '\0';
        }

        if (strcmp(h->column, alias) == 0) {
          const char *func = agg_to_sql(p->aggregates[a].func);
          if (is_meta_field(p->aggregates[a].field)) {
            int mi = meta_join_index(&mj, meta_key(p->aggregates[a].field));
            if (p->aggregates[a].func == TQL_AGG_COUNT_DISTINCT) {
              TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                              "%s COUNT(DISTINCT m%d.value_num) %s ?",
                              hconj, mi, op_to_sql(h->op));
            } else {
              TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                              "%s %s(m%d.value_num) %s ?",
                              hconj, func, mi, op_to_sql(h->op));
            }
          } else if (p->aggregates[a].func == TQL_AGG_COUNT_DISTINCT) {
            TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                            "%s COUNT(DISTINCT t.%s) %s ?",
                            hconj, p->aggregates[a].field,
                            op_to_sql(h->op));
          } else {
            TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                            "%s %s(t.%s) %s ?",
                            hconj, func, p->aggregates[a].field,
                            op_to_sql(h->op));
          }
          found = 1;
        }
      }
    }

    /* Fallback: use column name as-is (raw expression) */
    if (!found) {
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                      "%s %s %s ?", hconj, h->column, op_to_sql(h->op));
    }

    /* Bind having value (detect int vs float) */
    int is_int_val = 1;
    for (const char *vp = h->value; *vp != '\0'; vp++) {
      if (*vp != '-' && (*vp < '0' || *vp > '9')) {
        is_int_val = 0;
        break;
      }
    }
    if (is_int_val) {
      out->binds[out->bind_count].is_int = 1;
      out->binds[out->bind_count].ival = strtoll(h->value, NULL, 10);
    } else {
      out->binds[out->bind_count].is_double = 1;
      out->binds[out->bind_count].dval = strtod(h->value, NULL);
    }
    out->bind_count++;
  }

  /* ORDER BY */
  if (p->sort_count > 0) {
    TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, " ORDER BY ");
    for (u32 i = 0; i < p->sort_count; i++) {
      if (i > 0) { TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, ", "); }
      const char *dir = (p->sorts[i].dir == TQL_SORT_DESC) ? "DESC" : "ASC";

      int is_agg_alias = 0;
      for (u32 c = 0; c < out->column_count; c++) {
        if (strcmp(p->sorts[i].field, out->columns[c]) == 0 &&
            out->is_aggregate) {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "%u %s", c + 1, dir);
          is_agg_alias = 1;
          break;
        }
      }
      if (!is_agg_alias) {
        if (strcmp(p->sorts[i].field, "label") == 0) {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "tl.label %s", dir);
        } else if (is_meta_field(p->sorts[i].field)) {
          int mi = meta_join_index(&mj, meta_key(p->sorts[i].field));
          {
            int mn = emit_meta_num(sql, end, mi);
            if (mn < 0 || sql + mn >= end) { return TIX_ERR_OVERFLOW; }
            sql += mn;
          }
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, " %s", dir);
        } else {
          TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, "t.%s %s",
                          p->sorts[i].field, dir);
        }
      }
    }
  } else if (!p->has_group && p->agg_count == 0) {
    TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW,
                    " ORDER BY t.priority DESC, t.created_at ASC");
  }

  /* LIMIT */
  if (p->has_limit) {
    TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, " LIMIT %u", p->limit);
  }

  /* OFFSET */
  if (p->has_offset) {
    if (!p->has_limit) {
      TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, " LIMIT -1");
    }
    TIX_BUF_PRINTF(sql, end, TIX_ERR_OVERFLOW, " OFFSET %u", p->offset);
  }

  return TIX_OK;
}

/* ---- Convenience ---- */

tix_err_t tql_prepare(const char *query, tql_compiled_t *out,
                      char *err_buf, sz err_len) {
  tql_pipeline_t pipeline;
  tix_err_t err = tql_parse(query, &pipeline, err_buf, err_len);
  if (err != TIX_OK) { return err; }
  return tql_compile(&pipeline, out, err_buf, err_len);
}
