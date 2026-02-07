#include "cmd.h"
#include "git.h"
#include "json.h"
#include "search.h"
#include "log.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

/* check if any other ticket depends on the given ID */
static int has_dependents(tix_db_t *db, const char *id) {
  const char *sql =
    "SELECT COUNT(*) FROM ticket_deps WHERE dep_id=?";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return 0; }
  sqlite3_bind_text(stmt, 1, id, -1, SQLITE_STATIC);
  int count = 0;
  if (sqlite3_step(stmt) == SQLITE_ROW) {
    count = sqlite3_column_int(stmt, 0);
  }
  sqlite3_finalize(stmt);
  return count > 0;
}

/* Check if ticket belongs to current branch.
   Returns 1 if OK (ticket has no branch or matches current), 0 if mismatch. */
static int check_branch_scope(const tix_ticket_t *ticket) {
  if (ticket->branch[0] == '\0') { return 1; }
  char current[TIX_MAX_BRANCH_LEN];
  if (tix_git_current_branch(current, sizeof(current)) != TIX_OK) {
    return 1;
  }
  return strcmp(ticket->branch, current) == 0;
}

static tix_err_t task_add(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 1) {
    fprintf(stderr, "usage: tix task add '<json>'\n");
    return TIX_ERR_INVALID_ARG;
  }

  const char *input = argv[0];
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line(input, &obj);
  if (err != TIX_OK) {
    fprintf(stderr, "error: invalid JSON: %s\n", tix_strerror(err));
    return err;
  }

  tix_ticket_t ticket;
  tix_ticket_init(&ticket);
  ticket.type = TIX_TICKET_TASK;
  ticket.created_at = (i64)time(NULL);
  ticket.updated_at = ticket.created_at;

  err = tix_ticket_gen_id(TIX_TICKET_TASK, ticket.id, sizeof(ticket.id));
  if (err != TIX_OK) { return err; }

  /* name is required for tasks */
  const char *name = tix_json_get_str(&obj, "name");
  if (name == NULL || name[0] == '\0') {
    fprintf(stderr, "error: task requires a non-empty 'name' field\n");
    return TIX_ERR_VALIDATION;
  }
  tix_ticket_set_name(&ticket, name);

  const char *spec = tix_json_get_str(&obj, "spec");
  if (spec != NULL) { tix_ticket_set_spec(&ticket, spec); }

  const char *notes = tix_json_get_str(&obj, "notes");
  if (notes != NULL) {
    snprintf(ticket.notes, TIX_MAX_DESC_LEN, "%s", notes);
  }

  /* acceptance criteria - warn if missing */
  const char *accept = tix_json_get_str(&obj, "accept");
  if (accept != NULL && accept[0] != '\0') {
    snprintf(ticket.accept, TIX_MAX_DESC_LEN, "%s", accept);
  } else {
    TIX_WARN("task %s has no acceptance criteria", ticket.id);
  }

  /* validate priority string */
  const char *priority = tix_json_get_str(&obj, "priority");
  if (priority != NULL && priority[0] != '\0') {
    tix_priority_e p = tix_priority_from_str(priority);
    if (p == TIX_PRIORITY_NONE && strcmp(priority, "none") != 0) {
      fprintf(stderr, "error: invalid priority '%s' "
              "(must be high, medium, low, or none)\n", priority);
      return TIX_ERR_VALIDATION;
    }
    ticket.priority = p;
  }

  /* validate parent reference */
  const char *parent = tix_json_get_str(&obj, "parent");
  if (parent != NULL && parent[0] != '\0') {
    if (!tix_is_valid_ticket_id(parent)) {
      fprintf(stderr, "error: invalid parent ID format '%s'\n", parent);
      return TIX_ERR_VALIDATION;
    }
    if (!tix_db_ticket_exists(&ctx->db, parent)) {
      fprintf(stderr, "error: parent task %s does not exist\n", parent);
      return TIX_ERR_NOT_FOUND;
    }
    snprintf(ticket.parent, TIX_MAX_ID_LEN, "%s", parent);
  }

  /* validate created_from reference */
  const char *cf = tix_json_get_str(&obj, "created_from");
  if (cf != NULL && cf[0] != '\0') {
    if (!tix_is_valid_ticket_id(cf)) {
      fprintf(stderr, "error: invalid created_from ID format '%s'\n", cf);
      return TIX_ERR_VALIDATION;
    }
    if (!tix_db_ticket_exists(&ctx->db, cf)) {
      fprintf(stderr, "error: created_from issue %s does not exist\n", cf);
      return TIX_ERR_NOT_FOUND;
    }
    snprintf(ticket.created_from, TIX_MAX_ID_LEN, "%s", cf);
  }

  /* validate supersedes reference */
  const char *ss = tix_json_get_str(&obj, "supersedes");
  if (ss != NULL && ss[0] != '\0') {
    if (!tix_is_valid_ticket_id(ss)) {
      fprintf(stderr, "error: invalid supersedes ID format '%s'\n", ss);
      return TIX_ERR_VALIDATION;
    }
    if (!tix_db_ticket_exists(&ctx->db, ss)) {
      fprintf(stderr, "error: supersedes task %s does not exist\n", ss);
      return TIX_ERR_NOT_FOUND;
    }
    snprintf(ticket.supersedes, TIX_MAX_ID_LEN, "%s", ss);
  }

  /* labels - parse from JSON array */
  for (u32 i = 0; i < obj.field_count; i++) {
    if (strcmp(obj.fields[i].key, "labels") != 0) { continue; }
    if (obj.fields[i].type != TIX_JSON_ARRAY) { continue; }
    for (u32 j = 0; j < obj.fields[i].arr_count; j++) {
      const char *label = obj.fields[i].arr_vals[j];
      if (label[0] == '\0') { continue; }
      tix_err_t lerr = tix_ticket_add_label(&ticket, label);
      if (lerr == TIX_ERR_OVERFLOW) {
        fprintf(stderr, "error: too many labels (max %d)\n",
                TIX_MAX_LABELS);
        return TIX_ERR_OVERFLOW;
      }
    }
    break;
  }

  /* deps - validate each exists, is a task, and is not a duplicate */
  for (u32 i = 0; i < obj.field_count; i++) {
    if (strcmp(obj.fields[i].key, "deps") != 0) { continue; }
    if (obj.fields[i].type != TIX_JSON_ARRAY) { continue; }
    for (u32 j = 0; j < obj.fields[i].arr_count; j++) {
      const char *dep_id = obj.fields[i].arr_vals[j];
      if (!tix_is_valid_ticket_id(dep_id)) {
        fprintf(stderr, "error: invalid dependency ID format '%s'\n",
                dep_id);
        return TIX_ERR_VALIDATION;
      }
      if (tix_has_duplicate_dep(&ticket, dep_id)) {
        fprintf(stderr, "error: duplicate dependency '%s'\n", dep_id);
        return TIX_ERR_DUPLICATE;
      }
      tix_ticket_t dep_ticket;
      if (tix_db_get_ticket(&ctx->db, dep_id, &dep_ticket) != TIX_OK) {
        fprintf(stderr, "error: dependency %s does not exist\n", dep_id);
        return TIX_ERR_NOT_FOUND;
      }
      if (dep_ticket.type != TIX_TICKET_TASK) {
        fprintf(stderr, "error: dependency %s is not a task\n", dep_id);
        return TIX_ERR_VALIDATION;
      }
      tix_ticket_add_dep(&ticket, dep_id);
    }
    break;
  }

  /* auto-fill author from git user.name */
  tix_git_user_name(ticket.author, sizeof(ticket.author));

  /* stamp current branch on creation */
  tix_git_current_branch(ticket.branch, sizeof(ticket.branch));

  /* write to plan.jsonl and db */
  err = tix_plan_append_ticket(ctx->plan_path, &ticket);
  if (err != TIX_OK) { return err; }

  err = tix_db_upsert_ticket(&ctx->db, &ticket);
  if (err != TIX_OK) { return err; }

  tix_search_index_ticket(&ctx->db, &ticket);

  char esc_name[TIX_MAX_NAME_LEN * 2];
  tix_json_escape(ticket.name, esc_name, sizeof(esc_name));
  printf("{\"id\":\"%s\",\"name\":\"%s\"}\n", ticket.id, esc_name);
  return TIX_OK;
}

