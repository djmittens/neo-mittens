#pragma once

#include "types.h"
#include "common.h"

/*
 * Minimal JSON parser for plan.jsonl records.
 * No dynamic allocation - parses into fixed-size buffers.
 * Only handles flat objects with string/number values and string arrays.
 */

#define TIX_JSON_MAX_KEYS   32
#define TIX_JSON_MAX_ARRLEN 32

typedef enum {
  TIX_JSON_STRING,
  TIX_JSON_NUMBER,
  TIX_JSON_BOOL,
  TIX_JSON_NULL,
  TIX_JSON_ARRAY,
} tix_json_type_e;

typedef struct {
  char key[TIX_MAX_KEYWORD_LEN];
  tix_json_type_e type;
  char str_val[TIX_MAX_DESC_LEN];
  i64 num_val;
  int bool_val;
  /* for arrays of strings */
  char arr_vals[TIX_JSON_MAX_ARRLEN][TIX_MAX_ID_LEN];
  u32 arr_count;
} tix_json_field_t;

typedef struct {
  tix_json_field_t fields[TIX_JSON_MAX_KEYS];
  u32 field_count;
} tix_json_obj_t;

void tix_json_obj_init(tix_json_obj_t *obj);

tix_err_t tix_json_parse_line(const char *line, tix_json_obj_t *obj);

const char *tix_json_get_str(const tix_json_obj_t *obj, const char *key);
i64 tix_json_get_num(const tix_json_obj_t *obj, const char *key, i64 def);
int tix_json_get_bool(const tix_json_obj_t *obj, const char *key, int def);

int tix_json_has_key(const tix_json_obj_t *obj, const char *key);

/* Escape a string for JSON output (handles control chars, \, ") */
void tix_json_escape(const char *src, char *dst, sz dst_len);

/* Write helpers - write JSON to a char buffer */
sz tix_json_write_ticket(const void *ticket, char *buf, sz buf_len);
sz tix_json_write_tombstone(const void *tombstone, char *buf, sz buf_len);
