#include "tree.h"
#include "ticket.h"
#include "log.h"

#include <stdio.h>
#include <string.h>

#define TREE_MAX_DEPTH 10
#define TREE_STACK_SIZE 256

typedef struct {
  char id[TIX_MAX_ID_LEN];
  int depth;
  int is_last;
} tree_stack_entry_t;

static tix_err_t render_ticket_line(const tix_ticket_t *t, int depth,
                                    int is_last, int prefix_mask,
                                    char *buf, sz buf_len) {
  char *p = buf;
  char *end = buf + buf_len;

  for (int d = 0; d < depth; d++) {
    if (d == depth - 1) {
      TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "%s",
                     is_last ? "└── " : "├── ");
    } else {
      int has_sibling = (prefix_mask >> d) & 1;
      TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "%s",
                     has_sibling ? "│   " : "    ");
    }
  }

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "%s: %s [%s]",
                 t->id, t->name, tix_status_str(t->status));

  if (t->dep_count > 0 && t->status == TIX_STATUS_PENDING) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, " (deps:");
    for (u32 i = 0; i < t->dep_count; i++) {
      TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, " %s", t->deps[i]);
    }
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, ")");
  }

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "\n");
  return (tix_err_t)(p - buf);
}

tix_err_t tix_tree_render(tix_db_t *db, const char *root_id,
                          char *buf, sz buf_len) {
  if (db == NULL || root_id == NULL || buf == NULL) {
    return TIX_ERR_INVALID_ARG;
  }

  char *p = buf;
  char *end = buf + buf_len;

  tix_ticket_t root;
  tix_err_t err = tix_db_get_ticket(db, root_id, &root);
  if (err != TIX_OK) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "ticket %s not found\n", root_id);
    return TIX_OK;
  }

  /* render root */
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "%s: %s [%s]\n",
                 root.id, root.name, tix_status_str(root.status));

  /* find children (tickets that depend on this one) */
  const char *sql =
    "SELECT ticket_id FROM ticket_deps WHERE dep_id=?";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_OK; }

  sqlite3_bind_text(stmt, 1, root_id, -1, SQLITE_STATIC);

  char children[TIX_MAX_CHILDREN][TIX_MAX_ID_LEN];
  u32 child_count = 0;

  while (sqlite3_step(stmt) == SQLITE_ROW && child_count < TIX_MAX_CHILDREN) {
    const char *cid = (const char *)sqlite3_column_text(stmt, 0);
    if (cid != NULL) {
      snprintf(children[child_count], TIX_MAX_ID_LEN, "%s", cid);
      child_count++;
    }
  }
  sqlite3_finalize(stmt);

  for (u32 i = 0; i < child_count; i++) {
    tix_ticket_t child;
    err = tix_db_get_ticket(db, children[i], &child);
    if (err != TIX_OK) { continue; }

    char line[512];
    int is_last = (i == child_count - 1) ? 1 : 0;
    tix_err_t line_len = render_ticket_line(&child, 1, is_last, 0,
                                             line, sizeof(line));
    if (line_len > 0) {
      TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "%s", line);
    }
  }

  return TIX_OK;
}

tix_err_t tix_tree_render_all(tix_db_t *db, char *buf, sz buf_len) {
  if (db == NULL || buf == NULL) { return TIX_ERR_INVALID_ARG; }

  char *p = buf;
  char *end = buf + buf_len;

  /* find root tickets (no deps) */
  const char *sql =
    "SELECT id FROM tickets WHERE type=0 AND id NOT IN "
    "(SELECT ticket_id FROM ticket_deps) "
    "ORDER BY priority DESC, created_at ASC";

  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) { return TIX_ERR_DB; }

  char roots[TIX_MAX_BATCH][TIX_MAX_ID_LEN];
  u32 root_count = 0;

  while (sqlite3_step(stmt) == SQLITE_ROW && root_count < TIX_MAX_BATCH) {
    const char *id = (const char *)sqlite3_column_text(stmt, 0);
    if (id != NULL) {
      snprintf(roots[root_count], TIX_MAX_ID_LEN, "%s", id);
      root_count++;
    }
  }
  sqlite3_finalize(stmt);

  if (root_count == 0) {
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "(no tasks)\n");
    return TIX_OK;
  }

  for (u32 i = 0; i < root_count; i++) {
    char subtree[TIX_MAX_LINE_LEN * 2];
    tix_err_t err = tix_tree_render(db, roots[i], subtree, sizeof(subtree));
    if (err == TIX_OK) {
      TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "%s", subtree);
    }
    if (i < root_count - 1) {
      TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "\n");
    }
  }

  return TIX_OK;
}
