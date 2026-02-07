/*
 * TQL - Tix Query Language
 *
 * Single-pass tokenizer + iterative parser + SQL compiler.
 * No dynamic allocation; all state on the stack.
 *
 * Pipeline syntax:
 *   source | filter filter ... | stage | stage ...
 *
 * The parser splits on '|', then parses each segment:
 *   - First segment: source keyword (tasks/issues/notes/tickets)
 *     optionally followed by inline filters
 *   - Subsequent segments: filters, select, group, count/sum/avg/min/max,
 *     sort, limit
 */

#include "tql.h"
#include "log.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Valid ticket column names (for validation) */
static const char *VALID_COLUMNS[] = {
  "id", "type", "status", "priority", "name", "spec", "notes", "accept",
  "done_at", "branch", "parent", "created_from", "supersedes",
  "kill_reason", "created_from_name", "supersedes_name",
  "supersedes_reason", "created_at", "updated_at", "author",
  "completed_at", "cost", "tokens_in", "tokens_out", "iterations",
  "model", "retries", "kill_count", "commit_hash",
  NULL
};

static int is_valid_column(const char *field) {
  /* Special pseudo-columns */
  if (strcmp(field, "label") == 0) { return 1; }
  for (int i = 0; VALID_COLUMNS[i] != NULL; i++) {
    if (strcmp(field, VALID_COLUMNS[i]) == 0) { return 1; }
  }
  return 0;
}

/* ---- String helpers ---- */

static void skip_ws(const char **p) {
  while (**p != '\0' && isspace((unsigned char)**p)) { (*p)++; }
}

/* Read a word (alphanumeric + underscore) into buf.
   Returns number of chars read. */
static int read_word(const char *p, char *buf, sz buf_len) {
  sz i = 0;
  while (p[i] != '\0' && (isalnum((unsigned char)p[i]) || p[i] == '_') &&
         i < buf_len - 1) {
    buf[i] = p[i];
    i++;
  }
  buf[i] = '\0';
  return (int)i;
}

/* Read a value token: everything up to whitespace or pipe or end.
   Handles quoted strings: "value with spaces" */
static int read_value(const char *p, char *buf, sz buf_len) {
  sz i = 0;

  if (*p == '"') {
    /* quoted string */
    p++;
    while (p[i] != '\0' && p[i] != '"' && i < buf_len - 1) {
      buf[i] = p[i];
      i++;
    }
    buf[i] = '\0';
    /* +2 for opening and closing quote */
    return (int)(p[i] == '"' ? i + 2 : i + 1);
  }

  /* unquoted: read until space, pipe, or end */
  while (p[i] != '\0' && p[i] != ' ' && p[i] != '\t' && p[i] != '|' &&
         i < buf_len - 1) {
    buf[i] = p[i];
    i++;
  }
  buf[i] = '\0';
  return (int)i;
}

/* ---- Pipeline init ---- */

void tql_pipeline_init(tql_pipeline_t *p) {
  memset(p, 0, sizeof(*p));
}

/* ---- Parser ---- */

/* Split a comma-separated value string into or_values array.
   Returns the number of values parsed. */
static u32 split_or_values(const char *value, char out[][TQL_MAX_VALUE_LEN],
                           u32 max_count) {
  u32 count = 0;
  const char *p = value;

  while (*p != '\0' && count < max_count) {
    sz i = 0;
    while (p[i] != '\0' && p[i] != ',' && i < TQL_MAX_VALUE_LEN - 1) {
      out[count][i] = p[i];
      i++;
    }
    out[count][i] = '\0';
    count++;
    p += i;
    if (*p == ',') { p++; }
  }
  return count;
}

/* Check if a value string contains commas (OR logic) */
static int has_comma(const char *value) {
  for (const char *p = value; *p != '\0'; p++) {
    if (*p == ',') { return 1; }
  }
  return 0;
}

/* Parse a single filter expression: [!]field[op]value
   Operators: =, !=, >, <, >=, <=, ~
   Negation prefix: !field=val
   Empty value: field= -> IS NULL, field!= -> IS NOT NULL
   Comma values: field=a,b,c -> IN (a,b,c) */
