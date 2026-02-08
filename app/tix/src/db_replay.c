/*
 * db_replay.c — JSONL replay and cache rebuild.
 *
 * Split from db.c to respect the 1000-line file limit.
 * Handles parsing plan.jsonl lines and replaying them into the SQLite cache.
 */

#include "db.h"
#include "git.h"
#include "json.h"
#include "validate.h"
#include "log.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

tix_err_t tix_db_is_stale(tix_db_t *db, int *is_stale) {
  if (db == NULL || is_stale == NULL) { return TIX_ERR_INVALID_ARG; }

  char cached_commit[TIX_MAX_HASH_LEN];
  tix_err_t err = tix_db_get_meta(db, "last_commit",
                                   cached_commit, sizeof(cached_commit));
  if (err != TIX_OK || cached_commit[0] == '\0') {
    *is_stale = 1;
    return TIX_OK;
  }

  char head[TIX_MAX_HASH_LEN];
  err = tix_git_rev_parse_head(head, sizeof(head));
  if (err != TIX_OK) {
    *is_stale = 1;
    return TIX_OK;
  }

  *is_stale = (strcmp(cached_commit, head) != 0) ? 1 : 0;
  return TIX_OK;
}

static tix_ticket_type_e type_from_jsonl(const char *t_val) {
  if (strcmp(t_val, "task") == 0)  { return TIX_TICKET_TASK; }
  if (strcmp(t_val, "issue") == 0) { return TIX_TICKET_ISSUE; }
  if (strcmp(t_val, "note") == 0)  { return TIX_TICKET_NOTE; }
  return TIX_TICKET_TASK;
}

static tix_status_e status_from_jsonl(const char *s_val) {
  if (s_val == NULL) { return TIX_STATUS_PENDING; }
  if (strcmp(s_val, "d") == 0) { return TIX_STATUS_DONE; }
  if (strcmp(s_val, "a") == 0) { return TIX_STATUS_ACCEPTED; }
  if (strcmp(s_val, "r") == 0) { return TIX_STATUS_REJECTED; }
  if (strcmp(s_val, "x") == 0) { return TIX_STATUS_DELETED; }
  return TIX_STATUS_PENDING;
}

/* Parse a single JSONL line and apply it to the DB (upsert/delete).
   This is the shared core used by replay_content and replay_jsonl_file. */
