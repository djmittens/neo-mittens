/*
 * Tests for json.c: parser edge cases, JSON escaping, and roundtrip.
 */
#include "../testing.h"
#include "types.h"
#include "common.h"
#include "ticket.h"
#include "json.h"

#include <stdio.h>
#include <string.h>

/* --- JSON parser tests --- */

static void test_parse_empty_object(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line("{}", &obj);
  ASSERT_OK(err);
  ASSERT_EQ(obj.field_count, 0);
  TIX_PASS();
}

static void test_parse_whitespace_object(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line("  {  \"key\"  :  \"value\"  }  ", &obj);
  ASSERT_OK(err);
  ASSERT_EQ(obj.field_count, 1);
  const char *v = tix_json_get_str(&obj, "key");
  ASSERT_NOT_NULL(v);
  ASSERT_STR_EQ(v, "value");
  TIX_PASS();
}

static void test_parse_booleans(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line(
      "{\"active\":true,\"deleted\":false}", &obj);
  ASSERT_OK(err);
  ASSERT_EQ(tix_json_get_bool(&obj, "active", 0), 1);
  ASSERT_EQ(tix_json_get_bool(&obj, "deleted", 1), 0);
  /* missing key returns default */
  ASSERT_EQ(tix_json_get_bool(&obj, "missing", 42), 42);
  TIX_PASS();
}

static void test_parse_null(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line("{\"val\":null}", &obj);
  ASSERT_OK(err);
  ASSERT_EQ(obj.field_count, 1);
  ASSERT_TRUE(tix_json_has_key(&obj, "val"));
  ASSERT_NULL(tix_json_get_str(&obj, "val"));
  TIX_PASS();
}

static void test_parse_numbers(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line(
      "{\"pos\":42,\"neg\":-7,\"zero\":0}", &obj);
  ASSERT_OK(err);
  ASSERT_EQ(tix_json_get_num(&obj, "pos", 0), 42);
  ASSERT_EQ(tix_json_get_num(&obj, "neg", 0), -7);
  ASSERT_EQ(tix_json_get_num(&obj, "zero", -1), 0);
  /* missing key returns default */
  ASSERT_EQ(tix_json_get_num(&obj, "missing", 99), 99);
  TIX_PASS();
}

static void test_parse_string_escapes(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line(
      "{\"msg\":\"line1\\nline2\\ttab\"}", &obj);
  ASSERT_OK(err);
  const char *v = tix_json_get_str(&obj, "msg");
  ASSERT_NOT_NULL(v);
  ASSERT_STR_EQ(v, "line1\nline2\ttab");
  TIX_PASS();
}

static void test_parse_string_escaped_quotes(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line(
      "{\"msg\":\"say \\\"hello\\\"\"}", &obj);
  ASSERT_OK(err);
  const char *v = tix_json_get_str(&obj, "msg");
  ASSERT_NOT_NULL(v);
  ASSERT_STR_EQ(v, "say \"hello\"");
  TIX_PASS();
}

static void test_parse_string_backslash(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line(
      "{\"path\":\"C:\\\\dir\\\\file\"}", &obj);
  ASSERT_OK(err);
  const char *v = tix_json_get_str(&obj, "path");
  ASSERT_NOT_NULL(v);
  ASSERT_STR_EQ(v, "C:\\dir\\file");
  TIX_PASS();
}

static void test_parse_unclosed_string(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line("{\"key\":\"value", &obj);
  ASSERT_ERR(err);
  TIX_PASS();
}

static void test_parse_missing_colon(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line("{\"key\" \"value\"}", &obj);
  ASSERT_ERR(err);
  TIX_PASS();
}

static void test_parse_truncated_object(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line("{\"key\":\"value\"", &obj);
  ASSERT_ERR(err);
  TIX_PASS();
}

static void test_parse_null_args(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  ASSERT_ERR(tix_json_parse_line(NULL, &obj));
  ASSERT_ERR(tix_json_parse_line("{}", NULL));
  TIX_PASS();
}

static void test_get_str_wrong_type(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line("{\"num\":42}", &obj);
  ASSERT_OK(err);
  /* asking for string when it's a number should return NULL */
  ASSERT_NULL(tix_json_get_str(&obj, "num"));
  TIX_PASS();
}

