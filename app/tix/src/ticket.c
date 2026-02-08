#include "ticket.h"
#include "log.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

static u32 tix_id_counter = 0;

tix_err_t tix_ticket_gen_id(tix_ticket_type_e type, char *out, sz out_len) {
  if (out == NULL || out_len < TIX_MAX_ID_LEN) {
    return TIX_ERR_INVALID_ARG;
  }

  const char *prefix = "t";
  if (type == TIX_TICKET_ISSUE) { prefix = "i"; }
  if (type == TIX_TICKET_NOTE)  { prefix = "n"; }

  struct timespec ts = {0, 0};
  if (clock_gettime(CLOCK_REALTIME, &ts) != 0) { return TIX_ERR_IO; }
  u32 hash = (u32)(ts.tv_sec ^ ts.tv_nsec ^ (++tix_id_counter));

  int n = snprintf(out, out_len, "%s-%08x", prefix, hash);
  if (n < 0 || (sz)n >= out_len) { return TIX_ERR_OVERFLOW; }

  return TIX_OK;
}

const char *tix_ticket_type_str(tix_ticket_type_e type) {
  switch (type) {
    case TIX_TICKET_TASK:  return "task";
    case TIX_TICKET_ISSUE: return "issue";
    case TIX_TICKET_NOTE:  return "note";
  }
  return "unknown";
}

const char *tix_status_str(tix_status_e status) {
  switch (status) {
    case TIX_STATUS_PENDING:  return "pending";
    case TIX_STATUS_DONE:     return "done";
    case TIX_STATUS_ACCEPTED: return "accepted";
    case TIX_STATUS_REJECTED: return "rejected";
    case TIX_STATUS_DELETED:  return "deleted";
  }
  return "unknown";
}

const char *tix_priority_str(tix_priority_e prio) {
  switch (prio) {
    case TIX_PRIORITY_NONE:   return "none";
    case TIX_PRIORITY_LOW:    return "low";
    case TIX_PRIORITY_MEDIUM: return "medium";
    case TIX_PRIORITY_HIGH:   return "high";
  }
  return "none";
}

tix_priority_e tix_priority_from_str(const char *s) {
  if (s == NULL) { return TIX_PRIORITY_NONE; }
  if (strcmp(s, "high") == 0)   { return TIX_PRIORITY_HIGH; }
  if (strcmp(s, "medium") == 0) { return TIX_PRIORITY_MEDIUM; }
  if (strcmp(s, "low") == 0)    { return TIX_PRIORITY_LOW; }
  return TIX_PRIORITY_NONE;
}

void tix_ticket_init(tix_ticket_t *t) {
  memset(t, 0, sizeof(*t));
  t->type = TIX_TICKET_TASK;
  t->status = TIX_STATUS_PENDING;
  t->priority = TIX_PRIORITY_NONE;
}

tix_err_t tix_ticket_set_name(tix_ticket_t *t, const char *name) {
  if (t == NULL || name == NULL) { return TIX_ERR_INVALID_ARG; }
  sz len = strlen(name);
  if (len >= TIX_MAX_NAME_LEN) { return TIX_ERR_OVERFLOW; }
  memcpy(t->name, name, len + 1);
  return TIX_OK;
}

tix_err_t tix_ticket_set_spec(tix_ticket_t *t, const char *spec) {
  if (t == NULL || spec == NULL) { return TIX_ERR_INVALID_ARG; }
  sz len = strlen(spec);
  if (len >= TIX_MAX_PATH_LEN) { return TIX_ERR_OVERFLOW; }
  memcpy(t->spec, spec, len + 1);
  return TIX_OK;
}

tix_err_t tix_ticket_add_label(tix_ticket_t *t, const char *label) {
  if (t == NULL || label == NULL) { return TIX_ERR_INVALID_ARG; }
  if (t->label_count >= TIX_MAX_LABELS) { return TIX_ERR_OVERFLOW; }
  sz len = strlen(label);
  if (len == 0 || len >= TIX_MAX_KEYWORD_LEN) { return TIX_ERR_OVERFLOW; }
  /* skip duplicates silently */
  if (tix_ticket_has_label(t, label)) { return TIX_OK; }
  memcpy(t->labels[t->label_count], label, len + 1);
  t->label_count++;
  return TIX_OK;
}

int tix_ticket_has_label(const tix_ticket_t *t, const char *label) {
  if (t == NULL || label == NULL) { return 0; }
  for (u32 i = 0; i < t->label_count; i++) {
    if (strcmp(t->labels[i], label) == 0) { return 1; }
  }
  return 0;
}

tix_err_t tix_ticket_add_dep(tix_ticket_t *t, const char *dep_id) {
  if (t == NULL || dep_id == NULL) { return TIX_ERR_INVALID_ARG; }
  if (t->dep_count >= TIX_MAX_DEPS) { return TIX_ERR_OVERFLOW; }
  sz len = strlen(dep_id);
  if (len >= TIX_MAX_ID_LEN) { return TIX_ERR_OVERFLOW; }
  memcpy(t->deps[t->dep_count], dep_id, len + 1);
  t->dep_count++;
  return TIX_OK;
}

int tix_is_valid_ticket_id(const char *id) {
  if (id == NULL || strlen(id) < 3) { return 0; }
  if (id[0] != 't' && id[0] != 'i' && id[0] != 'n') { return 0; }
  if (id[1] != '-') { return 0; }
  for (sz k = 2; id[k] != '\0'; k++) {
    char c = id[k];
    int is_hex = (c >= '0' && c <= '9') ||
                 (c >= 'a' && c <= 'f') ||
                 (c >= 'A' && c <= 'F');
    if (!is_hex) { return 0; }
  }
  return 1;
}

int tix_has_duplicate_dep(const tix_ticket_t *t, const char *dep_id) {
  if (t == NULL || dep_id == NULL) { return 0; }
  for (u32 i = 0; i < t->dep_count; i++) {
    if (strcmp(t->deps[i], dep_id) == 0) { return 1; }
  }
  return 0;
}

tix_err_t tix_timestamp_iso8601(char *out, sz out_len) {
  if (out == NULL || out_len < 26) { return TIX_ERR_INVALID_ARG; }

  time_t now = time(NULL);
  struct tm local;
  struct tm utc;
  if (localtime_r(&now, &local) == NULL) { return TIX_ERR_IO; }
  if (gmtime_r(&now, &utc) == NULL) { return TIX_ERR_IO; }

  /* "2026-02-07T14:30:00" = 19 chars, "+HH:MM" = 6 chars, NUL = 1 => 26 */
  sz pos = strftime(out, out_len, "%Y-%m-%dT%H:%M:%S", &local);
  if (pos == 0) { return TIX_ERR_OVERFLOW; }

  /* compute UTC offset portably: diff between local and UTC mktime */
  time_t local_epoch = mktime(&local);
  time_t utc_epoch = mktime(&utc);
  long offset = (long)(local_epoch - utc_epoch);
  char sign = '+';
  if (offset < 0) { sign = '-'; offset = -offset; }
  int off_h = (int)(offset / 3600);
  int off_m = (int)((offset % 3600) / 60);

  int n = snprintf(out + pos, out_len - pos, "%c%02d:%02d", sign, off_h, off_m);
  if (n < 0 || (sz)n >= out_len - pos) { return TIX_ERR_OVERFLOW; }

  return TIX_OK;
}
