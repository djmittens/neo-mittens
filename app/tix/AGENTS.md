# tix Development Rules

## Overview

tix is a high-performance C CLI tool for git-based ticket management.
It replaces Ralph's Python-based ticket system with a zero-allocation C implementation.

## Architecture

- **C11 standard** (not C23), gcc + clang compatible, Linux + macOS
- **No dynamic allocation** - all stack buffers with TIX_MAX_* bounds
- **SQLite cache** (vendored amalgamation) in `.tix/cache.db` (gitignored)
- **plan.jsonl** compatibility with Ralph's existing format
- All output is JSON on stdout (except `status` and `report`)

## Coding Rules (NASA Power of 10 inspired)

1. No source file > 1000 lines
2. No conditional nesting > 3 levels deep
3. No recursion - iterative algorithms with explicit stacks
4. No dynamic allocation (malloc/calloc/realloc)
5. All buffers have TIX_MAX_* size limits
6. All snprintf calls must check return value for truncation
7. `-Wall -Wextra -Wpedantic -Werror -Wconversion -Wshadow` - zero warnings

## Build System

```bash
cd app/tix
make build        # Debug build (Ninja)
make build-asan   # AddressSanitizer build
make test         # Run all 68 E2E tests
make test-asan    # Tests under ASAN
make lint         # clang-tidy
```

`powerplant/tix` is a wrapper script that auto-builds on first run.
No `make install` needed — just `make build` and the wrapper picks up the binary.

## Testing

- Test framework: `test/testing.h` + `test/testing.c` (fork-based isolation)
- 10 test suites, 68 tests covering all modules
- Tests create isolated temp dirs with git repos
- ASAN build disables fork (runs direct)
- All tests must pass before merge

## Key Files

- `TIX_DESIGN.md` - Full architecture document (READ THIS FIRST)
- `src/types.h` - All type definitions and buffer size constants
- `src/common.h` - Error codes, assertions, buffer printf macro
- `src/cmd.h` - Context struct and command handler declarations

## Dependencies

- SQLite amalgamation in `vendor/sqlite/` (not committed, download via `https://sqlite.org/amalgamation.html`)
- CMake >= 3.20, Ninja, gcc or clang
