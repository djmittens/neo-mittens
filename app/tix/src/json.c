#include "json.h"
#include "ticket.h"
#include "log.h"

#include <ctype.h>
#include <string.h>
#include <stdio.h>

void tix_json_obj_init(tix_json_obj_t *obj) {
  memset(obj, 0, sizeof(*obj));
}

static const char *skip_ws(const char *p) {
  while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') { p++; }
  return p;
}

static const char *parse_string(const char *p, char *out, sz out_len) {
  if (*p != '"') { return NULL; }
  if (out_len == 0) { return NULL; }
  p++;
  sz i = 0;
  while (*p != '\0' && *p != '"' && i < out_len - 1) {
    if (*p == '\\' && *(p + 1) != '\0') {
      p++;
      if (*p == 'n')       { out[i++] = '\n'; }
      else if (*p == 't')  { out[i++] = '\t'; }
      else if (*p == 'r')  { out[i++] = '\r'; }
      else if (*p == 'b')  { out[i++] = '\b'; }
      else if (*p == 'f')  { out[i++] = '\f'; }
      else if (*p == '"')  { out[i++] = '"'; }
      else if (*p == '\\') { out[i++] = '\\'; }
      else if (*p == '/')  { out[i++] = '/'; }
      else if (*p == 'u')  { out[i++] = '?'; p += 4; p--; } /* skip \uXXXX */
      else { out[i++] = *p; }
    } else {
      out[i++] = *p;
    }
    p++;
  }
  out[i] = '\0';
  /* skip past remaining string content if we ran out of buffer */
  while (*p != '\0' && *p != '"') {
    if (*p == '\\' && *(p + 1) != '\0') { p++; }
    p++;
  }
  if (*p != '"') { return NULL; }
  p++;
  return p;
}

static const char *parse_array_of_strings(const char *p,
                                          tix_json_field_t *field) {
  if (*p != '[') { return NULL; }
  p++;
  field->arr_count = 0;

  p = skip_ws(p);
  if (*p == ']') { return p + 1; }

  while (*p != '\0' && *p != ']' && field->arr_count < TIX_JSON_MAX_ARRLEN) {
    p = skip_ws(p);
    if (*p != '"') { break; }
    p = parse_string(p, field->arr_vals[field->arr_count], TIX_MAX_ID_LEN);
    if (p == NULL) { return NULL; }
    field->arr_count++;
    p = skip_ws(p);
    if (*p == ',') { p++; }
  }
  if (*p != ']') { return NULL; }
  p++;
  return p;
}

tix_err_t tix_json_parse_line(const char *line, tix_json_obj_t *obj) {
  if (line == NULL || obj == NULL) { return TIX_ERR_INVALID_ARG; }

  tix_json_obj_init(obj);
  const char *p = skip_ws(line);
  if (*p != '{') { return TIX_ERR_PARSE; }
  p++;

  while (*p != '\0' && *p != '}' && obj->field_count < TIX_JSON_MAX_KEYS) {
    p = skip_ws(p);
    if (*p == '}') { break; }

    tix_json_field_t *f = &obj->fields[obj->field_count];
    memset(f, 0, sizeof(*f));

    /* parse key */
    p = parse_string(p, f->key, TIX_MAX_KEYWORD_LEN);
    if (p == NULL) { return TIX_ERR_PARSE; }

    p = skip_ws(p);
    if (*p != ':') { return TIX_ERR_PARSE; }
    p++;
    p = skip_ws(p);

    /* parse value */
    if (*p == '"') {
      f->type = TIX_JSON_STRING;
      p = parse_string(p, f->str_val, TIX_MAX_DESC_LEN);
      if (p == NULL) { return TIX_ERR_PARSE; }
    } else if (*p == '[') {
      f->type = TIX_JSON_ARRAY;
      p = parse_array_of_strings(p, f);
      if (p == NULL) { return TIX_ERR_PARSE; }
    } else if (*p == 't' || *p == 'f') {
      f->type = TIX_JSON_BOOL;
      if (strncmp(p, "true", 4) == 0) {
        f->bool_val = 1;
        p += 4;
      } else if (strncmp(p, "false", 5) == 0) {
        f->bool_val = 0;
        p += 5;
      } else {
        return TIX_ERR_PARSE;
      }
    } else if (*p == 'n' && strncmp(p, "null", 4) == 0) {
      f->type = TIX_JSON_NULL;
      p += 4;
    } else if (*p == '-' || isdigit((unsigned char)*p)) {
      f->type = TIX_JSON_NUMBER;
      char *end = NULL;
      f->num_val = strtoll(p, &end, 10);
      p = end;
    } else {
      return TIX_ERR_PARSE;
    }

    obj->field_count++;
    p = skip_ws(p);
    if (*p == ',') { p++; }
  }

  p = skip_ws(p);
  if (*p != '}') { return TIX_ERR_PARSE; }

  return TIX_OK;
}