static tix_err_t parse_filter(const char *token, tql_filter_t *f,
                              char *err_buf, sz err_len) {
  const char *p = token;
  memset(f, 0, sizeof(*f));

  /* Check for negation prefix */
  if (*p == '!') {
    f->negated = 1;
    p++;
  }

  char field[TQL_MAX_FIELD_LEN];
  int n = read_word(p, field, sizeof(field));
  if (n == 0) {
    snprintf(err_buf, err_len, "empty field name in filter");
    return TIX_ERR_PARSE;
  }
  p += n;

  snprintf(f->field, sizeof(f->field), "%s", field);

  /* parse operator */
  if (p[0] == '!' && p[1] == '=') {
    f->op = TQL_OP_NE;
    p += 2;
  } else if (p[0] == '>' && p[1] == '=') {
    f->op = TQL_OP_GE;
    p += 2;
  } else if (p[0] == '<' && p[1] == '=') {
    f->op = TQL_OP_LE;
    p += 2;
  } else if (p[0] == '=') {
    f->op = TQL_OP_EQ;
    p += 1;
  } else if (p[0] == '>') {
    f->op = TQL_OP_GT;
    p += 1;
  } else if (p[0] == '<') {
    f->op = TQL_OP_LT;
    p += 1;
  } else if (p[0] == '~') {
    f->op = TQL_OP_LIKE;
    p += 1;
  } else {
    snprintf(err_buf, err_len, "invalid operator after '%s'", field);
    return TIX_ERR_PARSE;
  }

  /* parse value */
  n = read_value(p, f->value, sizeof(f->value));

  /* Handle empty value: IS NULL / IS NOT NULL */
  if (n == 0 || f->value[0] == '\0') {
    if (f->op == TQL_OP_EQ) {
      f->op = TQL_OP_IS_NULL;
    } else if (f->op == TQL_OP_NE) {
      f->op = TQL_OP_IS_NOT_NULL;
    } else {
      snprintf(err_buf, err_len, "empty value for field '%s'", field);
      return TIX_ERR_PARSE;
    }
  }

  /* Handle comma-separated OR values */
  if (f->op == TQL_OP_EQ && has_comma(f->value)) {
    f->op = TQL_OP_IN;
    f->or_count = split_or_values(f->value, f->or_values, TQL_MAX_OR_VALUES);
  } else if (f->op == TQL_OP_NE && has_comma(f->value)) {
    f->op = TQL_OP_NOT_IN;
    f->or_count = split_or_values(f->value, f->or_values, TQL_MAX_OR_VALUES);
  }

  if (!is_valid_column(f->field)) {
    snprintf(err_buf, err_len, "unknown field: '%s'", f->field);
    return TIX_ERR_PARSE;
  }

  return TIX_OK;
}

/* Check if a token looks like a filter (contains an operator char) */
static int is_filter_token(const char *token) {
  /* skip leading negation prefix */
  if (*token == '!') { token++; }
  /* skip leading word chars */
  while (*token != '\0' && (isalnum((unsigned char)*token) || *token == '_')) {
    token++;
  }
  return (*token == '=' || *token == '!' || *token == '>' ||
          *token == '<' || *token == '~');
}

/* Parse a pipe segment (the text between | characters).
   Modifies the pipeline in-place. */
