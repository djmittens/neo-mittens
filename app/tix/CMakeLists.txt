cmake_minimum_required(VERSION 3.20 FATAL_ERROR)

project(tix LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Sanitizer options
option(ASAN "Enable AddressSanitizer" OFF)
option(TSAN "Enable ThreadSanitizer" OFF)

set(SANITIZE_FLAGS "")
if(ASAN)
  set(SANITIZE_FLAGS "-fsanitize=address -fno-omit-frame-pointer -fsanitize=undefined")
endif()
if(TSAN)
  set(SANITIZE_FLAGS "-fsanitize=thread -fno-omit-frame-pointer")
endif()

# NASA Power of 10 + strict warnings
set(WARN_FLAGS "-Wall -Wextra -Wpedantic -Werror")
set(WARN_FLAGS "${WARN_FLAGS} -Wshadow -Wconversion -Wstrict-prototypes")
set(WARN_FLAGS "${WARN_FLAGS} -Wold-style-definition -Wmissing-prototypes")
set(WARN_FLAGS "${WARN_FLAGS} -Wno-unused-parameter")

set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} ${WARN_FLAGS} ${SANITIZE_FLAGS}")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} ${SANITIZE_FLAGS}")

if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
  add_compile_definitions(_POSIX_C_SOURCE=200809L)
endif()

# --- SQLite (vendored amalgamation) ---
add_library(tix_sqlite STATIC vendor/sqlite/sqlite3.c)
target_compile_definitions(tix_sqlite PRIVATE
  SQLITE_THREADSAFE=0
  SQLITE_OMIT_LOAD_EXTENSION
  SQLITE_DQS=0
)
# SQLite has its own warning profile; suppress for vendored code
target_compile_options(tix_sqlite PRIVATE -w)

# --- tix static library (all source modules) ---
set(TIX_SOURCES
  src/log.c
  src/ticket.c
  src/git.c
  src/db.c
  src/config.c
  src/search.c
  src/tree.c
  src/report.c
  src/validate.c
  src/batch.c
  src/json.c
  src/cmd_init.c
  src/cmd_task.c
  src/cmd_issue.c
  src/cmd_note.c
  src/cmd_query.c
  src/cmd_status.c
  src/cmd_log.c
  src/cmd_tree.c
  src/cmd_report.c
  src/cmd_search.c
  src/cmd_validate.c
  src/cmd_batch.c
  src/cmd_sync.c
  src/cmd_compact.c
  src/cmd.c
)

add_library(tix_lib STATIC ${TIX_SOURCES})
target_include_directories(tix_lib PRIVATE
  ${PROJECT_SOURCE_DIR}/src
  ${PROJECT_SOURCE_DIR}/vendor/sqlite
)
target_link_libraries(tix_lib PRIVATE tix_sqlite)

# --- tix executable ---
add_executable(tix src/main.c)
target_include_directories(tix PRIVATE
  ${PROJECT_SOURCE_DIR}/src
  ${PROJECT_SOURCE_DIR}/vendor/sqlite
)
target_link_libraries(tix PRIVATE tix_lib tix_sqlite)

# --- Test helper library ---
add_library(tix_testing STATIC test/testing.c)
target_include_directories(tix_testing PRIVATE
  ${PROJECT_SOURCE_DIR}/test
)
# Testing framework uses _DEFAULT_SOURCE for usleep, etc.
target_compile_options(tix_testing PRIVATE -Wno-unused-parameter)

# Helper macro for adding test executables
function(tix_add_test name source)
  add_executable(${name} ${source})
  target_include_directories(${name} PRIVATE
    ${PROJECT_SOURCE_DIR}/src
    ${PROJECT_SOURCE_DIR}/vendor/sqlite
    ${PROJECT_SOURCE_DIR}/test
  )
  target_link_libraries(${name} PRIVATE tix_lib tix_sqlite tix_testing)
endfunction()

# --- E2E Tests ---
tix_add_test(test_task_lifecycle  test/e2e/test_task_lifecycle.c)
tix_add_test(test_git_integration test/e2e/test_git_integration.c)
tix_add_test(test_config          test/e2e/test_config.c)
tix_add_test(test_search          test/e2e/test_search.c)
tix_add_test(test_tree            test/e2e/test_tree.c)
tix_add_test(test_batch           test/e2e/test_batch.c)
tix_add_test(test_validate        test/e2e/test_validate.c)
tix_add_test(test_report          test/e2e/test_report.c)
target_link_libraries(test_report PRIVATE m)
tix_add_test(test_json            test/e2e/test_json.c)
tix_add_test(test_error_paths     test/e2e/test_error_paths.c)
tix_add_test(test_sync            test/e2e/test_sync.c)
tix_add_test(test_new_fields      test/e2e/test_new_fields.c)
target_link_libraries(test_new_fields PRIVATE m)
