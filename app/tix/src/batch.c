#include "batch.h"
#include "ticket.h"
#include "json.h"
#include "search.h"
#include "log.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

static tix_err_t process_add(tix_db_t *db, const char *plan_path,
                             tix_json_obj_t *obj) {
  tix_ticket_t ticket;
  tix_ticket_init(&ticket);
  ticket.type = TIX_TICKET_TASK;
  ticket.created_at = (i64)time(NULL);
  ticket.updated_at = ticket.created_at;

  tix_err_t err = tix_ticket_gen_id(TIX_TICKET_TASK, ticket.id,
                                     sizeof(ticket.id));
  if (err != TIX_OK) { return err; }

  const char *name = tix_json_get_str(obj, "name");
  if (name != NULL) { tix_ticket_set_name(&ticket, name); }

  const char *notes = tix_json_get_str(obj, "notes");
  if (notes != NULL) { snprintf(ticket.notes, TIX_MAX_DESC_LEN, "%s", notes); }

  const char *accept = tix_json_get_str(obj, "accept");
  if (accept != NULL) { snprintf(ticket.accept, TIX_MAX_DESC_LEN, "%s", accept); }

  const char *spec = tix_json_get_str(obj, "spec");
  if (spec != NULL) { tix_ticket_set_spec(&ticket, spec); }

  const char *priority = tix_json_get_str(obj, "priority");
  ticket.priority = tix_priority_from_str(priority);

  /* write to plan and db */
  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&ticket, buf, sizeof(buf));
  if (len > 0) {
    FILE *fp = fopen(plan_path, "a");
    if (fp != NULL) {
      fprintf(fp, "%s\n", buf);
      fclose(fp);
    }
  }

  tix_db_upsert_ticket(db, &ticket);
  tix_search_index_ticket(db, &ticket);
  return TIX_OK;
}

tix_err_t tix_batch_execute(tix_db_t *db, const char *plan_path,
                            const char *batch_file,
                            tix_batch_result_t *result) {
  if (db == NULL || plan_path == NULL || batch_file == NULL ||
      result == NULL) {
    return TIX_ERR_INVALID_ARG;
  }

  memset(result, 0, sizeof(*result));

  FILE *fp = fopen(batch_file, "r");
  if (fp == NULL) {
    snprintf(result->last_error, sizeof(result->last_error),
             "cannot open %s", batch_file);
    return TIX_ERR_IO;
  }

  char line[TIX_MAX_LINE_LEN];
  while (fgets(line, (int)sizeof(line), fp) != NULL) {
    tix_json_obj_t obj;
    if (tix_json_parse_line(line, &obj) != TIX_OK) {
      result->error_count++;
      continue;
    }

    const char *op = tix_json_get_str(&obj, "op");
    if (op == NULL) {
      result->error_count++;
      continue;
    }

    tix_err_t err = TIX_ERR_INVALID_ARG;
    if (strcmp(op, "add") == 0) {
      err = process_add(db, plan_path, &obj);
    } else if (strcmp(op, "delete") == 0) {
      const char *id = tix_json_get_str(&obj, "id");
      if (id != NULL) { err = tix_db_delete_ticket(db, id); }
    }

    if (err == TIX_OK) {
      result->success_count++;
    } else {
      result->error_count++;
      snprintf(result->last_error, sizeof(result->last_error),
               "%s: %s", op, tix_strerror(err));
    }
  }

  fclose(fp);
  return TIX_OK;
}

tix_err_t tix_batch_execute_json(tix_db_t *db, const char *plan_path,
                                 const char *json_array,
                                 tix_batch_result_t *result) {
  if (db == NULL || plan_path == NULL || json_array == NULL ||
      result == NULL) {
    return TIX_ERR_INVALID_ARG;
  }

  memset(result, 0, sizeof(*result));

  /* minimal array parsing: split on },{  */
  char buf[TIX_MAX_LINE_LEN * 4];
  snprintf(buf, sizeof(buf), "%s", json_array);

  /* skip leading [ */
  char *p = buf;
  while (*p == ' ' || *p == '[') { p++; }

  while (*p != '\0' && *p != ']') {
    /* find the end of this object */
    char *start = p;
    int depth = 0;
    while (*p != '\0') {
      if (*p == '{') { depth++; }
      if (*p == '}') { depth--; if (depth == 0) { p++; break; } }
      p++;
    }

    /* extract object */
    char obj_str[TIX_MAX_LINE_LEN];
    sz obj_len = (sz)(p - start);
    if (obj_len >= sizeof(obj_str)) { obj_len = sizeof(obj_str) - 1; }
    memcpy(obj_str, start, obj_len);
    obj_str[obj_len] = '\0';

    tix_json_obj_t obj;
    if (tix_json_parse_line(obj_str, &obj) == TIX_OK) {
      tix_err_t err = process_add(db, plan_path, &obj);
      if (err == TIX_OK) {
        result->success_count++;
      } else {
        result->error_count++;
      }
    }

    /* skip comma between objects */
    while (*p == ',' || *p == ' ' || *p == '\n') { p++; }
  }

  return TIX_OK;
}