static void test_has_key(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line("{\"a\":1,\"b\":\"x\"}", &obj);
  ASSERT_OK(err);
  ASSERT_TRUE(tix_json_has_key(&obj, "a"));
  ASSERT_TRUE(tix_json_has_key(&obj, "b"));
  ASSERT_FALSE(tix_json_has_key(&obj, "c"));
  ASSERT_FALSE(tix_json_has_key(NULL, "a"));
  ASSERT_FALSE(tix_json_has_key(&obj, NULL));
  TIX_PASS();
}

static void test_parse_array(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line(
      "{\"deps\":[\"t-001\",\"t-002\",\"t-003\"]}", &obj);
  ASSERT_OK(err);
  ASSERT_EQ(obj.field_count, 1);
  ASSERT_EQ(obj.fields[0].type, TIX_JSON_ARRAY);
  ASSERT_EQ(obj.fields[0].arr_count, 3);
  ASSERT_STR_EQ(obj.fields[0].arr_vals[0], "t-001");
  ASSERT_STR_EQ(obj.fields[0].arr_vals[2], "t-003");
  TIX_PASS();
}

static void test_parse_empty_array(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line("{\"deps\":[]}", &obj);
  ASSERT_OK(err);
  ASSERT_EQ(obj.fields[0].arr_count, 0);
  TIX_PASS();
}

/* --- JSON escape tests --- */

static void test_escape_quotes(TIX_TEST_ARGS()) {
  TIX_TEST();
  char out[128];
  tix_json_escape("he said \"hello\"", out, sizeof(out));
  ASSERT_STR_EQ(out, "he said \\\"hello\\\"");
  TIX_PASS();
}

static void test_escape_backslash(TIX_TEST_ARGS()) {
  TIX_TEST();
  char out[128];
  tix_json_escape("path\\to\\file", out, sizeof(out));
  ASSERT_STR_EQ(out, "path\\\\to\\\\file");
  TIX_PASS();
}

static void test_escape_newline_tab(TIX_TEST_ARGS()) {
  TIX_TEST();
  char out[128];
  tix_json_escape("line1\nline2\ttab", out, sizeof(out));
  ASSERT_STR_EQ(out, "line1\\nline2\\ttab");
  TIX_PASS();
}

static void test_escape_cr_bs_ff(TIX_TEST_ARGS()) {
  TIX_TEST();
  char out[128];
  tix_json_escape("a\rb\bc\f", out, sizeof(out));
  ASSERT_STR_EQ(out, "a\\rb\\bc\\f");
  TIX_PASS();
}

static void test_escape_control_char(TIX_TEST_ARGS()) {
  TIX_TEST();
  char out[128];
  char input[4] = {'\x01', '\x1f', '\0', '\0'};
  tix_json_escape(input, out, sizeof(out));
  ASSERT_STR_EQ(out, "\\u0001\\u001f");
  TIX_PASS();
}

static void test_escape_empty(TIX_TEST_ARGS()) {
  TIX_TEST();
  char out[128];
  tix_json_escape("", out, sizeof(out));
  ASSERT_STR_EQ(out, "");
  TIX_PASS();
}

static void test_escape_small_buffer(TIX_TEST_ARGS()) {
  TIX_TEST();
  char out[2];
  tix_json_escape("hello", out, sizeof(out));
  /* should not overflow, null-terminated */
  ASSERT_TRUE(out[1] == '\0');

  char out1[1];
  tix_json_escape("hello", out1, sizeof(out1));
  ASSERT_STR_EQ(out1, "");
  TIX_PASS();
}

static void test_escape_roundtrip(TIX_TEST_ARGS()) {
  TIX_TEST();
  /* create a ticket with special chars in name */
  tix_ticket_t t;
  tix_ticket_init(&t);
  t.type = TIX_TICKET_TASK;
  snprintf(t.id, sizeof(t.id), "t-test01");
  tix_ticket_set_name(&t, "Fix \"parser\" bug\nwith tabs\t");

  /* write to JSON */
  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_ticket(&t, buf, sizeof(buf));
  ASSERT_GT(len, 0);

  /* parse it back */
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line(buf, &obj);
  ASSERT_OK(err);

  const char *name = tix_json_get_str(&obj, "name");
  ASSERT_NOT_NULL(name);
  ASSERT_STR_EQ(name, "Fix \"parser\" bug\nwith tabs\t");
  TIX_PASS();
}