static tix_err_t task_done(tix_ctx_t *ctx, int argc, char **argv) {
  char id[TIX_MAX_ID_LEN];

  if (argc >= 1) {
    snprintf(id, sizeof(id), "%s", argv[0]);
  } else {
    /* find first pending task */
    tix_ticket_t tickets[1];
    u32 count = 0;
    tix_err_t err = tix_db_list_tickets(&ctx->db, TIX_TICKET_TASK,
                                         TIX_STATUS_PENDING,
                                         tickets, &count, 1);
    if (err != TIX_OK || count == 0) {
      fprintf(stderr, "error: no pending tasks\n");
      return TIX_ERR_NOT_FOUND;
    }
    snprintf(id, sizeof(id), "%s", tickets[0].id);
  }

  tix_ticket_t ticket;
  tix_err_t err = tix_db_get_ticket(&ctx->db, id, &ticket);
  if (err != TIX_OK) {
    fprintf(stderr, "error: task %s not found\n", id);
    return err;
  }

  /* validate: must be a task */
  if (ticket.type != TIX_TICKET_TASK) {
    fprintf(stderr, "error: %s is not a task\n", id);
    return TIX_ERR_STATE;
  }

  /* validate: must be pending to mark done */
  if (ticket.status != TIX_STATUS_PENDING) {
    fprintf(stderr, "error: task %s is already %s, cannot mark done\n",
            id, tix_status_str(ticket.status));
    return TIX_ERR_STATE;
  }

  if (!check_branch_scope(&ticket)) {
    fprintf(stderr, "error: task %s belongs to branch '%s', "
            "not current branch\n", id, ticket.branch);
    return TIX_ERR_INVALID_ARG;
  }

  ticket.status = TIX_STATUS_DONE;
  ticket.updated_at = (i64)time(NULL);
  tix_git_rev_parse_head(ticket.done_at, sizeof(ticket.done_at));
  tix_git_current_branch(ticket.branch, sizeof(ticket.branch));
  tix_timestamp_iso8601(ticket.completed_at, sizeof(ticket.completed_at));

  err = tix_db_upsert_ticket(&ctx->db, &ticket);
  if (err != TIX_OK) { return err; }

  err = tix_plan_append_ticket(ctx->plan_path, &ticket);
  if (err != TIX_OK) { return err; }

  printf("{\"id\":\"%s\",\"status\":\"done\",\"done_at\":\"%s\"}\n",
         id, ticket.done_at);
  return TIX_OK;
}

