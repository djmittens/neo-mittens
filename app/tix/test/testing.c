#define _POSIX_C_SOURCE 200809L
#define _DEFAULT_SOURCE
#include "testing.h"

#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/*
 * Disable fork-based testing under AddressSanitizer.
 * ASAN doesn't properly support fork() - shadow memory becomes inconsistent.
 */
#if defined(__SANITIZE_ADDRESS__) || \
    (defined(__has_feature) && __has_feature(address_sanitizer))
#define TIX_TEST_FORK_ENABLED 0
#else
#define TIX_TEST_FORK_ENABLED 1
#endif

static const char *DOT_FILL =
    "........................................................................"
    "........................................................................";

long tix_test_get_us(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return ts.tv_sec * 1000000L + ts.tv_nsec / 1000L;
}

void tix_testsuite_init(tix_test_suite_t *suite, const char *filename) {
  memset(suite, 0, sizeof(*suite));
  strncpy(suite->filename, filename, TIX_TEST_MAX_NAME - 1);
}

void tix_testsuite_add(tix_test_suite_t *suite, const char *name,
                       tix_test_fn func) {
  if (suite->count >= TIX_TEST_MAX_TESTS) {
    fprintf(stderr, "error: too many tests (max %d)\n", TIX_TEST_MAX_TESTS);
    return;
  }

  tix_test_entry_t *entry = &suite->tests[suite->count];
  memset(entry, 0, sizeof(*entry));
  strncpy(entry->name, name, TIX_TEST_MAX_NAME - 1);
  entry->func = func;
  entry->result.type = TIX_TEST_UNDEFINED;
  suite->count++;
}

#if TIX_TEST_FORK_ENABLED
static int tix_test_use_fork(void) {
  return getenv("TIX_TEST_NO_FORK") == NULL;
}

static void tix_test_run_forked(tix_test_entry_t *entry,
                                tix_test_suite_t *suite) {
  int pout[2], perr[2];

  if (pipe(pout) != 0 || pipe(perr) != 0) {
    entry->result.type = TIX_TEST_CRASH;
    return;
  }

  pid_t pid = fork();
  if (pid < 0) {
    entry->result.type = TIX_TEST_CRASH;
    close(pout[0]); close(pout[1]);
    close(perr[0]); close(perr[1]);
    return;
  }

  if (pid == 0) {
    /* child */
    close(pout[0]);
    close(perr[0]);
    dup2(pout[1], STDOUT_FILENO);
    dup2(perr[1], STDERR_FILENO);
    close(pout[1]);
    close(perr[1]);

    entry->func(suite, &entry->result);

    /* write result struct to stderr for parent to read */
    fflush(stdout);
    fflush(stderr);

    const unsigned char *p = (const unsigned char *)&entry->result;
    size_t remaining = sizeof(entry->result);
    while (remaining > 0) {
      ssize_t n = write(STDERR_FILENO, p, remaining);
      if (n <= 0) { break; }
      p += n;
      remaining -= (size_t)n;
    }

    _exit(0);
  }

  /* parent */
  close(pout[1]);
  close(perr[1]);

  /* read captured stdout */
  {
    ssize_t n = read(pout[0], entry->captured_stdout,
                     TIX_TEST_CAPTURE_SIZE - 1);
    if (n > 0) {
      entry->captured_stdout[n] = '\0';
      entry->stdout_len = (int)n;
    }
    close(pout[0]);
  }

  /* read captured stderr (contains test output + result struct at end) */
  char stderr_buf[TIX_TEST_CAPTURE_SIZE + sizeof(tix_test_result_t)];
  ssize_t stderr_total = 0;
  {
    ssize_t n;
    while ((n = read(perr[0], stderr_buf + stderr_total,
                     sizeof(stderr_buf) - (size_t)stderr_total)) > 0) {
      stderr_total += n;
    }
    close(perr[0]);
  }

  /* wait for child with timeout */
  int timeout_sec = TIX_TEST_TIMEOUT_SEC;
  {
    const char *env = getenv("TIX_TEST_TIMEOUT");
    if (env != NULL) {
      int val = atoi(env);
      if (val > 0) { timeout_sec = val; }
    }
  }

  int wstatus = 0;
  int elapsed = 0;
  pid_t ret;

  while (elapsed < timeout_sec) {
    ret = waitpid(pid, &wstatus, WNOHANG);
    if (ret != 0) { break; }
    usleep(100000); /* 100ms */
    elapsed++;
  }

  if (elapsed >= timeout_sec) {
    kill(pid, SIGKILL);
    waitpid(pid, &wstatus, 0);
    entry->result.type = TIX_TEST_TIMEOUT;
    entry->result.stop_us = tix_test_get_us();
    snprintf(entry->captured_stderr, TIX_TEST_CAPTURE_SIZE,
             "Test timed out after %d seconds\n", timeout_sec);
    entry->stderr_len = (int)strlen(entry->captured_stderr);
    return;
  }

  if (WIFEXITED(wstatus) && WEXITSTATUS(wstatus) == 0) {
    /* extract result struct from end of stderr */
    ssize_t result_size = (ssize_t)sizeof(tix_test_result_t);
    if (stderr_total >= result_size) {
      memcpy(&entry->result, stderr_buf + stderr_total - result_size,
             sizeof(tix_test_result_t));
      ssize_t text_len = stderr_total - result_size;
      if (text_len > 0) {
        if (text_len >= TIX_TEST_CAPTURE_SIZE) {
          text_len = TIX_TEST_CAPTURE_SIZE - 1;
        }
        memcpy(entry->captured_stderr, stderr_buf, (size_t)text_len);
        entry->captured_stderr[text_len] = '\0';
        entry->stderr_len = (int)text_len;
      }
    } else {
      entry->result.type = TIX_TEST_CRASH;
    }
  } else if (WIFSIGNALED(wstatus)) {
    entry->result.type = TIX_TEST_CRASH;
    entry->result.stop_us = tix_test_get_us();
    int sig = WTERMSIG(wstatus);
    snprintf(entry->captured_stderr, TIX_TEST_CAPTURE_SIZE,
             "Child killed by signal %d (%s)\n", sig, strsignal(sig));
    entry->stderr_len = (int)strlen(entry->captured_stderr);
  } else {
    entry->result.type = TIX_TEST_CRASH;
    entry->result.stop_us = tix_test_get_us();
  }
}
#endif /* TIX_TEST_FORK_ENABLED */

