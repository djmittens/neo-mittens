/*
 * tix test framework - simplified fork-based test isolation
 * Modeled after Valkyria's test framework but with no dynamic allocation.
 *
 * Usage:
 *   static void test_something(TIX_TEST_ARGS()) {
 *     TIX_TEST();
 *     // ... test code ...
 *     ASSERT_EQ(a, b);
 *     TIX_PASS();
 *   }
 *
 *   int main(void) {
 *     tix_test_suite_t suite;
 *     tix_testsuite_init(&suite, __FILE__);
 *     tix_testsuite_add(&suite, "test_something", test_something);
 *     int result = tix_testsuite_run(&suite);
 *     tix_testsuite_print(&suite);
 *     return result;
 *   }
 */
#pragma once

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TIX_TEST_MAX_TESTS    64
#define TIX_TEST_MAX_NAME     128
#define TIX_TEST_CAPTURE_SIZE 4096
#define TIX_TEST_TIMEOUT_SEC  30

typedef enum {
  TIX_TEST_UNDEFINED = 0,
  TIX_TEST_PASS,
  TIX_TEST_FAIL,
  TIX_TEST_CRASH,
  TIX_TEST_SKIP,
  TIX_TEST_TIMEOUT,
} tix_test_result_e;

typedef struct {
  tix_test_result_e type;
  long start_us;
  long stop_us;
} tix_test_result_t;

typedef struct tix_test_suite_t tix_test_suite_t;
typedef void (*tix_test_fn)(tix_test_suite_t *suite, tix_test_result_t *result);

#define TIX_TEST_ARGS() tix_test_suite_t *_suite, tix_test_result_t *_result

#define TIX_TEST()                       \
  (void)_suite;                          \
  _result->start_us = tix_test_get_us()

#define TIX_PASS()                                       \
  do {                                                   \
    if (_result->type == TIX_TEST_UNDEFINED) {            \
      _result->type = TIX_TEST_PASS;                     \
      _result->stop_us = tix_test_get_us();              \
    }                                                    \
  } while (0)

#define TIX_SKIP(reason)                                 \
  do {                                                   \
    if (_result->type == TIX_TEST_UNDEFINED) {            \
      fprintf(stderr, "SKIP: %s:%d: %s\n",              \
              __FILE__, __LINE__, (reason));              \
      _result->type = TIX_TEST_SKIP;                     \
      _result->stop_us = tix_test_get_us();              \
    }                                                    \
    return;                                              \
  } while (0)

/*
 * TIX_FAIL_MSG - simple string message (no format args)
 * TIX_FAIL     - formatted message with printf-style args
 *
 * In C11 with -Wpedantic, ##__VA_ARGS__ is not portable.
 * We use two separate macros to avoid the issue.
 */
#define TIX_FAIL_MSG(msg)                                \
  do {                                                   \
    if (_result->type == TIX_TEST_UNDEFINED) {            \
      fprintf(stderr, "FAIL: %s:%d: %s\n",              \
              __FILE__, __LINE__, (msg));                 \
      _result->type = TIX_TEST_FAIL;                     \
      _result->stop_us = tix_test_get_us();              \
    }                                                    \
  } while (0)

#define TIX_FAIL(fmt, ...)                               \
  do {                                                   \
    if (_result->type == TIX_TEST_UNDEFINED) {            \
      fprintf(stderr, "FAIL: %s:%d: " fmt "\n",         \
              __FILE__, __LINE__, __VA_ARGS__);           \
      _result->type = TIX_TEST_FAIL;                     \
      _result->stop_us = tix_test_get_us();              \
    }                                                    \
  } while (0)

/* --- Assertion macros --- */

#define ASSERT_TRUE(cond)                                \
  do {                                                   \
    if (!(cond)) {                                       \
      TIX_FAIL_MSG("ASSERT_TRUE: condition is false");   \
      return;                                            \
    }                                                    \
  } while (0)

#define ASSERT_FALSE(cond)                               \
  do {                                                   \
    if ((cond)) {                                        \
      TIX_FAIL_MSG("ASSERT_FALSE: condition is true");   \
      return;                                            \
    }                                                    \
  } while (0)

#define ASSERT_EQ(a, b)                                  \
  do {                                                   \
    long long _a = (long long)(a);                       \
    long long _b = (long long)(b);                       \
    if (_a != _b) {                                      \
      TIX_FAIL("ASSERT_EQ: %lld != %lld", _a, _b);     \
      return;                                            \
    }                                                    \
  } while (0)