static tix_err_t task_accept(tix_ctx_t *ctx, int argc, char **argv) {
  char id[TIX_MAX_ID_LEN];

  if (argc >= 1) {
    snprintf(id, sizeof(id), "%s", argv[0]);
  } else {
    tix_ticket_t tickets[1];
    u32 count = 0;
    tix_db_list_tickets(&ctx->db, TIX_TICKET_TASK, TIX_STATUS_DONE,
                        tickets, &count, 1);
    if (count == 0) {
      fprintf(stderr, "error: no done tasks to accept\n");
      return TIX_ERR_NOT_FOUND;
    }
    snprintf(id, sizeof(id), "%s", tickets[0].id);
  }

  tix_ticket_t ticket;
  tix_err_t err = tix_db_get_ticket(&ctx->db, id, &ticket);
  if (err != TIX_OK) {
    fprintf(stderr, "error: task %s not found\n", id);
    return err;
  }

  /* validate: must be a task */
  if (ticket.type != TIX_TICKET_TASK) {
    fprintf(stderr, "error: %s is not a task\n", id);
    return TIX_ERR_STATE;
  }

  /* validate: must be done to accept */
  if (ticket.status != TIX_STATUS_DONE) {
    fprintf(stderr, "error: task %s is %s, must be done to accept\n",
            id, tix_status_str(ticket.status));
    return TIX_ERR_STATE;
  }

  if (!check_branch_scope(&ticket)) {
    fprintf(stderr, "error: task %s belongs to branch '%s', "
            "not current branch\n", id, ticket.branch);
    return TIX_ERR_INVALID_ARG;
  }

  /* create tombstone */
  tix_tombstone_t ts;
  memset(&ts, 0, sizeof(ts));
  snprintf(ts.id, sizeof(ts.id), "%s", ticket.id);
  snprintf(ts.done_at, sizeof(ts.done_at), "%s", ticket.done_at);
  snprintf(ts.name, sizeof(ts.name), "%s", ticket.name);
  ts.is_accept = 1;
  ts.timestamp = (i64)time(NULL);

  err = tix_db_upsert_tombstone(&ctx->db, &ts);
  if (err != TIX_OK) { return err; }

  err = tix_db_delete_ticket(&ctx->db, id);
  if (err != TIX_OK) { return err; }

  err = tix_plan_append_tombstone(ctx->plan_path, &ts);
  if (err != TIX_OK) { return err; }

  printf("{\"id\":\"%s\",\"status\":\"accepted\"}\n", id);
  return TIX_OK;
}

