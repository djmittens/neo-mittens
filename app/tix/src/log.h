#pragma once

#include <stdarg.h>

typedef enum {
  TIX_LOG_ERROR = 0,
  TIX_LOG_WARN  = 1,
  TIX_LOG_INFO  = 2,
  TIX_LOG_DEBUG = 3,
  TIX_LOG_TRACE = 4,
} tix_log_level_e;

void tix_log_init(void);
void tix_log_set_level(tix_log_level_e lvl);
tix_log_level_e tix_log_get_level(void);
int tix_log_would_log(tix_log_level_e lvl);

void tix_log(tix_log_level_e lvl, const char *file, int line,
             const char *func, const char *fmt, ...);

#define TIX_LOG(lvl, fmt, ...) \
  tix_log((lvl), __FILE__, __LINE__, __func__, (fmt), ##__VA_ARGS__)

#define TIX_ERROR(fmt, ...) TIX_LOG(TIX_LOG_ERROR, (fmt), ##__VA_ARGS__)
#define TIX_WARN(fmt, ...)  TIX_LOG(TIX_LOG_WARN,  (fmt), ##__VA_ARGS__)
#define TIX_INFO(fmt, ...)  TIX_LOG(TIX_LOG_INFO,  (fmt), ##__VA_ARGS__)
#define TIX_DEBUG(fmt, ...) TIX_LOG(TIX_LOG_DEBUG, (fmt), ##__VA_ARGS__)
#define TIX_TRACE(fmt, ...) TIX_LOG(TIX_LOG_TRACE, (fmt), ##__VA_ARGS__)
