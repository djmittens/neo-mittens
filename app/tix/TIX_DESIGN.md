# TIX - Git-Based Ticketing & Workflow System

## Status: IMPLEMENTED

All core modules, CLI commands, test framework, and build system are complete.
Schema version 6 with generic `ticket_meta` key-value metadata subsystem.

---

## 1. Overview

**tix** is a high-performance, zero-malloc C tool for git-based ticket management.
It manages tasks, issues, and notes as a compiled binary that uses SQLite for caching
and leverages git's immutability for commit-based state.

### Design Principles
- **No dynamic allocation**: All buffers are stack-allocated with fixed maximums (NASA coding rules)
- **No nesting > 3 deep**: Conditional nesting must not exceed 3 levels
- **No source file > 1000 lines**: Split into focused modules
- **Zero library dependencies** (except SQLite, bundled as amalgamation)
- **Fail on all warnings**: `-Wall -Wextra -Wpedantic -Werror`
- **Cross-platform**: Linux + macOS, gcc + clang
- **Fast**: Single-binary CLI, sub-millisecond for reads from cache

---

## 2. Integration Model

tix is a standalone CLI tool designed to be consumed by external orchestrators.
It owns the ticket data model (tasks, issues, notes) and provides a JSON-based
interface for programmatic consumption. External tools can add their own record
types to plan.jsonl (e.g. config, spec, stage records) — tix preserves these
during compaction without interpreting them.

### plan.jsonl File Format
```jsonl
{"t": "task", "id": "t-1a2b", "spec": "coverage.md", "name": "...", "s": "p"}
{"t": "task", "id": "t-3c4d", "name": "...", "s": "d", "meta": {"cost": 1.23, "model": "gpt-4o"}}
{"t": "issue", "id": "i-7g8h", "spec": "coverage.md", "desc": "..."}
{"t": "accept", "id": "t-1a2b", "done_at": "abc123", "reason": ""}
{"t": "reject", "id": "t-3c4d", "done_at": "def456", "reason": "..."}
{"t": "delete", "id": "t-1a2b"}
```

Tickets may carry arbitrary key-value metadata in a nested `"meta":{...}` object.
During replay, metadata keys are stored in the `ticket_meta` table. For backward
compatibility, legacy JSONL with telemetry fields as top-level keys (e.g.
`"cost":1.23`) is also recognized and routed to `ticket_meta` during replay.

External orchestrators may also write their own record types:
```jsonl
{"t": "config", "timeout_ms": 900000, "max_iterations": 10}
{"t": "spec", "spec": "coverage.md"}
{"t": "stage", "stage": "BUILD", ...}
```

The file is **append-only** during normal operations. Mutations (status changes,
priority updates, deletions) append new lines rather than editing existing ones.
Duplicate IDs are resolved by last-write-wins during cache rebuild.

`tix compact` rewrites the file with only live tickets, sorted by ID, for clean
git diffs. See section 16 for details.

---

## 3. Architecture