static void tix_test_run_direct(tix_test_entry_t *entry,
                                tix_test_suite_t *suite) {
  entry->func(suite, &entry->result);
}

int tix_testsuite_run(tix_test_suite_t *suite) {
  int failures = 0;

  for (int i = 0; i < suite->count; i++) {
    tix_test_entry_t *entry = &suite->tests[i];

#if TIX_TEST_FORK_ENABLED
    if (tix_test_use_fork()) {
      tix_test_run_forked(entry, suite);
    } else {
      tix_test_run_direct(entry, suite);
    }
#else
    tix_test_run_direct(entry, suite);
#endif

    if (entry->result.type != TIX_TEST_PASS &&
        entry->result.type != TIX_TEST_SKIP) {
      failures++;
    }
  }

  return failures > 0 ? 1 : 0;
}

void tix_testsuite_print(tix_test_suite_t *suite) {
  int pass = 0, fail = 0, crash = 0, skip = 0, timeout = 0;

  printf("\n[%d tests] %s\n", suite->count, suite->filename);

  for (int i = 0; i < suite->count; i++) {
    tix_test_entry_t *entry = &suite->tests[i];
    int name_len = (int)strlen(entry->name);
    int dots = 72 - name_len;
    if (dots < 2) { dots = 2; }

    long elapsed_us = entry->result.stop_us - entry->result.start_us;

    switch (entry->result.type) {
    case TIX_TEST_PASS:
      printf("  PASS  %s%.*s %ld us\n", entry->name, dots, DOT_FILL,
             elapsed_us);
      pass++;
      break;
    case TIX_TEST_FAIL:
      printf("  FAIL  %s%.*s %ld us\n", entry->name, dots, DOT_FILL,
             elapsed_us);
      if (entry->stderr_len > 0) {
        printf("        %s", entry->captured_stderr);
      }
      fail++;
      break;
    case TIX_TEST_CRASH:
      printf("  CRSH  %s%.*s\n", entry->name, dots, DOT_FILL);
      if (entry->stderr_len > 0) {
        printf("        %s", entry->captured_stderr);
      }
      crash++;
      break;
    case TIX_TEST_SKIP:
      printf("  SKIP  %s%.*s\n", entry->name, dots, DOT_FILL);
      skip++;
      break;
    case TIX_TEST_TIMEOUT:
      printf("  TIME  %s%.*s\n", entry->name, dots, DOT_FILL);
      if (entry->stderr_len > 0) {
        printf("        %s", entry->captured_stderr);
      }
      timeout++;
      break;
    case TIX_TEST_UNDEFINED:
      printf("  ????  %s%.*s\n", entry->name, dots, DOT_FILL);
      fail++;
      break;
    }
  }

  printf("\n  Results: %d pass, %d fail, %d crash, %d skip, %d timeout\n\n",
         pass, fail, crash, skip, timeout);
}
