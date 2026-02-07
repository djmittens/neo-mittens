#include "cmd.h"
#include "git.h"
#include "json.h"
#include "search.h"
#include "log.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

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

  const char *name = tix_json_get_str(&obj, "name");
  if (name != NULL) { tix_ticket_set_name(&ticket, name); }

  const char *spec = tix_json_get_str(&obj, "spec");
  if (spec != NULL) { tix_ticket_set_spec(&ticket, spec); }

  const char *notes = tix_json_get_str(&obj, "notes");
  if (notes != NULL) { snprintf(ticket.notes, TIX_MAX_DESC_LEN, "%s", notes); }

  const char *accept = tix_json_get_str(&obj, "accept");
  if (accept != NULL) { snprintf(ticket.accept, TIX_MAX_DESC_LEN, "%s", accept); }

  const char *priority = tix_json_get_str(&obj, "priority");
  ticket.priority = tix_priority_from_str(priority);

  const char *parent = tix_json_get_str(&obj, "parent");
  if (parent != NULL) { snprintf(ticket.parent, TIX_MAX_ID_LEN, "%s", parent); }

  const char *cf = tix_json_get_str(&obj, "created_from");
  if (cf != NULL) { snprintf(ticket.created_from, TIX_MAX_ID_LEN, "%s", cf); }

  /* deps */
  for (u32 i = 0; i < obj.field_count; i++) {
    if (strcmp(obj.fields[i].key, "deps") != 0) { continue; }
    if (obj.fields[i].type != TIX_JSON_ARRAY) { continue; }
    for (u32 j = 0; j < obj.fields[i].arr_count; j++) {
      tix_ticket_add_dep(&ticket, obj.fields[i].arr_vals[j]);
    }
    break;
  }

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

  ticket.status = TIX_STATUS_DONE;
  ticket.updated_at = (i64)time(NULL);
  tix_git_rev_parse_head(ticket.done_at, sizeof(ticket.done_at));
  tix_git_current_branch(ticket.branch, sizeof(ticket.branch));

  err = tix_db_upsert_ticket(&ctx->db, &ticket);
  if (err != TIX_OK) { return err; }

  err = tix_plan_rewrite(ctx->plan_path, &ctx->db);
  if (err != TIX_OK) { return err; }

  char msg[TIX_MAX_NAME_LEN + 32];
  snprintf(msg, sizeof(msg), "tix: task done %s", id);
  tix_git_commit(msg, ctx->plan_path);

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

  err = tix_plan_rewrite(ctx->plan_path, &ctx->db);
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

  err = tix_plan_rewrite(ctx->plan_path, &ctx->db);
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
  tix_err_t err = tix_db_delete_ticket(&ctx->db, id);
  if (err != TIX_OK) {
    fprintf(stderr, "error: task %s not found\n", id);
    return err;
  }

  err = tix_plan_rewrite(ctx->plan_path, &ctx->db);
  if (err != TIX_OK) { return err; }

  printf("{\"id\":\"%s\",\"status\":\"deleted\"}\n", id);
  return TIX_OK;
}

static tix_err_t task_prioritize(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 2) {
    fprintf(stderr, "usage: tix task prioritize <id> <high|medium|low>\n");
    return TIX_ERR_INVALID_ARG;
  }

  const char *id = argv[0];
  tix_priority_e prio = tix_priority_from_str(argv[1]);

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

  err = tix_plan_rewrite(ctx->plan_path, &ctx->db);
  if (err != TIX_OK) { return err; }

  printf("{\"id\":\"%s\",\"priority\":\"%s\"}\n", id, tix_priority_str(prio));
  return TIX_OK;
}

tix_err_t tix_cmd_task(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 1) {
    fprintf(stderr, "usage: tix task <add|done|accept|reject|delete|prioritize>\n");
    return TIX_ERR_INVALID_ARG;
  }

  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  const char *sub = argv[0];
  if (strcmp(sub, "add") == 0)        { return task_add(ctx, argc - 1, argv + 1); }
  if (strcmp(sub, "done") == 0)       { return task_done(ctx, argc - 1, argv + 1); }
  if (strcmp(sub, "accept") == 0)     { return task_accept(ctx, argc - 1, argv + 1); }
  if (strcmp(sub, "reject") == 0)     { return task_reject(ctx, argc - 1, argv + 1); }
  if (strcmp(sub, "delete") == 0)     { return task_delete(ctx, argc - 1, argv + 1); }
  if (strcmp(sub, "prioritize") == 0) { return task_prioritize(ctx, argc - 1, argv + 1); }

  fprintf(stderr, "error: unknown task subcommand: %s\n", sub);
  return TIX_ERR_INVALID_ARG;
}