### Directory Layout
```
app/tix/
  CMakeLists.txt          # Build definition
  Makefile                # Developer wrapper
  AGENTS.md               # AI agent instructions
  TIX_DESIGN.md           # This file
  .clang-tidy             # Static analysis config
  src/
    types.h               # Fixed-width types, buffer limits
    common.h              # TIX_ASSERT, error enum, TIX_BUF_PRINTF
    log.h                 # Log level enum + macros
    log.c                 # Log implementation
    ticket.h              # Ticket types: task, issue, note + tombstone
    ticket.c              # Ticket ID gen, serialization, validation
    git.h                 # Git operations (popen-based)
    git.c                 # rev-parse, log, branch, commit, diff
    db.h                  # SQLite cache interface
    db.c                  # Cache init, upsert, query, keyword index
    config.h              # TOML config parsing
    config.c              # Read/write .tix/config.toml
    search.h              # LLM-searchable index, keyword cloud
    search.c              # FTS5 full-text search, keyword extraction
    tree.h                # Dependency tree visualization
    tree.c                # ASCII tree rendering
    report.h              # Progress reporting
    report.c              # Status dashboard, progress stats
    validate.h            # History validation
    validate.c            # Commit-based integrity checks
    batch.h               # Batch operations
    batch.c               # Multi-ticket operations
    cmd.h                 # CLI command dispatch table
    cmd_task.c            # task add|done|accept|reject|delete|prioritize
    cmd_issue.c           # issue add|done|done-all|done-ids
    cmd_note.c            # note add|done|list
    cmd_query.c           # query [tasks|issues|stage|iteration]
    cmd_status.c          # status (human-readable dashboard)
    cmd_log.c             # log [--all] [--spec <file>]
    cmd_tree.c            # tree (dependency visualization)
    cmd_report.c          # report (progress tracking)
    cmd_validate.c        # validate (history integrity check)
    cmd_init.c            # init (create .tix/ directory)
    cmd_search.c          # search <query> (LLM-friendly search)
    cmd_batch.c           # batch <subcommand> (batch operations)
    main.c                # Entry point, CLI parsing, dispatch
  test/
    testing.h             # Test framework (fork-based, mirrors Valkyria)
    testing.c             # Test runner
    e2e/
      test_task_lifecycle.c   # add -> done -> accept/reject
      test_issue_workflow.c   # issue add -> done
      test_note_workflow.c    # note add -> list -> done
      test_git_integration.c  # branch tracking, commit hashes
      test_search.c           # keyword search, FTS
      test_tree.c             # dependency tree rendering
      test_batch.c            # batch operations
      test_validate.c         # history validation
      test_config.c           # TOML config parsing
      test_report.c           # progress reporting
```

### Module Dependency Graph
```
main.c
  --> cmd.h (dispatch table)
    --> cmd_*.c (each command)
      --> ticket.h (data model)
      --> git.h (git ops)
      --> db.h (cache)
      --> config.h (config)
      --> search.h (FTS)
      --> tree.h (visualization)
      --> report.h (reporting)
      --> validate.h (integrity)
      --> batch.h (batch ops)
  --> log.h (logging)
  --> common.h (assertions, errors)
  --> types.h (type aliases)
```

---

## 4. Data Model (tix)

### Ticket Types
```c
typedef enum {
  TIX_TICKET_TASK = 0,
  TIX_TICKET_ISSUE = 1,
  TIX_TICKET_NOTE = 2,
} tix_ticket_type_e;

typedef enum {
  TIX_STATUS_PENDING  = 0,   // "p"
  TIX_STATUS_DONE     = 1,   // "d"
  TIX_STATUS_ACCEPTED = 2,   // "a"
  TIX_STATUS_REJECTED = 3,   // "r"
  TIX_STATUS_DELETED  = 4,   // "x"
} tix_status_e;

typedef enum {
  TIX_PRIORITY_NONE   = 0,
  TIX_PRIORITY_LOW    = 1,
  TIX_PRIORITY_MEDIUM = 2,
  TIX_PRIORITY_HIGH   = 3,
} tix_priority_e;

typedef struct {
  char id[TIX_MAX_ID_LEN];
  tix_ticket_type_e type;
  tix_status_e status;
  tix_priority_e priority;
  char name[TIX_MAX_NAME_LEN];
  char spec[TIX_MAX_PATH_LEN];
  char notes[TIX_MAX_DESC_LEN];
  char accept[TIX_MAX_DESC_LEN];
  char done_at[TIX_MAX_HASH_LEN];       // commit hash
  char branch[TIX_MAX_BRANCH_LEN];      // associated branch
  char parent[TIX_MAX_ID_LEN];          // decomposed from
  char created_from[TIX_MAX_ID_LEN];    // from issue
  char supersedes[TIX_MAX_ID_LEN];      // replaces
  char deps[TIX_MAX_DEPS][TIX_MAX_ID_LEN];
  u32 dep_count;
  char labels[TIX_MAX_LABELS][TIX_MAX_KEYWORD_LEN];
  u32 label_count;
  char kill_reason[TIX_MAX_KEYWORD_LEN]; // "timeout" or "context"
  char created_from_name[TIX_MAX_NAME_LEN];   // denormalized at compact
  char supersedes_name[TIX_MAX_NAME_LEN];     // denormalized at compact
  char supersedes_reason[TIX_MAX_KEYWORD_LEN]; // denormalized at compact
  i64 created_at;                         // unix timestamp
  i64 updated_at;                         // unix timestamp
  char author[TIX_MAX_NAME_LEN];
  char assigned[TIX_MAX_NAME_LEN];       // who should work on this
  char completed_at[64];                  // ISO 8601 completion time
  i64 resolved_at;                        // when reached terminal state
  i64 compacted_at;                       // when removed from plan.jsonl
} tix_ticket_t;

typedef struct {
  char id[TIX_MAX_ID_LEN];
  char done_at[TIX_MAX_HASH_LEN];
  char reason[TIX_MAX_DESC_LEN];
  char name[TIX_MAX_NAME_LEN];
  int is_accept;                          // 1 = accept, 0 = reject
  i64 timestamp;
} tix_tombstone_t;
```