#define ASSERT_NE(a, b)                                  \
  do {                                                   \
    long long _a = (long long)(a);                       \
    long long _b = (long long)(b);                       \
    if (_a == _b) {                                      \
      TIX_FAIL("ASSERT_NE: %lld == %lld", _a, _b);     \
      return;                                            \
    }                                                    \
  } while (0)

#define ASSERT_GT(a, b)                                  \
  do {                                                   \
    long long _a = (long long)(a);                       \
    long long _b = (long long)(b);                       \
    if (!(_a > _b)) {                                    \
      TIX_FAIL("ASSERT_GT: %lld <= %lld", _a, _b);     \
      return;                                            \
    }                                                    \
  } while (0)

#define ASSERT_GE(a, b)                                  \
  do {                                                   \
    long long _a = (long long)(a);                       \
    long long _b = (long long)(b);                       \
    if (!(_a >= _b)) {                                   \
      TIX_FAIL("ASSERT_GE: %lld < %lld", _a, _b);      \
      return;                                            \
    }                                                    \
  } while (0)

#define ASSERT_NOT_NULL(ptr)                             \
  do {                                                   \
    if ((ptr) == NULL) {                                 \
      TIX_FAIL_MSG("ASSERT_NOT_NULL: pointer is NULL"); \
      return;                                            \
    }                                                    \
  } while (0)

#define ASSERT_NULL(ptr)                                 \
  do {                                                   \
    if ((ptr) != NULL) {                                 \
      TIX_FAIL_MSG("ASSERT_NULL: pointer is not NULL"); \
      return;                                            \
    }                                                    \
  } while (0)

#define ASSERT_STR_EQ(a, b)                              \
  do {                                                   \
    const char *_sa = (a);                               \
    const char *_sb = (b);                               \
    if (_sa == NULL || _sb == NULL) {                     \
      if (_sa != _sb) {                                  \
        TIX_FAIL_MSG("ASSERT_STR_EQ: NULL string");     \
        return;                                          \
      }                                                  \
    } else if (strcmp(_sa, _sb) != 0) {                  \
      TIX_FAIL("ASSERT_STR_EQ: \"%s\" != \"%s\"",      \
               _sa, _sb);                                \
      return;                                            \
    }                                                    \
  } while (0)

#define ASSERT_STR_CONTAINS(haystack, needle)            \
  do {                                                   \
    if ((haystack) == NULL || (needle) == NULL) {         \
      TIX_FAIL_MSG("ASSERT_STR_CONTAINS: NULL arg");    \
      return;                                            \
    }                                                    \
    if (strstr((haystack), (needle)) == NULL) {           \
      TIX_FAIL("ASSERT_STR_CONTAINS: \"%s\" not in "    \
               "\"%s\"", (needle), (haystack));          \
      return;                                            \
    }                                                    \
  } while (0)

#define ASSERT_OK(err)                                   \
  do {                                                   \
    if ((err) != 0) {                                    \
      TIX_FAIL("ASSERT_OK: got error %d", (int)(err));  \
      return;                                            \
    }                                                    \
  } while (0)

#define ASSERT_ERR(err)                                  \
  do {                                                   \
    if ((err) == 0) {                                    \
      TIX_FAIL_MSG("ASSERT_ERR: expected error");       \
      return;                                            \
    }                                                    \
  } while (0)

/* --- Test suite (all stack-allocated) --- */

typedef struct {
  char name[TIX_TEST_MAX_NAME];
  tix_test_fn func;
  tix_test_result_t result;
  char captured_stdout[TIX_TEST_CAPTURE_SIZE];
  char captured_stderr[TIX_TEST_CAPTURE_SIZE];
  int stdout_len;
  int stderr_len;
} tix_test_entry_t;

struct tix_test_suite_t {
  char filename[TIX_TEST_MAX_NAME];
  tix_test_entry_t tests[TIX_TEST_MAX_TESTS];
  int count;
};

void tix_testsuite_init(tix_test_suite_t *suite, const char *filename);
void tix_testsuite_add(tix_test_suite_t *suite, const char *name,
                       tix_test_fn func);
int  tix_testsuite_run(tix_test_suite_t *suite);
void tix_testsuite_print(tix_test_suite_t *suite);

long tix_test_get_us(void);
