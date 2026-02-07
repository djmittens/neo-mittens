#pragma once

#include <stddef.h>
#include <stdint.h>

typedef unsigned long long u64;
typedef signed long long   i64;
typedef unsigned int       u32;
typedef signed int         i32;
typedef unsigned short     u16;
typedef signed short       i16;
typedef unsigned char      u8;
typedef signed char        i8;

typedef size_t sz;

typedef int32_t tix_err_t;

#define TIX_MAX_ID_LEN       16
#define TIX_MAX_NAME_LEN     256
#define TIX_MAX_PATH_LEN     4096
#define TIX_MAX_HASH_LEN     64
#define TIX_MAX_BRANCH_LEN   256
#define TIX_MAX_DESC_LEN     4096
#define TIX_MAX_LINE_LEN     8192
#define TIX_MAX_KEYWORD_LEN  64
#define TIX_MAX_KEYWORDS     64
#define TIX_MAX_LABELS       16
#define TIX_MAX_DEPS         32
#define TIX_MAX_BATCH        128
#define TIX_MAX_CHILDREN     256
#define TIX_MAX_QUERY_LEN    2048