static void replay_one_line(tix_db_t *db, const char *line) {
  tix_json_obj_t obj;
  if (tix_json_parse_line(line, &obj) != TIX_OK) { return; }

  const char *t_val = tix_json_get_str(&obj, "t");
  if (t_val == NULL) { return; }

  if (strcmp(t_val, "task") == 0 || strcmp(t_val, "issue") == 0 ||
      strcmp(t_val, "note") == 0) {
    tix_ticket_t ticket;
    tix_ticket_init(&ticket);
    ticket.type = type_from_jsonl(t_val);

    const char *id = tix_json_get_str(&obj, "id");
    if (id != NULL) { snprintf(ticket.id, TIX_MAX_ID_LEN, "%s", id); }

    const char *name = tix_json_get_str(&obj, "name");
    if (name != NULL) { snprintf(ticket.name, TIX_MAX_NAME_LEN, "%s", name); }

    const char *s = tix_json_get_str(&obj, "s");
    ticket.status = status_from_jsonl(s);

    const char *spec = tix_json_get_str(&obj, "spec");
    if (spec != NULL) { snprintf(ticket.spec, TIX_MAX_PATH_LEN, "%s", spec); }

    const char *notes = tix_json_get_str(&obj, "notes");
    if (notes != NULL) { snprintf(ticket.notes, TIX_MAX_DESC_LEN, "%s", notes); }

    const char *accept = tix_json_get_str(&obj, "accept");
    if (accept != NULL) { snprintf(ticket.accept, TIX_MAX_DESC_LEN, "%s", accept); }

    const char *done_at = tix_json_get_str(&obj, "done_at");
    if (done_at != NULL) { snprintf(ticket.done_at, TIX_MAX_HASH_LEN, "%s", done_at); }

    const char *priority = tix_json_get_str(&obj, "priority");
    ticket.priority = tix_priority_from_str(priority);

    const char *parent = tix_json_get_str(&obj, "parent");
    if (parent != NULL) { snprintf(ticket.parent, TIX_MAX_ID_LEN, "%s", parent); }

    const char *cf = tix_json_get_str(&obj, "created_from");
    if (cf != NULL) { snprintf(ticket.created_from, TIX_MAX_ID_LEN, "%s", cf); }

    const char *ss = tix_json_get_str(&obj, "supersedes");
    if (ss != NULL) { snprintf(ticket.supersedes, TIX_MAX_ID_LEN, "%s", ss); }

    const char *kr = tix_json_get_str(&obj, "kill_reason");
    if (kr != NULL) { snprintf(ticket.kill_reason, TIX_MAX_KEYWORD_LEN, "%s", kr); }

    /* denormalized reference names */
    const char *cfn = tix_json_get_str(&obj, "created_from_name");
    if (cfn != NULL) {
      snprintf(ticket.created_from_name, TIX_MAX_NAME_LEN, "%s", cfn);
    }
    const char *ssn = tix_json_get_str(&obj, "supersedes_name");
    if (ssn != NULL) {
      snprintf(ticket.supersedes_name, TIX_MAX_NAME_LEN, "%s", ssn);
    }
    const char *ssr = tix_json_get_str(&obj, "supersedes_reason");
    if (ssr != NULL) {
      snprintf(ticket.supersedes_reason, TIX_MAX_KEYWORD_LEN, "%s", ssr);
    }

    const char *branch = tix_json_get_str(&obj, "branch");
    if (branch != NULL) {
      snprintf(ticket.branch, TIX_MAX_BRANCH_LEN, "%s", branch);
    }

    /* identity & attribution */
    const char *author = tix_json_get_str(&obj, "author");
    if (author != NULL) {
      snprintf(ticket.author, TIX_MAX_NAME_LEN, "%s", author);
    }

    const char *assigned = tix_json_get_str(&obj, "assigned");
    if (assigned != NULL) {
      snprintf(ticket.assigned, TIX_MAX_NAME_LEN, "%s", assigned);
    }

    /* completion timing */
    const char *completed_at = tix_json_get_str(&obj, "completed_at");
    if (completed_at != NULL) {
      snprintf(ticket.completed_at, sizeof(ticket.completed_at),
               "%s", completed_at);
    }

    /* lifecycle timestamps */
    ticket.resolved_at = tix_json_get_num(&obj, "resolved_at", 0);
    ticket.compacted_at = tix_json_get_num(&obj, "compacted_at", 0);

    /* load deps from JSON array */
    for (u32 fi = 0; fi < obj.field_count; fi++) {
      if (strcmp(obj.fields[fi].key, "deps") == 0 &&
          obj.fields[fi].type == TIX_JSON_ARRAY) {
        for (u32 ai = 0; ai < obj.fields[fi].arr_count &&
             ticket.dep_count < TIX_MAX_DEPS; ai++) {
          const char *dval = obj.fields[fi].arr_vals[ai];
          sz dlen = strlen(dval);
          if (dlen >= TIX_MAX_ID_LEN) { dlen = TIX_MAX_ID_LEN - 1; }
          memcpy(ticket.deps[ticket.dep_count], dval, dlen);
          ticket.deps[ticket.dep_count][dlen] = '\0';
          ticket.dep_count++;
        }
        break;
      }
    }

    /* load labels from JSON array */
    for (u32 fi = 0; fi < obj.field_count; fi++) {
      if (strcmp(obj.fields[fi].key, "labels") == 0 &&
          obj.fields[fi].type == TIX_JSON_ARRAY) {
        for (u32 ai = 0; ai < obj.fields[fi].arr_count &&
             ticket.label_count < TIX_MAX_LABELS; ai++) {
          snprintf(ticket.labels[ticket.label_count], TIX_MAX_KEYWORD_LEN,
                   "%s", obj.fields[fi].arr_vals[ai]);
          ticket.label_count++;
        }
        break;
      }
    }

    tix_db_upsert_ticket(db, &ticket);

    /* route metadata from "meta":{...} sub-object to ticket_meta table */
    if (ticket.id[0] != '\0') {
      for (u32 fi = 0; fi < obj.field_count; fi++) {
        if (strncmp(obj.fields[fi].key, "meta.", 5) != 0) { continue; }
        const char *mkey = obj.fields[fi].key + 5; /* skip "meta." */
        if (mkey[0] == '\0') { continue; }
        if (obj.fields[fi].type == TIX_JSON_NUMBER) {
          tix_db_set_ticket_meta_num(db, ticket.id,
                                     mkey, obj.fields[fi].dbl_val);
        } else if (obj.fields[fi].type == TIX_JSON_STRING) {
          tix_db_set_ticket_meta_str(db, ticket.id,
                                     mkey, obj.fields[fi].str_val);
        }
      }
    }
  } else if (strcmp(t_val, "accept") == 0 || strcmp(t_val, "reject") == 0) {
    tix_tombstone_t ts;
    memset(&ts, 0, sizeof(ts));
    ts.is_accept = (strcmp(t_val, "accept") == 0) ? 1 : 0;

    const char *id = tix_json_get_str(&obj, "id");
    if (id != NULL) { snprintf(ts.id, TIX_MAX_ID_LEN, "%s", id); }

    const char *done_at = tix_json_get_str(&obj, "done_at");
    if (done_at != NULL) { snprintf(ts.done_at, TIX_MAX_HASH_LEN, "%s", done_at); }

    const char *reason = tix_json_get_str(&obj, "reason");
    if (reason != NULL) { snprintf(ts.reason, TIX_MAX_DESC_LEN, "%s", reason); }

    const char *name = tix_json_get_str(&obj, "name");
    if (name != NULL) { snprintf(ts.name, TIX_MAX_NAME_LEN, "%s", name); }

    ts.timestamp = tix_json_get_num(&obj, "timestamp", 0);

    tix_db_upsert_tombstone(db, &ts);

    /* Accept: mark ticket as ACCEPTED with resolved_at instead of deleting.
       Reject: the subsequent ticket line will reset it to PENDING.
       We still update the ticket to REJECTED here so the tombstone timestamp
       is captured; the next ticket line will overwrite it back to PENDING. */
    if (ts.id[0] != '\0') {
      tix_ticket_t existing;
      if (tix_db_get_ticket(db, ts.id, &existing) == TIX_OK) {
        existing.status = ts.is_accept ?
            TIX_STATUS_ACCEPTED : TIX_STATUS_REJECTED;
        if (ts.timestamp > 0) {
          existing.resolved_at = ts.timestamp;
        } else {
          existing.resolved_at = (i64)time(NULL);
        }
        tix_db_upsert_ticket(db, &existing);
      }
    }
  } else if (strcmp(t_val, "delete") == 0) {
    const char *id = tix_json_get_str(&obj, "id");
    if (id != NULL) {
      /* Mark ticket as DELETED with resolved_at instead of deleting */
      tix_ticket_t existing;
      if (tix_db_get_ticket(db, id, &existing) == TIX_OK) {
        existing.status = TIX_STATUS_DELETED;
        existing.resolved_at = (i64)time(NULL);
        tix_db_upsert_ticket(db, &existing);
      }
    }
  }
}

