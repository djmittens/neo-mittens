#pragma once

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "types.h"

#define TIX_UNUSED(x) ((void)(x))

#define TIX_ASSERT(cond, msg)                                          \
  do {                                                                 \
    if (!(cond)) {                                                     \
      fprintf(stderr, "ASSERT FAILED: %s:%d:%s: %s\n",                \
              __FILE__, __LINE__, __func__, (msg));                    \
      abort();                                                         \
    }                                                                  \
  } while (0)

#define TIX_BUF_PRINTF(p, end, overflow_ret, ...)                      \
  do {                                                                 \
    int _n = snprintf((p), (sz)((end) - (p)), __VA_ARGS__);           \
    if (_n < 0 || (p) + _n >= (end)) { return (overflow_ret); }       \
    (p) += _n;                                                         \
  } while (0)

typedef enum {
  TIX_OK = 0,
  TIX_ERR_INVALID_ARG = -1,
  TIX_ERR_NOT_FOUND = -2,
  TIX_ERR_IO = -3,
  TIX_ERR_GIT = -4,
  TIX_ERR_DB = -5,
  TIX_ERR_OVERFLOW = -6,
  TIX_ERR_PARSE = -7,
  TIX_ERR_DUPLICATE = -8,
  TIX_ERR_STATE = -9,
  TIX_ERR_DEPENDENCY = -10,
  TIX_ERR_VALIDATION = -11,
} tix_error_e;

static inline const char *tix_strerror(tix_error_e err) {
  switch (err) {
    case TIX_OK:              return "success";
    case TIX_ERR_INVALID_ARG: return "invalid argument";
    case TIX_ERR_NOT_FOUND:   return "not found";
    case TIX_ERR_IO:          return "I/O error";
    case TIX_ERR_GIT:         return "git error";
    case TIX_ERR_DB:          return "database error";
    case TIX_ERR_OVERFLOW:    return "buffer overflow";
    case TIX_ERR_PARSE:       return "parse error";
    case TIX_ERR_DUPLICATE:   return "duplicate entry";
    case TIX_ERR_STATE:       return "invalid state";
    case TIX_ERR_DEPENDENCY:  return "dependency error";
    case TIX_ERR_VALIDATION:  return "validation error";
  }
  return "unknown error";
}