### ID Generation
Format: `{prefix}-{hex8}` where hex8 = lower 32 bits of (microsecond timestamp XOR random).
- Tasks: `t-a1b2c3d4`
- Issues: `i-a1b2c3d4`
- Notes: `n-a1b2c3d4`

---

## 5. Storage Architecture

### .tix/ Directory (gitignored)
```
.tix/
  config.toml    # User configuration
  cache.db       # SQLite database (rebuilt from git)
```

### config.toml Format
```toml
[repo]
main_branch = "main"
plan_file = ".tix/plan.jsonl"    # default; configurable for legacy repos

[display]
color = true

[cache]
auto_rebuild = true
```

### SQLite Schema
```sql
-- Core ticket storage (cache, rebuilt from plan.jsonl in git)
CREATE TABLE tickets (
  id TEXT PRIMARY KEY,
  type INTEGER NOT NULL,        -- 0=task, 1=issue, 2=note
  status INTEGER NOT NULL,      -- 0=pending, 1=done, 2=accepted, 3=rejected, 4=deleted
  priority INTEGER DEFAULT 0,
  name TEXT NOT NULL,
  spec TEXT,
  notes TEXT,
  accept TEXT,
  done_at TEXT,
  branch TEXT,
  parent TEXT,
  created_from TEXT,
  supersedes TEXT,
  kill_reason TEXT,
  author TEXT,
  assigned TEXT,
  completed_at TEXT,
  created_from_name TEXT,
  supersedes_name TEXT,
  supersedes_reason TEXT,
  created_at INTEGER,
  updated_at INTEGER,
  resolved_at INTEGER,
  compacted_at INTEGER,
  commit_hash TEXT              -- git commit this state was read from
);

-- Generic key-value metadata for tickets (agent telemetry, etc.)
CREATE TABLE ticket_meta (
  ticket_id TEXT NOT NULL,
  key TEXT NOT NULL,
  value_text TEXT,              -- for string values
  value_num REAL,               -- for numeric values
  PRIMARY KEY (ticket_id, key)
);

CREATE TABLE ticket_deps (
  ticket_id TEXT NOT NULL,
  dep_id TEXT NOT NULL,
  PRIMARY KEY (ticket_id, dep_id)
);

CREATE TABLE tombstones (
  id TEXT PRIMARY KEY,
  done_at TEXT,
  reason TEXT,
  name TEXT,
  is_accept INTEGER,
  timestamp INTEGER
);

-- Keyword cloud for LLM search
CREATE TABLE keywords (
  ticket_id TEXT NOT NULL,
  keyword TEXT NOT NULL,
  weight REAL DEFAULT 1.0,
  PRIMARY KEY (ticket_id, keyword)
);

CREATE INDEX idx_keywords_keyword ON keywords(keyword);

-- Full-text search (FTS5)
CREATE VIRTUAL TABLE tickets_fts USING fts5(
  id, name, notes, accept, spec,
  content='tickets',
  content_rowid='rowid'
);

-- Cache metadata
CREATE TABLE cache_meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
-- Stores: last_commit, last_rebuild_time, schema_version (currently "6")
```