tix_err_t tix_db_clear_tickets(tix_db_t *db) {
  if (db == NULL || db->handle == NULL) { return TIX_ERR_INVALID_ARG; }

  sqlite3_exec(db->handle, "DELETE FROM tickets", NULL, NULL, NULL);
  sqlite3_exec(db->handle, "DELETE FROM ticket_deps", NULL, NULL, NULL);
  sqlite3_exec(db->handle, "DELETE FROM ticket_labels", NULL, NULL, NULL);
  sqlite3_exec(db->handle, "DELETE FROM tombstones", NULL, NULL, NULL);
  sqlite3_exec(db->handle, "DELETE FROM keywords", NULL, NULL, NULL);
  sqlite3_exec(db->handle, "DELETE FROM ticket_meta", NULL, NULL, NULL);
  return TIX_OK;
}

tix_err_t tix_db_replay_content(tix_db_t *db, const char *content) {
  if (db == NULL) { return TIX_ERR_INVALID_ARG; }
  if (content == NULL || content[0] == '\0') { return TIX_OK; }

  const char *p = content;
  char line[TIX_MAX_LINE_LEN];

  while (*p != '\0') {
    const char *nl = strchr(p, '\n');
    sz line_len;
    if (nl != NULL) {
      line_len = (sz)(nl - p);
    } else {
      line_len = strlen(p);
    }
    if (line_len >= sizeof(line)) { line_len = sizeof(line) - 1; }
    memcpy(line, p, line_len);
    line[line_len] = '\0';

    p = (nl != NULL) ? nl + 1 : p + line_len;

    if (line[0] == '\0') { continue; }
    replay_one_line(db, line);
  }

  return TIX_OK;
}