static void test_write_ticket_null(TIX_TEST_ARGS()) {
  TIX_TEST();
  char buf[256];
  ASSERT_EQ(tix_json_write_ticket(NULL, buf, sizeof(buf)), 0);
  ASSERT_EQ(tix_json_write_ticket(&buf, NULL, 256), 0);
  ASSERT_EQ(tix_json_write_ticket(&buf, buf, 32), 0);  /* buf_len < 64 */
  TIX_PASS();
}

static void test_write_tombstone_roundtrip(TIX_TEST_ARGS()) {
  TIX_TEST();
  tix_tombstone_t ts;
  memset(&ts, 0, sizeof(ts));
  snprintf(ts.id, sizeof(ts.id), "t-abc123");
  snprintf(ts.done_at, sizeof(ts.done_at), "def456");
  snprintf(ts.reason, sizeof(ts.reason), "Tests \"failed\" badly");
  snprintf(ts.name, sizeof(ts.name), "Fix parser");
  ts.is_accept = 0;
  ts.timestamp = 12345;

  char buf[TIX_MAX_LINE_LEN];
  sz len = tix_json_write_tombstone(&ts, buf, sizeof(buf));
  ASSERT_GT(len, 0);

  /* parse it back */
  tix_json_obj_t obj;
  tix_err_t err = tix_json_parse_line(buf, &obj);
  ASSERT_OK(err);

  ASSERT_STR_EQ(tix_json_get_str(&obj, "t"), "reject");
  ASSERT_STR_EQ(tix_json_get_str(&obj, "id"), "t-abc123");
  /* reason should have escaped quotes preserved through roundtrip */
  const char *reason = tix_json_get_str(&obj, "reason");
  ASSERT_NOT_NULL(reason);
  ASSERT_STR_EQ(reason, "Tests \"failed\" badly");
  TIX_PASS();
}

int main(void) {
  tix_test_suite_t suite;
  tix_testsuite_init(&suite, __FILE__);

  /* parser */
  tix_testsuite_add(&suite, "parse_empty_object", test_parse_empty_object);
  tix_testsuite_add(&suite, "parse_whitespace", test_parse_whitespace_object);
  tix_testsuite_add(&suite, "parse_booleans", test_parse_booleans);
  tix_testsuite_add(&suite, "parse_null", test_parse_null);
  tix_testsuite_add(&suite, "parse_numbers", test_parse_numbers);
  tix_testsuite_add(&suite, "parse_string_escapes", test_parse_string_escapes);
  tix_testsuite_add(&suite, "parse_escaped_quotes", test_parse_string_escaped_quotes);
  tix_testsuite_add(&suite, "parse_backslash", test_parse_string_backslash);
  tix_testsuite_add(&suite, "parse_unclosed_str", test_parse_unclosed_string);
  tix_testsuite_add(&suite, "parse_missing_colon", test_parse_missing_colon);
  tix_testsuite_add(&suite, "parse_truncated_obj", test_parse_truncated_object);
  tix_testsuite_add(&suite, "parse_null_args", test_parse_null_args);
  tix_testsuite_add(&suite, "get_str_wrong_type", test_get_str_wrong_type);
  tix_testsuite_add(&suite, "has_key", test_has_key);
  tix_testsuite_add(&suite, "parse_array", test_parse_array);
  tix_testsuite_add(&suite, "parse_empty_array", test_parse_empty_array);

  /* escaping */
  tix_testsuite_add(&suite, "escape_quotes", test_escape_quotes);
  tix_testsuite_add(&suite, "escape_backslash", test_escape_backslash);
  tix_testsuite_add(&suite, "escape_newline_tab", test_escape_newline_tab);
  tix_testsuite_add(&suite, "escape_cr_bs_ff", test_escape_cr_bs_ff);
  tix_testsuite_add(&suite, "escape_control_char", test_escape_control_char);
  tix_testsuite_add(&suite, "escape_empty", test_escape_empty);
  tix_testsuite_add(&suite, "escape_small_buffer", test_escape_small_buffer);
  tix_testsuite_add(&suite, "escape_roundtrip", test_escape_roundtrip);

  /* write */
  tix_testsuite_add(&suite, "write_ticket_null", test_write_ticket_null);
  tix_testsuite_add(&suite, "write_tombstone_rt", test_write_tombstone_roundtrip);

  int result = tix_testsuite_run(&suite);
  tix_testsuite_print(&suite);
  return result;
}
