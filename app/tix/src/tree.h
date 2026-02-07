#pragma once

#include "types.h"
#include "common.h"
#include "db.h"

tix_err_t tix_tree_render(tix_db_t *db, const char *root_id,
                          char *buf, sz buf_len);
tix_err_t tix_tree_render_all(tix_db_t *db, char *buf, sz buf_len);