static tix_err_t parse_segment(const char *seg, tql_pipeline_t *p,
                               int seg_idx, char *err_buf, sz err_len) {
  const char *cursor = seg;
  skip_ws(&cursor);

  if (*cursor == '\0') { return TIX_OK; }

  /* First segment: expect source keyword */
  if (seg_idx == 0) {
    char word[TQL_MAX_FIELD_LEN];
    int n = read_word(cursor, word, sizeof(word));
    if (n == 0) {
      snprintf(err_buf, err_len, "expected source (tasks|issues|notes|tickets)");
      return TIX_ERR_PARSE;
    }

    if (strcmp(word, "tasks") == 0) {
      p->source = TQL_SOURCE_TASKS;
      p->has_source = 1;
    } else if (strcmp(word, "issues") == 0) {
      p->source = TQL_SOURCE_ISSUES;
      p->has_source = 1;
    } else if (strcmp(word, "notes") == 0) {
      p->source = TQL_SOURCE_NOTES;
      p->has_source = 1;
    } else if (strcmp(word, "tickets") == 0) {
      p->source = TQL_SOURCE_TICKETS;
      p->has_source = 1;
    } else {
      snprintf(err_buf, err_len,
               "unknown source '%s' (expected tasks|issues|notes|tickets)",
               word);
      return TIX_ERR_PARSE;
    }
    cursor += n;
    skip_ws(&cursor);

    /* Source segment may have inline filters after the keyword */
    while (*cursor != '\0') {
      if (is_filter_token(cursor)) {
        if (p->filter_count >= TQL_MAX_FILTERS) {
          snprintf(err_buf, err_len, "too many filters (max %d)",
                   TQL_MAX_FILTERS);
          return TIX_ERR_PARSE;
        }
        tix_err_t err = parse_filter(cursor,
                                     &p->filters[p->filter_count],
                                     err_buf, err_len);
        if (err != TIX_OK) { return err; }
        p->filter_count++;

        /* advance cursor past the filter token */
        while (*cursor != '\0' && *cursor != ' ' && *cursor != '\t') {
          if (*cursor == '"') {
            cursor++;
            while (*cursor != '\0' && *cursor != '"') { cursor++; }
            if (*cursor == '"') { cursor++; }
          } else {
            cursor++;
          }
        }
        skip_ws(&cursor);
      } else {
        snprintf(err_buf, err_len,
                 "unexpected token in source segment: '%s'", cursor);
        return TIX_ERR_PARSE;
      }
    }
    return TIX_OK;
  }

  /* Subsequent segments: filters, select, group, aggregate, sort, limit */
  char word[TQL_MAX_FIELD_LEN];
  int n = read_word(cursor, word, sizeof(word));

  /* select f1,f2,f3 */
  if (strcmp(word, "select") == 0) {
    cursor += n;
    skip_ws(&cursor);
    while (*cursor != '\0' && p->select_count < TQL_MAX_SELECT) {
      char fname[TQL_MAX_FIELD_LEN];
      int fn = read_word(cursor, fname, sizeof(fname));
      if (fn == 0) { break; }
      snprintf(p->selects[p->select_count], TQL_MAX_FIELD_LEN, "%s", fname);
      p->select_count++;
      cursor += fn;
      if (*cursor == ',') { cursor++; }
      skip_ws(&cursor);
    }
    return TIX_OK;
  }

  /* group field */
  if (strcmp(word, "group") == 0) {
    cursor += n;
    skip_ws(&cursor);
    n = read_word(cursor, p->group_by, sizeof(p->group_by));
    if (n == 0) {
      snprintf(err_buf, err_len, "group requires a field name");
      return TIX_ERR_PARSE;
    }
    p->has_group = 1;
    return TIX_OK;
  }

  /* distinct */
  if (strcmp(word, "distinct") == 0) {
    p->has_distinct = 1;
    return TIX_OK;
  }

  /* having col>N (post-aggregate filter) */
  if (strcmp(word, "having") == 0) {
    cursor += n;
    skip_ws(&cursor);

    while (*cursor != '\0') {
      if (p->having_count >= TQL_MAX_HAVINGS) {
        snprintf(err_buf, err_len, "too many HAVING filters (max %d)",
                 TQL_MAX_HAVINGS);
        return TIX_ERR_PARSE;
      }

      tql_having_t *h = &p->havings[p->having_count];
      char hfield[TQL_MAX_FIELD_LEN];
      int fn = read_word(cursor, hfield, sizeof(hfield));
      if (fn == 0) { break; }
      cursor += fn;

      snprintf(h->column, sizeof(h->column), "%s", hfield);

      /* parse operator */
      if (cursor[0] == '!' && cursor[1] == '=') {
        h->op = TQL_OP_NE; cursor += 2;
      } else if (cursor[0] == '>' && cursor[1] == '=') {
        h->op = TQL_OP_GE; cursor += 2;
      } else if (cursor[0] == '<' && cursor[1] == '=') {
        h->op = TQL_OP_LE; cursor += 2;
      } else if (cursor[0] == '=') {
        h->op = TQL_OP_EQ; cursor += 1;
      } else if (cursor[0] == '>') {
        h->op = TQL_OP_GT; cursor += 1;
      } else if (cursor[0] == '<') {
        h->op = TQL_OP_LT; cursor += 1;
      } else {
        snprintf(err_buf, err_len,
                 "invalid operator in HAVING after '%s'", hfield);
        return TIX_ERR_PARSE;
      }

      fn = read_value(cursor, h->value, sizeof(h->value));
      if (fn == 0) {
        snprintf(err_buf, err_len, "empty value in HAVING for '%s'", hfield);
        return TIX_ERR_PARSE;
      }
      cursor += fn;
      p->having_count++;
      skip_ws(&cursor);
    }
    return TIX_OK;
  }

  /* offset N */
  if (strcmp(word, "offset") == 0) {
    cursor += n;
    skip_ws(&cursor);
    char num[32];
    int nn = read_word(cursor, num, sizeof(num));
    if (nn == 0) {
      snprintf(err_buf, err_len, "offset requires a number");
      return TIX_ERR_PARSE;
    }
    long val = strtol(num, NULL, 10);
    if (val < 0) {
      snprintf(err_buf, err_len, "offset must be a non-negative number");
      return TIX_ERR_PARSE;
    }
    p->offset = (u32)val;
    p->has_offset = 1;
    return TIX_OK;
  }

  /* count */
  if (strcmp(word, "count") == 0) {
    if (p->agg_count >= TQL_MAX_AGGREGATES) {
      snprintf(err_buf, err_len, "too many aggregates");
      return TIX_ERR_PARSE;
    }
    p->aggregates[p->agg_count].func = TQL_AGG_COUNT;
    p->aggregates[p->agg_count].field[0] = '\0';
    p->agg_count++;
    return TIX_OK;
  }

  /* count_distinct field */
  if (strcmp(word, "count_distinct") == 0) {
    if (p->agg_count >= TQL_MAX_AGGREGATES) {
      snprintf(err_buf, err_len, "too many aggregates");
      return TIX_ERR_PARSE;
    }
    cursor += n;
    skip_ws(&cursor);
    char fname[TQL_MAX_FIELD_LEN];
    int fn = read_word(cursor, fname, sizeof(fname));
    if (fn == 0) {
      snprintf(err_buf, err_len, "count_distinct requires a field name");
      return TIX_ERR_PARSE;
    }
    p->aggregates[p->agg_count].func = TQL_AGG_COUNT_DISTINCT;
    snprintf(p->aggregates[p->agg_count].field, TQL_MAX_FIELD_LEN,
             "%s", fname);
    p->agg_count++;
    return TIX_OK;
  }

  /* sum/avg/min/max field */
  if (strcmp(word, "sum") == 0 || strcmp(word, "avg") == 0 ||
      strcmp(word, "min") == 0 || strcmp(word, "max") == 0) {
    if (p->agg_count >= TQL_MAX_AGGREGATES) {
      snprintf(err_buf, err_len, "too many aggregates");
      return TIX_ERR_PARSE;
    }
    tql_agg_e func = TQL_AGG_SUM;
    if (strcmp(word, "avg") == 0) { func = TQL_AGG_AVG; }
    else if (strcmp(word, "min") == 0) { func = TQL_AGG_MIN; }
    else if (strcmp(word, "max") == 0) { func = TQL_AGG_MAX; }

    cursor += n;
    skip_ws(&cursor);
    char fname[TQL_MAX_FIELD_LEN];
    int fn = read_word(cursor, fname, sizeof(fname));
    if (fn == 0) {
      snprintf(err_buf, err_len, "%s requires a field name", word);
      return TIX_ERR_PARSE;
    }
    p->aggregates[p->agg_count].func = func;
    snprintf(p->aggregates[p->agg_count].field, TQL_MAX_FIELD_LEN,
             "%s", fname);
    p->agg_count++;
    return TIX_OK;
  }

  /* sort field [asc|desc] */
  if (strcmp(word, "sort") == 0) {
    cursor += n;
    skip_ws(&cursor);

    while (*cursor != '\0' && p->sort_count < TQL_MAX_SORTS) {
      char fname[TQL_MAX_FIELD_LEN];
      int fn = read_word(cursor, fname, sizeof(fname));
      if (fn == 0) { break; }
      cursor += fn;
      skip_ws(&cursor);

      tql_sort_dir_e dir = TQL_SORT_ASC;
      char dirword[16];
      int dn = read_word(cursor, dirword, sizeof(dirword));
      if (dn > 0) {
        if (strcmp(dirword, "desc") == 0) {
          dir = TQL_SORT_DESC;
          cursor += dn;
          skip_ws(&cursor);
        } else if (strcmp(dirword, "asc") == 0) {
          dir = TQL_SORT_ASC;
          cursor += dn;
          skip_ws(&cursor);
        }
        /* else: it's the next sort field, don't advance */
      }

      snprintf(p->sorts[p->sort_count].field, TQL_MAX_FIELD_LEN, "%s", fname);
      p->sorts[p->sort_count].dir = dir;
      p->sort_count++;

      if (*cursor == ',') { cursor++; skip_ws(&cursor); }
    }
    return TIX_OK;
  }

  /* limit N */
  if (strcmp(word, "limit") == 0) {
    cursor += n;
    skip_ws(&cursor);
    char num[32];
    int nn = read_word(cursor, num, sizeof(num));
    if (nn == 0) {
      snprintf(err_buf, err_len, "limit requires a number");
      return TIX_ERR_PARSE;
    }
    long val = strtol(num, NULL, 10);
    if (val <= 0) {
      snprintf(err_buf, err_len, "limit must be a positive number");
      return TIX_ERR_PARSE;
    }
    p->limit = (u32)val;
    p->has_limit = 1;
    return TIX_OK;
  }

  /* If the whole segment is filters (no keyword prefix) */
  if (n > 0 && is_filter_token(cursor)) {
    /* Parse as filter segment: multiple space-separated filters */
    while (*cursor != '\0') {
      skip_ws(&cursor);
      if (*cursor == '\0') { break; }

      if (!is_filter_token(cursor)) {
        snprintf(err_buf, err_len, "unexpected token: '%s'", cursor);
        return TIX_ERR_PARSE;
      }

      if (p->filter_count >= TQL_MAX_FILTERS) {
        snprintf(err_buf, err_len, "too many filters (max %d)",
                 TQL_MAX_FILTERS);
        return TIX_ERR_PARSE;
      }

      tix_err_t err = parse_filter(cursor,
                                   &p->filters[p->filter_count],
                                   err_buf, err_len);
      if (err != TIX_OK) { return err; }
      p->filter_count++;

      /* advance past filter token */
      while (*cursor != '\0' && *cursor != ' ' && *cursor != '\t') {
        if (*cursor == '"') {
          cursor++;
          while (*cursor != '\0' && *cursor != '"') { cursor++; }
          if (*cursor == '"') { cursor++; }
        } else {
          cursor++;
        }
      }
    }
    return TIX_OK;
  }

  snprintf(err_buf, err_len, "unknown stage: '%s'", word);
  return TIX_ERR_PARSE;
}