static tix_err_t task_reject(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 2) {
    fprintf(stderr, "usage: tix task reject <id> \"reason\"\n");
    return TIX_ERR_INVALID_ARG;
  }

  const char *id = argv[0];
  const char *reason = argv[1];

  tix_ticket_t ticket;
  tix_err_t err = tix_db_get_ticket(&ctx->db, id, &ticket);
  if (err != TIX_OK) {
    fprintf(stderr, "error: task %s not found\n", id);
    return err;
  }

  /* validate: must be a task */
  if (ticket.type != TIX_TICKET_TASK) {
    fprintf(stderr, "error: %s is not a task\n", id);
    return TIX_ERR_STATE;
  }

  /* validate: must be done to reject */
  if (ticket.status != TIX_STATUS_DONE) {
    fprintf(stderr, "error: task %s is %s, must be done to reject\n",
            id, tix_status_str(ticket.status));
    return TIX_ERR_STATE;
  }

  /* validate: reason must not be empty */
  if (reason[0] == '\0') {
    fprintf(stderr, "error: reject reason must not be empty\n");
    return TIX_ERR_VALIDATION;
  }

  if (!check_branch_scope(&ticket)) {
    fprintf(stderr, "error: task %s belongs to branch '%s', "
            "not current branch\n", id, ticket.branch);
    return TIX_ERR_INVALID_ARG;
  }

  /* create reject tombstone */
  tix_tombstone_t ts;
  memset(&ts, 0, sizeof(ts));
  snprintf(ts.id, sizeof(ts.id), "%s", ticket.id);
  snprintf(ts.done_at, sizeof(ts.done_at), "%s", ticket.done_at);
  snprintf(ts.name, sizeof(ts.name), "%s", ticket.name);
  snprintf(ts.reason, sizeof(ts.reason), "%s", reason);
  ts.is_accept = 0;
  ts.timestamp = (i64)time(NULL);

  err = tix_db_upsert_tombstone(&ctx->db, &ts);
  if (err != TIX_OK) { return err; }

  /* reset task to pending */
  ticket.status = TIX_STATUS_PENDING;
  ticket.done_at[0] = '\0';
  ticket.updated_at = (i64)time(NULL);

  err = tix_db_upsert_ticket(&ctx->db, &ticket);
  if (err != TIX_OK) { return err; }

  err = tix_plan_append_tombstone(ctx->plan_path, &ts);
  if (err != TIX_OK) { return err; }

  err = tix_plan_append_ticket(ctx->plan_path, &ticket);
  if (err != TIX_OK) { return err; }

  printf("{\"id\":\"%s\",\"status\":\"rejected\"}\n", id);
  return TIX_OK;
}