### Commit-Based Cache Strategy
1. On `tix` invocation, read `cache_meta.last_commit`
2. Run `git rev-parse HEAD` to get current commit
3. If they match, cache is fresh -> use SQLite directly
4. If they differ, rebuild cache from `plan.jsonl` at HEAD
5. This leverages git immutability: a commit's content never changes

---

## 6. Git Integration

### Operations (all via popen, no libgit2)
```c
tix_err_t tix_git_rev_parse_head(char *out, sz out_len);
tix_err_t tix_git_current_branch(char *out, sz out_len);
tix_err_t tix_git_is_clean(int *is_clean);
tix_err_t tix_git_commit(const char *message, const char *file);
tix_err_t tix_git_add(const char *file);
tix_err_t tix_git_log_file(const char *file, tix_git_log_entry_t *entries, u32 *count, u32 max);
tix_err_t tix_git_toplevel(char *out, sz out_len);
```

### Commit Policy
tix **never auto-commits**. All mutations (add, done, accept, reject, delete, prioritize)
write to `plan.jsonl` and update the SQLite cache, but leave the file uncommitted.
The caller (orchestrator, user, CI) decides when to `git add` + `git commit`.

`tix_git_commit()` and `tix_git_add()` are available in the API for callers that want
to commit programmatically, but no tix command invokes them.

`tix task done` reads the current HEAD hash via `git rev-parse --short HEAD` to
record `done_at`, but does not create a commit.

### Branch Tracking
- Each ticket can be associated with a branch
- `tix task done` records current branch + HEAD commit hash
- `tix status` shows tickets grouped by branch

---

## 7. CLI Commands

### Command Table
| Command | Subcommand | Description |
|---------|------------|-------------|
| `tix init` | | Create `.tix/` directory with default config |
| `tix task` | `add <json>` | Add task (single or batch JSON array) |
| | `done [id]` | Mark task done, record commit hash |
| | `accept [id]` | Accept done task, create tombstone |
| | `reject <id> "reason"` | Reject done task, create tombstone |
| | `delete <id>` | Remove task |
| | `prioritize <id> <level>` | Set priority (high/medium/low) |
| `tix issue` | `add '<json>'` | Create issue |
| | `done [id]` | Resolve issue |
| | `done-all` | Resolve all issues |
| | `done-ids <id>...` | Resolve specific issues |
| `tix note` | `add "text"` | Add note |
| | `list` | List all notes |
| | `done <id>` | Archive note |
| `tix query` | (none) | Full state as JSON |
| | `tasks [--done]` | Pending (or done) tasks as JSON |
| | `issues` | Issues as JSON |
| | `stage` | Current stage |
| `tix status` | | Human-readable dashboard |
| `tix log` | `[--all] [--spec <f>]` | Git history of changes |
| `tix tree` | `[id]` | Dependency tree visualization |
| `tix report` | | Progress tracking report |
| `tix search` | `<query>` | LLM-friendly keyword search |
| `tix validate` | | History integrity validation |
| `tix batch` | `<file>` | Execute batch operations from file |
| `tix compact` | | Rebuild from git history, rewrite plan.jsonl with only live tickets |

### JSON Output Format (for LLM consumption)
```json
{
  "tickets": {
    "tasks": {"pending": [...], "done": [...], "accepted": [...]},
    "issues": [...],
    "notes": [...]
  },
  "tombstones": {"accepted": [...], "rejected": [...]},
  "meta": {"commit": "abc123", "branch": "main", "spec": "coverage.md"}
}
```

---

## 8. Search & Keyword Cloud

### Keyword Extraction
- Extract from: name, notes, accept criteria
- Tokenize on whitespace + punctuation
- Skip stop words (the, a, an, is, are, was, etc.)
- Normalize to lowercase
- Store with weight: name keywords = 3.0, notes = 1.0, accept = 2.0