tix_err_t tql_parse(const char *query, tql_pipeline_t *out,
                    char *err_buf, sz err_len) {
  if (query == NULL || out == NULL) { return TIX_ERR_INVALID_ARG; }
  tql_pipeline_init(out);

  /* Split on pipe characters and parse each segment */
  const char *p = query;
  int seg_idx = 0;
  char seg_buf[TQL_MAX_SQL_LEN];

  while (*p != '\0') {
    /* extract segment up to next pipe */
    sz len = 0;
    while (p[len] != '\0' && p[len] != '|') {
      /* skip quoted strings in segment scan */
      if (p[len] == '"') {
        len++;
        while (p[len] != '\0' && p[len] != '"') { len++; }
        if (p[len] == '"') { len++; }
      } else {
        len++;
      }
    }

    if (len >= sizeof(seg_buf)) {
      snprintf(err_buf, err_len, "segment too long");
      return TIX_ERR_PARSE;
    }

    memcpy(seg_buf, p, len);
    seg_buf[len] = '\0';

    tix_err_t err = parse_segment(seg_buf, out, seg_idx, err_buf, err_len);
    if (err != TIX_OK) { return err; }

    p += len;
    if (*p == '|') { p++; }
    seg_idx++;
  }

  if (!out->has_source) {
    snprintf(err_buf, err_len,
             "query must start with a source (tasks|issues|notes|tickets)");
    return TIX_ERR_PARSE;
  }

  return TIX_OK;
}

/* tql_compile() and tql_prepare() are in tql_compile.c */