static tix_err_t task_delete(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 1) {
    fprintf(stderr, "usage: tix task delete <id>\n");
    return TIX_ERR_INVALID_ARG;
  }

  const char *id = argv[0];

  /* validate: check that the task exists first */
  tix_ticket_t ticket;
  tix_err_t err = tix_db_get_ticket(&ctx->db, id, &ticket);
  if (err != TIX_OK) {
    fprintf(stderr, "error: task %s not found\n", id);
    return err;
  }

  if (!check_branch_scope(&ticket)) {
    fprintf(stderr, "error: task %s belongs to branch '%s', "
            "not current branch\n", id, ticket.branch);
    return TIX_ERR_INVALID_ARG;
  }

  /* prevent deleting a task that other tasks depend on */
  if (has_dependents(&ctx->db, id)) {
    fprintf(stderr,
            "error: cannot delete %s, other tasks depend on it\n", id);
    return TIX_ERR_DEPENDENCY;
  }

  err = tix_db_delete_ticket(&ctx->db, id);
  if (err != TIX_OK) {
    fprintf(stderr, "error: failed to delete task %s\n", id);
    return err;
  }

  err = tix_plan_append_delete(ctx->plan_path, id);
  if (err != TIX_OK) { return err; }

  printf("{\"id\":\"%s\",\"status\":\"deleted\"}\n", id);
  return TIX_OK;
}

static tix_err_t task_update(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 2) {
    fprintf(stderr, "usage: tix task update <id> '<json>'\n");
    return TIX_ERR_INVALID_ARG;
  }

  const char *id = argv[0];
  const char *input = argv[1];

  tix_ticket_t ticket;
  tix_err_t err = tix_db_get_ticket(&ctx->db, id, &ticket);
  if (err != TIX_OK) {
    fprintf(stderr, "error: ticket %s not found\n", id);
    return err;
  }

  tix_json_obj_t obj;
  err = tix_json_parse_line(input, &obj);
  if (err != TIX_OK) {
    fprintf(stderr, "error: invalid JSON: %s\n", tix_strerror(err));
    return err;
  }

  /* merge provided fields onto existing ticket */
  const char *v;
  v = tix_json_get_str(&obj, "author");
  if (v != NULL) { snprintf(ticket.author, sizeof(ticket.author), "%s", v); }
  v = tix_json_get_str(&obj, "completed_at");
  if (v != NULL) {
    snprintf(ticket.completed_at, sizeof(ticket.completed_at), "%s", v);
  }
  v = tix_json_get_str(&obj, "model");
  if (v != NULL) { snprintf(ticket.model, sizeof(ticket.model), "%s", v); }
  v = tix_json_get_str(&obj, "notes");
  if (v != NULL) { snprintf(ticket.notes, TIX_MAX_DESC_LEN, "%s", v); }
  v = tix_json_get_str(&obj, "accept");
  if (v != NULL) { snprintf(ticket.accept, TIX_MAX_DESC_LEN, "%s", v); }
  v = tix_json_get_str(&obj, "kill_reason");
  if (v != NULL) {
    snprintf(ticket.kill_reason, TIX_MAX_KEYWORD_LEN, "%s", v);
  }

  if (tix_json_has_key(&obj, "cost")) {
    ticket.cost = tix_json_get_double(&obj, "cost", 0.0);
  }
  if (tix_json_has_key(&obj, "tokens_in")) {
    ticket.tokens_in = tix_json_get_num(&obj, "tokens_in", 0);
  }
  if (tix_json_has_key(&obj, "tokens_out")) {
    ticket.tokens_out = tix_json_get_num(&obj, "tokens_out", 0);
  }
  if (tix_json_has_key(&obj, "iterations")) {
    ticket.iterations = (i32)tix_json_get_num(&obj, "iterations", 0);
  }
  if (tix_json_has_key(&obj, "retries")) {
    ticket.retries = (i32)tix_json_get_num(&obj, "retries", 0);
  }
  if (tix_json_has_key(&obj, "kill_count")) {
    ticket.kill_count = (i32)tix_json_get_num(&obj, "kill_count", 0);
  }

  /* labels - replace if provided */
  for (u32 i = 0; i < obj.field_count; i++) {
    if (strcmp(obj.fields[i].key, "labels") != 0) { continue; }
    if (obj.fields[i].type != TIX_JSON_ARRAY) { continue; }
    ticket.label_count = 0;
    for (u32 j = 0; j < obj.fields[i].arr_count; j++) {
      const char *label = obj.fields[i].arr_vals[j];
      if (label[0] == '\0') { continue; }
      tix_ticket_add_label(&ticket, label);
    }
    break;
  }

  ticket.updated_at = (i64)time(NULL);

  err = tix_db_upsert_ticket(&ctx->db, &ticket);
  if (err != TIX_OK) { return err; }

  err = tix_plan_append_ticket(ctx->plan_path, &ticket);
  if (err != TIX_OK) { return err; }

  printf("{\"id\":\"%s\",\"status\":\"updated\"}\n", id);
  return TIX_OK;
}

