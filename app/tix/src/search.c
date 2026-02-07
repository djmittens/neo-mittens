#include "search.h"
#include "log.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>

static const char *STOP_WORDS[] = {
  "the", "a", "an", "is", "are", "was", "were", "be", "to", "of",
  "and", "in", "for", "on", "with", "at", "by", "it", "this", "that",
  "from", "or", "as", "not", "but", "if", "has", "have", "had", "do",
  NULL
};

static int is_stop_word(const char *word) {
  for (int i = 0; STOP_WORDS[i] != NULL; i++) {
    if (strcmp(word, STOP_WORDS[i]) == 0) { return 1; }
  }
  return 0;
}

static void to_lower(char *s) {
  for (; *s != '\0'; s++) {
    *s = (char)tolower((unsigned char)*s);
  }
}

static void index_text(tix_db_t *db, const char *ticket_id,
                       const char *text, double weight) {
  if (text == NULL || text[0] == '\0') { return; }

  char buf[TIX_MAX_DESC_LEN];
  snprintf(buf, sizeof(buf), "%s", text);
  to_lower(buf);

  const char *sql =
    "INSERT OR REPLACE INTO keywords (ticket_id, keyword, weight) "
    "VALUES (?, ?, MAX(COALESCE("
    "  (SELECT weight FROM keywords WHERE ticket_id=? AND keyword=?), 0"
    "), ?))";

  char *saveptr = NULL;
  static const char delims[] = " \t\n\r.,;:!?()[]{}\"'`/\\-_=+<>@#$%^&*~|";
  char *token = strtok_r(buf, delims, &saveptr);
  u32 count = 0;

  while (token != NULL && count < TIX_MAX_KEYWORDS) {
    if (strlen(token) >= 2 && !is_stop_word(token)) {
      sqlite3_stmt *stmt = NULL;
      int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
      if (rc == SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, ticket_id, -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 2, token, -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(stmt, 3, ticket_id, -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 4, token, -1, SQLITE_TRANSIENT);
        sqlite3_bind_double(stmt, 5, weight);
        sqlite3_step(stmt);
        sqlite3_finalize(stmt);
        count++;
      }
    }
    token = strtok_r(NULL, delims, &saveptr);
  }
}

tix_err_t tix_search_index_ticket(tix_db_t *db, const tix_ticket_t *ticket) {
  if (db == NULL || ticket == NULL) { return TIX_ERR_INVALID_ARG; }

  /* clear old keywords for this ticket */
  const char *del = "DELETE FROM keywords WHERE ticket_id=?";
  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, del, -1, &stmt, NULL);
  if (rc == SQLITE_OK) {
    sqlite3_bind_text(stmt, 1, ticket->id, -1, SQLITE_STATIC);
    sqlite3_step(stmt);
    sqlite3_finalize(stmt);
  }

  index_text(db, ticket->id, ticket->name, 3.0);
  index_text(db, ticket->id, ticket->accept, 2.0);
  index_text(db, ticket->id, ticket->notes, 1.0);

  return TIX_OK;
}

tix_err_t tix_search_query(tix_db_t *db, const char *query,
                           tix_search_result_t *results,
                           u32 *count, u32 max) {
  if (db == NULL || query == NULL || results == NULL || count == NULL) {
    return TIX_ERR_INVALID_ARG;
  }

  *count = 0;

  /* tokenize query */
  char qbuf[TIX_MAX_QUERY_LEN];
  snprintf(qbuf, sizeof(qbuf), "%s", query);
  to_lower(qbuf);

  char tokens[16][TIX_MAX_KEYWORD_LEN];
  u32 token_count = 0;
  char *saveptr = NULL;
  char *tok = strtok_r(qbuf, " \t", &saveptr);
  while (tok != NULL && token_count < 16) {
    if (!is_stop_word(tok) && strlen(tok) >= 2) {
      snprintf(tokens[token_count], TIX_MAX_KEYWORD_LEN, "%s", tok);
      token_count++;
    }
    tok = strtok_r(NULL, " \t", &saveptr);
  }

  if (token_count == 0) { return TIX_OK; }

  /* query: find tickets matching any keyword, sum weights */
  const char *sql =
    "SELECT k.ticket_id, t.name, SUM(k.weight) as score "
    "FROM keywords k "
    "JOIN tickets t ON k.ticket_id = t.id "
    "WHERE k.keyword LIKE ? "
    "GROUP BY k.ticket_id "
    "ORDER BY score DESC "
    "LIMIT ?";

  for (u32 ti = 0; ti < token_count && *count < max; ti++) {
    char pattern[TIX_MAX_KEYWORD_LEN + 4];
    snprintf(pattern, sizeof(pattern), "%%%s%%", tokens[ti]);

    sqlite3_stmt *stmt = NULL;
    int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
    if (rc != SQLITE_OK) { continue; }

    sqlite3_bind_text(stmt, 1, pattern, -1, SQLITE_STATIC);
    sqlite3_bind_int(stmt, 2, (int)(max - *count));

    while (sqlite3_step(stmt) == SQLITE_ROW && *count < max) {
      tix_search_result_t *r = &results[*count];
      memset(r, 0, sizeof(*r));

      const char *id = (const char *)sqlite3_column_text(stmt, 0);
      if (id != NULL) { snprintf(r->id, TIX_MAX_ID_LEN, "%s", id); }

      const char *name = (const char *)sqlite3_column_text(stmt, 1);
      if (name != NULL) { snprintf(r->name, TIX_MAX_NAME_LEN, "%s", name); }

      r->score = sqlite3_column_double(stmt, 2);

      snprintf(r->keywords[0], TIX_MAX_KEYWORD_LEN, "%s", tokens[ti]);
      r->keyword_count = 1;

      (*count)++;
    }
    sqlite3_finalize(stmt);
  }

  return TIX_OK;
}

tix_err_t tix_search_keyword_cloud(tix_db_t *db, char *buf, sz buf_len) {
  if (db == NULL || buf == NULL) { return TIX_ERR_INVALID_ARG; }

  const char *sql =
    "SELECT keyword, SUM(weight) as total "
    "FROM keywords GROUP BY keyword ORDER BY total DESC LIMIT 50";

  sqlite3_stmt *stmt = NULL;
  int rc = sqlite3_prepare_v2(db->handle, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK) {
    snprintf(buf, buf_len, "{}");
    return TIX_OK;
  }

  char *p = buf;
  char *end = buf + buf_len;
  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "{");

  int first = 1;
  while (sqlite3_step(stmt) == SQLITE_ROW) {
    const char *kw = (const char *)sqlite3_column_text(stmt, 0);
    double total = sqlite3_column_double(stmt, 1);
    if (kw == NULL) { continue; }

    if (!first) { TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, ","); }
    TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "\"%s\":%.0f", kw, total);
    first = 0;
  }

  TIX_BUF_PRINTF(p, end, TIX_ERR_OVERFLOW, "}");
  sqlite3_finalize(stmt);
  return TIX_OK;
}