### LLM Search Interface
`tix search "memory leak parser"` returns:
```json
{
  "query": "memory leak parser",
  "results": [
    {"id": "t-a1b2", "name": "Fix parser memory", "score": 0.95, "keywords": ["memory", "parser", "leak"]},
    ...
  ],
  "keyword_cloud": {
    "memory": 5, "parser": 12, "test": 8, "fix": 3, ...
  }
}
```

---

## 9. Tree Visualization

### ASCII Dependency Tree
```
tix tree t-root
  t-root: Implement feature X [pending]
  ├── t-a1b2: Design API [done]
  │   └── t-c3d4: Write tests [pending]
  ├── t-e5f6: Implement core [pending]  (blocked by: t-a1b2)
  └── t-g7h8: Documentation [pending]  (blocked by: t-e5f6)
```

### Report Output
```
tix report
  Progress Report
  ===============
  Total: 15 tasks, 3 issues, 2 notes
  Done:  8/15 (53%)
  Blocked: 2 (waiting on dependencies)

  By Priority:
    High:   3 pending, 2 done
    Medium: 4 pending, 3 done
    Low:    1 pending, 3 done

  By Spec:
    coverage.md:  5/8 done
    refactor.md:  3/7 done

  Recent Activity (last 5):
    [2026-02-05] t-a1b2 done (abc123)
    [2026-02-04] t-c3d4 accepted
    ...
```

---

## 10. Build System

### CMake Configuration (mirrors Valkyria)
- CMake 3.20+ (lower than Valkyria since no C23 needed - using C11)
- Ninja generator via Makefile wrapper
- C11 standard (not C23 - for wider compiler compat, no GNU extensions needed)
- Compiler: system clang or gcc (both supported)
- SQLite3 bundled as amalgamation (no external dep)
- `-Wall -Wextra -Wpedantic -Werror` (fail on all warnings)
- Additional NASA-style flags: `-Wconversion -Wshadow -Wstrict-prototypes -Wold-style-definition`
- ASAN/TSAN build variants
- Single CMakeLists.txt (all in app/tix/)

### Makefile Targets
| Target | Description |
|--------|-------------|
| `make build` | Default build |
| `make build-asan` | ASAN build |
| `make test` | Run all E2E tests |
| `make test-asan` | Tests with ASAN |
| `make lint` | run-clang-tidy |
| `make clean` | Remove build dirs |
| `make help` | Show available targets |

### SQLite Bundling
SQLite amalgamation (`sqlite3.c` + `sqlite3.h`) is vendored in `app/tix/vendor/sqlite/`.
Built as part of the tix target. No system SQLite dependency.

---

## 11. Testing Strategy

### E2E Tests (real git, real filesystem)
Each test:
1. Creates a temp directory with `mkdtemp`
2. Runs `git init` in it
3. Creates `.tix/` via `tix init`
4. Exercises tix commands via the compiled binary (popen or direct function calls)
5. Verifies git state (commits, branches) and SQLite state
6. Cleans up temp directory

### Test Framework (mirrors Valkyria's testing.h)
- Fork-based isolation (each test in child process)
- Timeout per test (default 10s)
- ASSERT_EQ, ASSERT_STR_EQ, ASSERT_TRUE, etc.
- Test suite registration pattern:
```c
int main(void) {
  tix_test_suite_t *suite = tix_testsuite_create(__FILE__);
  tix_testsuite_add(suite, "test_task_add", test_task_add);
  tix_testsuite_add(suite, "test_task_done", test_task_done);
  int result = tix_testsuite_run(suite);
  tix_testsuite_print(suite);
  tix_testsuite_free(suite);
  return result;
}
```

### Test Coverage Requirements
- Every CLI command has at least one E2E test
- Error paths tested (invalid args, missing .tix/, corrupt DB)
- Git integration tested (commits created, hashes recorded)
- Search functionality tested (keyword extraction, FTS queries)
- Tree visualization tested (correct ASCII output)
- Batch operations tested (multi-ticket ops)
- History validation tested (corrupt/valid histories)

---

## 12. Integration Points