static tix_err_t task_prioritize(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 2) {
    fprintf(stderr,
            "usage: tix task prioritize <id> <high|medium|low>\n");
    return TIX_ERR_INVALID_ARG;
  }

  const char *id = argv[0];
  const char *prio_str = argv[1];

  /* validate priority string */
  tix_priority_e prio = tix_priority_from_str(prio_str);
  if (prio == TIX_PRIORITY_NONE && strcmp(prio_str, "none") != 0) {
    fprintf(stderr, "error: invalid priority '%s' "
            "(must be high, medium, low, or none)\n", prio_str);
    return TIX_ERR_VALIDATION;
  }

  tix_ticket_t ticket;
  tix_err_t err = tix_db_get_ticket(&ctx->db, id, &ticket);
  if (err != TIX_OK) {
    fprintf(stderr, "error: task %s not found\n", id);
    return err;
  }

  ticket.priority = prio;
  ticket.updated_at = (i64)time(NULL);

  err = tix_db_upsert_ticket(&ctx->db, &ticket);
  if (err != TIX_OK) { return err; }

  err = tix_plan_append_ticket(ctx->plan_path, &ticket);
  if (err != TIX_OK) { return err; }

  printf("{\"id\":\"%s\",\"priority\":\"%s\"}\n",
         id, tix_priority_str(prio));
  return TIX_OK;
}

tix_err_t tix_cmd_task(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 1) {
    fprintf(stderr,
            "usage: tix task "
            "<add|done|accept|reject|delete|prioritize|update>\n");
    return TIX_ERR_INVALID_ARG;
  }

  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  const char *sub = argv[0];
  if (strcmp(sub, "add") == 0) {
    return task_add(ctx, argc - 1, argv + 1);
  }
  if (strcmp(sub, "done") == 0) {
    return task_done(ctx, argc - 1, argv + 1);
  }
  if (strcmp(sub, "accept") == 0) {
    return task_accept(ctx, argc - 1, argv + 1);
  }
  if (strcmp(sub, "reject") == 0) {
    return task_reject(ctx, argc - 1, argv + 1);
  }
  if (strcmp(sub, "delete") == 0) {
    return task_delete(ctx, argc - 1, argv + 1);
  }
  if (strcmp(sub, "prioritize") == 0) {
    return task_prioritize(ctx, argc - 1, argv + 1);
  }
  if (strcmp(sub, "update") == 0) {
    return task_update(ctx, argc - 1, argv + 1);
  }

  fprintf(stderr, "error: unknown task subcommand: %s\n", sub);
  return TIX_ERR_INVALID_ARG;
}
