#include "cmd.h"
#include "git.h"
#include "json.h"
#include "search.h"
#include "log.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

static tix_err_t issue_add(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 1) {
    fprintf(stderr, "usage: tix issue add '<json>'\n");
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
  ticket.type = TIX_TICKET_ISSUE;
  ticket.created_at = (i64)time(NULL);
  ticket.updated_at = ticket.created_at;

  err = tix_ticket_gen_id(TIX_TICKET_ISSUE, ticket.id, sizeof(ticket.id));
  if (err != TIX_OK) { return err; }

  /* desc is required for issues */
  const char *desc = tix_json_get_str(&obj, "desc");
  if (desc == NULL || desc[0] == '\0') {
    fprintf(stderr, "error: issue requires a non-empty 'desc' field\n");
    return TIX_ERR_VALIDATION;
  }
  tix_ticket_set_name(&ticket, desc);

  const char *spec = tix_json_get_str(&obj, "spec");
  if (spec != NULL) { tix_ticket_set_spec(&ticket, spec); }

  /* auto-fill author from git user.name */
  tix_git_user_name(ticket.author, sizeof(ticket.author));

  err = tix_plan_append_ticket(ctx->plan_path, &ticket);
  if (err != TIX_OK) { return err; }

  err = tix_db_upsert_ticket(&ctx->db, &ticket);
  if (err != TIX_OK) { return err; }

  tix_search_index_ticket(&ctx->db, &ticket);

  char esc_desc[TIX_MAX_NAME_LEN * 2];
  tix_json_escape(ticket.name, esc_desc, sizeof(esc_desc));
  printf("{\"id\":\"%s\",\"desc\":\"%s\"}\n", ticket.id, esc_desc);
  return TIX_OK;
}

static tix_err_t issue_done(tix_ctx_t *ctx, int argc, char **argv) {
  char id[TIX_MAX_ID_LEN];

  if (argc >= 1) {
    snprintf(id, sizeof(id), "%s", argv[0]);
  } else {
    tix_ticket_t tickets[1];
    u32 count = 0;
    tix_db_list_tickets(&ctx->db, TIX_TICKET_ISSUE, TIX_STATUS_PENDING,
                        tickets, &count, 1);
    if (count == 0) {
      fprintf(stderr, "error: no pending issues\n");
      return TIX_ERR_NOT_FOUND;
    }
    snprintf(id, sizeof(id), "%s", tickets[0].id);
  }

  /* Mark as DELETED with resolved_at instead of hard-deleting */
  tix_ticket_t ticket;
  tix_err_t err = tix_db_get_ticket(&ctx->db, id, &ticket);
  if (err != TIX_OK) { return err; }

  ticket.status = TIX_STATUS_DELETED;
  ticket.resolved_at = (i64)time(NULL);
  err = tix_db_upsert_ticket(&ctx->db, &ticket);
  if (err != TIX_OK) { return err; }

  err = tix_plan_append_delete(ctx->plan_path, id);
  if (err != TIX_OK) { return err; }

  printf("{\"id\":\"%s\",\"status\":\"resolved\"}\n", id);
  return TIX_OK;
}

static tix_err_t issue_done_all(tix_ctx_t *ctx) {
  tix_ticket_t tickets[TIX_MAX_BATCH];
  u32 count = 0;

  tix_err_t err = tix_db_list_tickets(&ctx->db, TIX_TICKET_ISSUE,
                                       TIX_STATUS_PENDING,
                                       tickets, &count, TIX_MAX_BATCH);
  if (err != TIX_OK) { return err; }

  i64 now = (i64)time(NULL);
  for (u32 i = 0; i < count; i++) {
    tickets[i].status = TIX_STATUS_DELETED;
    tickets[i].resolved_at = now;
    tix_db_upsert_ticket(&ctx->db, &tickets[i]);
    tix_plan_append_delete(ctx->plan_path, tickets[i].id);
  }

  printf("{\"resolved\":%u}\n", count);
  return TIX_OK;
}

static tix_err_t issue_done_ids(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 1) {
    fprintf(stderr, "usage: tix issue done-ids <id1> <id2> ...\n");
    return TIX_ERR_INVALID_ARG;
  }

  i64 now = (i64)time(NULL);
  u32 resolved = 0;
  for (int i = 0; i < argc; i++) {
    tix_ticket_t ticket;
    if (tix_db_get_ticket(&ctx->db, argv[i], &ticket) == TIX_OK) {
      ticket.status = TIX_STATUS_DELETED;
      ticket.resolved_at = now;
      tix_db_upsert_ticket(&ctx->db, &ticket);
      tix_plan_append_delete(ctx->plan_path, argv[i]);
      resolved++;
    }
  }

  printf("{\"resolved\":%u}\n", resolved);
  return TIX_OK;
}

tix_err_t tix_cmd_issue(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 1) {
    fprintf(stderr, "usage: tix issue <add|done|done-all|done-ids>\n");
    return TIX_ERR_INVALID_ARG;
  }

  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  const char *sub = argv[0];
  if (strcmp(sub, "add") == 0)      { return issue_add(ctx, argc - 1, argv + 1); }
  if (strcmp(sub, "done") == 0)     { return issue_done(ctx, argc - 1, argv + 1); }
  if (strcmp(sub, "done-all") == 0) { return issue_done_all(ctx); }
  if (strcmp(sub, "done-ids") == 0) { return issue_done_ids(ctx, argc - 1, argv + 1); }

  fprintf(stderr, "error: unknown issue subcommand: %s\n", sub);
  return TIX_ERR_INVALID_ARG;
}
