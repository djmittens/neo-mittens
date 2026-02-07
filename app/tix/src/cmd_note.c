#include "cmd.h"
#include "json.h"
#include "log.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

static tix_err_t note_add(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 1) {
    fprintf(stderr, "usage: tix note add \"text\"\n");
    return TIX_ERR_INVALID_ARG;
  }

  tix_ticket_t ticket;
  tix_ticket_init(&ticket);
  ticket.type = TIX_TICKET_NOTE;
  ticket.created_at = (i64)time(NULL);
  ticket.updated_at = ticket.created_at;

  tix_err_t err = tix_ticket_gen_id(TIX_TICKET_NOTE, ticket.id,
                                     sizeof(ticket.id));
  if (err != TIX_OK) { return err; }

  /* validate: note text must not be empty */
  if (argv[0][0] == '\0') {
    fprintf(stderr, "error: note requires non-empty text\n");
    return TIX_ERR_VALIDATION;
  }

  tix_ticket_set_name(&ticket, argv[0]);

  err = tix_plan_append_ticket(ctx->plan_path, &ticket);
  if (err != TIX_OK) { return err; }

  err = tix_db_upsert_ticket(&ctx->db, &ticket);
  if (err != TIX_OK) { return err; }

  char esc_text[TIX_MAX_NAME_LEN * 2];
  tix_json_escape(ticket.name, esc_text, sizeof(esc_text));
  printf("{\"id\":\"%s\",\"text\":\"%s\"}\n", ticket.id, esc_text);
  return TIX_OK;
}

static tix_err_t note_list(tix_ctx_t *ctx) {
  tix_ticket_t notes[TIX_MAX_BATCH];
  u32 count = 0;

  tix_err_t err = tix_db_list_tickets(&ctx->db, TIX_TICKET_NOTE,
                                       TIX_STATUS_PENDING,
                                       notes, &count, TIX_MAX_BATCH);
  if (err != TIX_OK) { return err; }

  printf("[");
  for (u32 i = 0; i < count; i++) {
    if (i > 0) { printf(","); }
    char buf[TIX_MAX_LINE_LEN];
    tix_json_write_ticket(&notes[i], buf, sizeof(buf));
    printf("%s", buf);
  }
  printf("]\n");
  return TIX_OK;
}

static tix_err_t note_done(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 1) {
    fprintf(stderr, "usage: tix note done <id>\n");
    return TIX_ERR_INVALID_ARG;
  }

  tix_err_t err = tix_db_delete_ticket(&ctx->db, argv[0]);
  if (err != TIX_OK) { return err; }

  err = tix_plan_append_delete(ctx->plan_path, argv[0]);
  if (err != TIX_OK) { return err; }

  printf("{\"id\":\"%s\",\"status\":\"archived\"}\n", argv[0]);
  return TIX_OK;
}

tix_err_t tix_cmd_note(tix_ctx_t *ctx, int argc, char **argv) {
  if (argc < 1) {
    fprintf(stderr, "usage: tix note <add|list|done>\n");
    return TIX_ERR_INVALID_ARG;
  }

  tix_err_t err = tix_ctx_ensure_cache(ctx);
  if (err != TIX_OK) { return err; }

  const char *sub = argv[0];
  if (strcmp(sub, "add") == 0)  { return note_add(ctx, argc - 1, argv + 1); }
  if (strcmp(sub, "list") == 0) { return note_list(ctx); }
  if (strcmp(sub, "done") == 0) { return note_done(ctx, argc - 1, argv + 1); }

  fprintf(stderr, "error: unknown note subcommand: %s\n", sub);
  return TIX_ERR_INVALID_ARG;
}