const char *tix_json_get_str(const tix_json_obj_t *obj, const char *key) {
  if (obj == NULL || key == NULL) { return NULL; }
  for (u32 i = 0; i < obj->field_count; i++) {
    if (strcmp(obj->fields[i].key, key) == 0) {
      if (obj->fields[i].type == TIX_JSON_STRING) {
        return obj->fields[i].str_val;
      }
      return NULL;
    }
  }
  return NULL;
}

i64 tix_json_get_num(const tix_json_obj_t *obj, const char *key, i64 def) {
  if (obj == NULL || key == NULL) { return def; }
  for (u32 i = 0; i < obj->field_count; i++) {
    if (strcmp(obj->fields[i].key, key) == 0) {
      if (obj->fields[i].type == TIX_JSON_NUMBER) {
        return obj->fields[i].num_val;
      }
      return def;
    }
  }
  return def;
}

int tix_json_get_bool(const tix_json_obj_t *obj, const char *key, int def) {
  if (obj == NULL || key == NULL) { return def; }
  for (u32 i = 0; i < obj->field_count; i++) {
    if (strcmp(obj->fields[i].key, key) == 0) {
      if (obj->fields[i].type == TIX_JSON_BOOL) {
        return obj->fields[i].bool_val;
      }
      return def;
    }
  }
  return def;
}

int tix_json_has_key(const tix_json_obj_t *obj, const char *key) {
  if (obj == NULL || key == NULL) { return 0; }
  for (u32 i = 0; i < obj->field_count; i++) {
    if (strcmp(obj->fields[i].key, key) == 0) { return 1; }
  }
  return 0;
}

void tix_json_escape(const char *src, char *dst, sz dst_len) {
  if (dst_len < 2) {
    if (dst_len == 1) { dst[0] = '\0'; }
    return;
  }
  sz j = 0;
  for (sz i = 0; src[i] != '\0' && j < dst_len - 2; i++) {
    unsigned char c = (unsigned char)src[i];
    if (c == '"' || c == '\\') {
      dst[j++] = '\\';
      if (j >= dst_len - 1) { break; }
      dst[j++] = (char)c;
      continue;
    }
    if (c == '\n') {
      dst[j++] = '\\';
      if (j >= dst_len - 1) { break; }
      dst[j++] = 'n';
      continue;
    }
    if (c == '\t') {
      dst[j++] = '\\';
      if (j >= dst_len - 1) { break; }
      dst[j++] = 't';
      continue;
    }
    if (c == '\r') {
      dst[j++] = '\\';
      if (j >= dst_len - 1) { break; }
      dst[j++] = 'r';
      continue;
    }
    if (c == '\b') {
      dst[j++] = '\\';
      if (j >= dst_len - 1) { break; }
      dst[j++] = 'b';
      continue;
    }
    if (c == '\f') {
      dst[j++] = '\\';
      if (j >= dst_len - 1) { break; }
      dst[j++] = 'f';
      continue;
    }
    if (c < 0x20) {
      /* escape other control chars as \u00XX */
      if (j + 6 >= dst_len) { break; }
      int n = snprintf(dst + j, dst_len - j, "\\u%04x", c);
      if (n > 0) { j += (sz)n; }
      continue;
    }
    dst[j++] = (char)c;
  }
  dst[j] = '\0';
}