### Bootstrap (bootstrap.sh)
`powerplant/tix` is a **wrapper script** (not a binary) that:
1. Locates the real binary at `app/tix/build/tix`
2. If missing, downloads SQLite amalgamation and runs `make build` automatically
3. `exec`s the real binary transparently (signals, exit codes pass through)

`bootstrap.sh` pre-builds tix during setup (optional, since the wrapper auto-builds).
No `make install` step needed — local development just uses `make build` and the
wrapper always picks up the latest binary from `app/tix/build/tix`.

### OpenCode Tool (.opencode/tools/tix-status.ts)
Read `.tix/cache.db` or shell out to `tix query`.

### OpenCode Skill (.opencode/skills/tix/SKILL.md)
Skill for LLMs to understand tix workflow and commands.

### Claude Commands (.claude/commands/tix-*.md)
- `tix-status.md` - Show tix status
- `tix-task.md` - Execute one task from plan

### Agentic Flow Integration
tix outputs JSON on stdout for programmatic consumption.
All commands return exit code 0 on success, non-zero on failure.
`tix query` returns full state as structured JSON for LLM parsing.
`tix search` returns scored results for RAG-style retrieval.

---

## 13. Coding Rules (NASA Power of 10)

1. **No dynamic memory allocation** - all buffers stack-allocated with known bounds
2. **All loops must have a fixed upper bound** - use TIX_MAX_* constants
3. **No recursion** - use iterative algorithms with explicit stacks
4. **Assertions for all invariants** - TIX_ASSERT on every precondition
5. **Minimal scope for variables** - declare at point of use
6. **Check all return values** - every function call's return checked
7. **Limit pointer dereferences** - max 2 levels of indirection
8. **No function pointers** (except command dispatch table) - prefer switch/if
9. **Compile with all warnings enabled** - treat warnings as errors
10. **Source files < 1000 lines, nesting < 3 levels deep**

### Error Handling Pattern
```c
tix_err_t tix_some_operation(const char *arg, char *out, sz out_len) {
  if (arg == NULL || out == NULL) { return TIX_ERR_INVALID_ARG; }
  if (out_len < TIX_MAX_ID_LEN) { return TIX_ERR_OVERFLOW; }

  char buf[TIX_MAX_LINE_LEN];
  tix_err_t err = tix_git_rev_parse_head(buf, sizeof(buf));
  if (err != TIX_OK) { return err; }

  // ... do work ...
  return TIX_OK;
}
```

---

## 14. Valkyria Patterns to Mirror

### From Valkyria's CMakeLists.txt
- `cmake_minimum_required(VERSION 3.20)`
- `project(tix LANGUAGES C)`
- `set(CMAKE_C_STANDARD 11)` (C11, not C23 - wider compat)
- `CMAKE_EXPORT_COMPILE_COMMANDS ON`
- ASAN/TSAN via options
- Explicit source file listing (no globs)

### From Valkyria's Makefile
- Ninja generator via `cmake -G Ninja`
- `cmake_configure` macro for build dir setup
- `do_build` macro for cmake --build
- `run_tests` macro for test execution
- Per-build-variant directories: `build/`, `build-asan/`

### From Valkyria's Code Style
- `snake_case` functions/variables with `tix_` prefix
- `UPPER_SNAKE_CASE` macros with `TIX_` prefix
- Types with `_t` suffix, enums with `_e` suffix
- `#pragma once` for header guards
- 2-space indentation
- System headers in `<>`, project headers in `""`
- Minimal comments (code should be self-documenting)

### From Valkyria's Test Framework
- `TIX_TEST_ARGS()` macro for test function signature
- `TIX_TEST()` macro to start timing
- `TIX_PASS()` / `TIX_FAIL()` for results
- Fork-based isolation in child processes
- Ring buffer stdout/stderr capture

---

## 15. TOML Parsing Strategy

Since we want zero dependencies and no malloc, TOML parsing is minimal:
- Only support flat key-value pairs and one level of sections
- Parse line-by-line into fixed-size buffers
- No arrays, no inline tables, no multiline strings
- Sufficient for `[repo] main_branch = "main"` style config