tix_err_t tix_db_replay_jsonl_file(tix_db_t *db, const char *jsonl_path) {
  if (db == NULL || jsonl_path == NULL) { return TIX_ERR_INVALID_ARG; }

  FILE *fp = fopen(jsonl_path, "r");
  if (fp == NULL) {
    TIX_DEBUG("plan.jsonl not found at %s, skipping", jsonl_path);
    return TIX_OK;
  }

  sqlite3_exec(db->handle, "BEGIN TRANSACTION", NULL, NULL, NULL);

  char line[TIX_MAX_LINE_LEN];
  while (fgets(line, (int)sizeof(line), fp) != NULL) {
    replay_one_line(db, line);
  }

  sqlite3_exec(db->handle, "COMMIT", NULL, NULL, NULL);
  fclose(fp);

  TIX_INFO("replayed %s into cache", jsonl_path);
  return TIX_OK;
}

tix_err_t tix_db_rebuild_from_jsonl(tix_db_t *db, const char *jsonl_path) {
  if (db == NULL || jsonl_path == NULL) { return TIX_ERR_INVALID_ARG; }

  FILE *fp = fopen(jsonl_path, "r");
  if (fp == NULL) {
    TIX_DEBUG("plan.jsonl not found at %s, starting fresh", jsonl_path);
    return TIX_OK;
  }
  fclose(fp);

  tix_db_clear_tickets(db);

  tix_err_t err = tix_db_replay_jsonl_file(db, jsonl_path);
  if (err != TIX_OK) { return err; }

  /* update cache commit */
  char head[TIX_MAX_HASH_LEN];
  if (tix_git_rev_parse_head(head, sizeof(head)) == TIX_OK) {
    tix_db_set_meta(db, "last_commit", head);
  }

  TIX_INFO("rebuilt cache from %s", jsonl_path);

  /* run validation after rebuild to surface data issues from JSONL */
  tix_validation_result_t vresult;
  tix_err_t verr = tix_validate_history(db, jsonl_path, &vresult);
  if (verr == TIX_OK) {
    for (u32 vi = 0; vi < vresult.error_count; vi++) {
      TIX_WARN("rebuild validation: %s", vresult.errors[vi]);
    }
    for (u32 vi = 0; vi < vresult.warning_count; vi++) {
      TIX_DEBUG("rebuild validation: %s", vresult.warnings[vi]);
    }
  }

  return TIX_OK;
}