sz tix_json_write_ticket(const void *vticket, char *buf, sz buf_len) {
  const tix_ticket_t *t = (const tix_ticket_t *)vticket;
  if (t == NULL || buf == NULL || buf_len < 64) { return 0; }

  char esc_name[TIX_MAX_NAME_LEN * 2];
  char esc_notes[TIX_MAX_DESC_LEN * 2];
  char esc_accept[TIX_MAX_DESC_LEN * 2];
  tix_json_escape(t->name, esc_name, sizeof(esc_name));
  tix_json_escape(t->notes, esc_notes, sizeof(esc_notes));
  tix_json_escape(t->accept, esc_accept, sizeof(esc_accept));

  char *p = buf;
  char *end = buf + buf_len;

  const char *type_key = "task";
  if (t->type == TIX_TICKET_ISSUE) { type_key = "issue"; }
  if (t->type == TIX_TICKET_NOTE)  { type_key = "note"; }

  const char *status_key = "p";
  if (t->status == TIX_STATUS_DONE)     { status_key = "d"; }
  if (t->status == TIX_STATUS_ACCEPTED) { status_key = "a"; }

  TIX_BUF_PRINTF(p, end, 0,
      "{\"t\":\"%s\",\"id\":\"%s\",\"name\":\"%s\",\"s\":\"%s\"",
      type_key, t->id, esc_name, status_key);

  if (t->spec[0] != '\0') {
    TIX_BUF_PRINTF(p, end, 0, ",\"spec\":\"%s\"", t->spec);
  }
  if (esc_notes[0] != '\0') {
    TIX_BUF_PRINTF(p, end, 0, ",\"notes\":\"%s\"", esc_notes);
  }
  if (esc_accept[0] != '\0') {
    TIX_BUF_PRINTF(p, end, 0, ",\"accept\":\"%s\"", esc_accept);
  }
  if (t->done_at[0] != '\0') {
    TIX_BUF_PRINTF(p, end, 0, ",\"done_at\":\"%s\"", t->done_at);
  }
  if (t->branch[0] != '\0') {
    TIX_BUF_PRINTF(p, end, 0, ",\"branch\":\"%s\"", t->branch);
  }
  if (t->parent[0] != '\0') {
    TIX_BUF_PRINTF(p, end, 0, ",\"parent\":\"%s\"", t->parent);
  }
  if (t->created_from[0] != '\0') {
    TIX_BUF_PRINTF(p, end, 0, ",\"created_from\":\"%s\"", t->created_from);
  }
  if (t->supersedes[0] != '\0') {
    TIX_BUF_PRINTF(p, end, 0, ",\"supersedes\":\"%s\"", t->supersedes);
  }
  if (t->kill_reason[0] != '\0') {
    TIX_BUF_PRINTF(p, end, 0, ",\"kill_reason\":\"%s\"", t->kill_reason);
  }
  if (t->priority != TIX_PRIORITY_NONE) {
    TIX_BUF_PRINTF(p, end, 0, ",\"priority\":\"%s\"",
                   tix_priority_str(t->priority));
  }
  if (t->dep_count > 0) {
    TIX_BUF_PRINTF(p, end, 0, ",\"deps\":[");
    for (u32 i = 0; i < t->dep_count; i++) {
      if (i > 0) { TIX_BUF_PRINTF(p, end, 0, ","); }
      TIX_BUF_PRINTF(p, end, 0, "\"%s\"", t->deps[i]);
    }
    TIX_BUF_PRINTF(p, end, 0, "]");
  }

  TIX_BUF_PRINTF(p, end, 0, "}");
  return (sz)(p - buf);
}

sz tix_json_write_tombstone(const void *vtombstone, char *buf, sz buf_len) {
  const tix_tombstone_t *ts = (const tix_tombstone_t *)vtombstone;
  if (ts == NULL || buf == NULL || buf_len < 64) { return 0; }

  char esc_reason[TIX_MAX_DESC_LEN * 2];
  char esc_name[TIX_MAX_NAME_LEN * 2];
  tix_json_escape(ts->reason, esc_reason, sizeof(esc_reason));
  tix_json_escape(ts->name, esc_name, sizeof(esc_name));

  char *p = buf;
  char *end = buf + buf_len;
  const char *type = ts->is_accept ? "accept" : "reject";

  TIX_BUF_PRINTF(p, end, 0,
      "{\"t\":\"%s\",\"id\":\"%s\",\"done_at\":\"%s\","
      "\"reason\":\"%s\",\"name\":\"%s\"}",
      type, ts->id, ts->done_at, esc_reason, esc_name);

  return (sz)(p - buf);
}