```c
typedef struct {
  char section[64];
  char key[64];
  char value[256];
} tix_toml_entry_t;

tix_err_t tix_toml_parse(const char *path, tix_toml_entry_t *entries,
                          u32 *count, u32 max_entries);
```

---

## 16. plan.jsonl Compatibility

tix uses `plan.jsonl` as its source of truth, with SQLite as a read cache.
Primary storage remains the JSONL file committed to git.

### Append-Only Model

All mutations append new lines to `plan.jsonl` rather than rewriting the file:

| Operation | What gets appended |
|---|---|
| `task add` | New ticket line |
| `task done` | Updated ticket line (status=d, done_at set) |
| `task accept` | Tombstone line (accept) |
| `task reject` | Tombstone line (reject) + updated ticket line (status=p) |
| `task delete` | Delete marker: `{"t":"delete","id":"..."}` |
| `task prioritize` | Updated ticket line (priority changed) |
| `issue done` | Delete marker |
| `note done` | Delete marker |

Between compactions the file may contain duplicate entries for the same ticket ID.
The SQLite cache rebuild handles this via last-write-wins (later lines override
earlier ones for the same ID). Delete markers and accept tombstones remove the
ticket from the cache during replay.

This design makes git merges of concurrent branches safe: appends from different
branches touching different tickets produce changes on different lines, so git
auto-merges cleanly.

### Compaction

`tix compact` rebuilds the complete picture and rewrites `plan.jsonl`:

1. Walks full git history of `plan.jsonl` (all commits that touched it)
2. Replays every historical version into SQLite, oldest first
3. Replays the current working tree version on top
4. Rewrites `plan.jsonl` with only live tickets, sorted by ID
5. Tombstones, delete markers, and stale duplicate entries are dropped

The result is a minimal file containing only actionable work. Nothing is lost -
`git log -p -- plan.jsonl` preserves the full audit trail.

Compaction is triggered by the orchestrator (not by tix automatically), typically:
- Before merging a feature branch to main
- At the end of an agent session
- When the file grows large with stale entries

### Commit Policy

tix never auto-commits. All mutations write to `plan.jsonl` and update the SQLite
cache, but leave the file uncommitted. The caller decides when to commit.

### Default Location

The default plan file location is `.tix/plan.jsonl`. tix also supports a
legacy fallback to `ralph/plan.jsonl` for repos that store their plan file there.

| `.tix/plan.jsonl` | `ralph/plan.jsonl` | Result |
|---|---|---|
| exists | exists | Uses `.tix/plan.jsonl` |
| exists | missing | Uses `.tix/plan.jsonl` |
| missing | exists | Falls back to `ralph/plan.jsonl` |
| missing | missing | Uses `.tix/plan.jsonl` (created on first write) |

The location can be overridden via `plan_file` in `config.toml` (under `[repo]`).
On `tix init`, if `ralph/plan.jsonl` exists, the config is set to point there
for legacy compatibility.

---

## 17. Vendor Dependencies

```
app/tix/vendor/
  sqlite/
    sqlite3.c        # SQLite amalgamation (~250KB source)
    sqlite3.h        # SQLite header
```

Download from https://sqlite.org/amalgamation.html
Compile with: `-DSQLITE_THREADSAFE=0 -DSQLITE_OMIT_LOAD_EXTENSION`
(single-threaded, no extensions needed)

---

## 18. Performance Targets

| Operation | Target |
|-----------|--------|
| `tix status` (cached) | < 5ms |
| `tix query` (cached) | < 5ms |
| `tix task add` | < 50ms (includes git commit) |
| `tix search` (FTS) | < 10ms |
| `tix tree` | < 10ms |
| Cache rebuild (100 tickets) | < 100ms |
| Cache rebuild (1000 tickets) | < 500ms |

---

## 19. Future Extensions

- Integration with GitHub Issues API (import/export)
- Integration with spec files
- Construct mode orchestration (INVESTIGATE/BUILD/VERIFY loop)
- Multi-repo support
- Conflict resolution for concurrent edits
- Web dashboard (read-only, serves from SQLite)
