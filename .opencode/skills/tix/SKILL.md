---
name: tix
description: Use the tix CLI for git-based ticket management - tasks, issues, notes with plan.jsonl compatibility
license: MIT
compatibility: opencode
metadata:
  category: workflow
  tool: tix
---

# Using tix - Git-Based Ticket Management

Use this skill when managing tasks, issues, and notes through the `tix` CLI. tix is a high-performance C binary for git-based ticket management, reading and writing `.tix/plan.jsonl` (with legacy fallback to `ralph/plan.jsonl`).

## Quick Reference

```bash
tix init                          # Initialize .tix/ in current repo
tix status                        # Human-readable dashboard
tix query                         # Full state as JSON
tix task add '<json>'             # Add task(s)
tix task done [id]                # Mark task done
tix task accept <id>              # Accept done task
tix task reject <id> "reason"     # Reject done task
tix task update <id> '<json>'     # Update fields on existing ticket
tix issue add "description"       # Add issue
tix issue done [id]               # Resolve issue
tix search "keywords"             # Search tickets
tix tree [id]                     # Dependency tree
tix report                        # Progress report
tix validate                      # Integrity check
tix log                           # Git history of plan changes
tix sync [branch|--all]           # Sync cache from git history
tix compact                       # Sync + compact plan.jsonl
```

## Data Flow

```
.tix/plan.jsonl  <---->  tix  <---->  .tix/cache.db (SQLite)
      |                                      |
   git tracked                          gitignored
   (primary storage)                    (read cache)
```

tix reads/writes `.tix/plan.jsonl` (the git-tracked source of truth) and caches state in `.tix/cache.db` for fast reads. The cache is rebuilt automatically when plan.jsonl changes or the schema version bumps.

## Task Management

### Adding Tasks

Single task:
```bash
tix task add '{"name": "Implement feature X", "spec": "my-spec.md", "notes": "Details here", "accept": "tests pass", "priority": "high"}'
```

Batch add (faster, supports intra-batch dependencies):
```bash
tix task add '[
  {"name": "Create module A", "spec": "feature.md", "accept": "import works"},
  {"name": "Create module B", "spec": "feature.md", "accept": "import works", "deps": ["t-previous"]}
]'
```

### Task Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Short description |
| `spec` | No | Spec file this belongs to |
| `notes` | No | Implementation details |
| `accept` | No | Acceptance criteria |
| `deps` | No | Array of dependency task IDs |
| `priority` | No | `"high"`, `"medium"`, or `"low"` |
| `parent` | No | Decomposed from task ID |
| `created_from` | No | Created from issue ID |
| `supersedes` | No | Replaces task ID |

### Auto-filled Fields

These fields are populated automatically by tix:

| Field | When | Source |
|-------|------|--------|
| `author` | Ticket creation | `git config user.name` |
| `completed_at` | Task marked done | ISO 8601 timestamp with timezone |
| `branch` | Ticket creation/update | Current git branch |

### Agent Telemetry Fields

These fields are populated by the orchestrator (via `tix task update`) after stage completion:

| Field | Type | Description |
|-------|------|-------------|
| `cost` | float | Total dollar cost for this task |
| `tokens_in` | int | Total input tokens consumed |
| `tokens_out` | int | Total output tokens consumed |
| `iterations` | int | Construct loop iterations |
| `model` | string | Model used (e.g. `"claude-sonnet-4-20250514"`) |
| `retries` | int | Retries after failure before success |
| `kill_count` | int | Times iteration was killed before success |

### Task Lifecycle

```
pending -> done -> accepted (tombstone created)
                -> rejected (tombstone created, may retry)
```

```bash
tix task done                     # Mark current/first pending task done
tix task done t-a1b2c3d4          # Mark specific task done
tix task accept t-a1b2c3d4        # Accept after verification
tix task reject t-a1b2c3d4 "Tests fail on edge case"
tix task delete t-a1b2c3d4        # Remove task entirely
tix task prioritize t-a1b2c3d4 high  # Set priority
tix task update t-a1b2c3d4 '{"cost": 0.52, "tokens_in": 50000}'  # Attach telemetry
```

## Issue Management

Issues are lightweight items for the INVESTIGATE stage:

```bash
tix issue add "Memory leak in parser module"
tix issue done                    # Resolve first issue
tix issue done i-a1b2c3d4         # Resolve specific issue
tix issue done-all                # Resolve all issues
tix issue done-ids i-abc1 i-def2  # Resolve specific issues
```

## Note Management

Notes are informational items:

```bash
tix note add "Discovered that X depends on Y"
tix note list                     # List all notes
tix note done n-a1b2c3d4          # Archive note
```

## Querying State

### Full State (JSON)

```bash
tix query                         # Everything
tix query tasks                   # Pending tasks only
tix query tasks --done            # Done tasks
tix query issues                  # Issues only
tix query full                    # Full state with tombstones
```

Output format:
```json
{
  "tasks": {"pending": [...], "done": [...]},
  "issues": [...],
  "notes": [...],
  "tombstones": {"accepted": [...], "rejected": [...]},
  "meta": {"commit": "abc123", "branch": "main"}
}
```

### Human-Readable

```bash
tix status                        # Dashboard view
tix report                        # Progress tracking
```

## Search

```bash
tix search "memory leak parser"
```

Returns JSON with scored results and keyword cloud:
```json
{
  "query": "memory leak parser",
  "results": [
    {"id": "t-a1b2", "name": "Fix parser memory", "score": 0.95}
  ],
  "keyword_cloud": {"memory": 5, "parser": 12}
}
```

## Dependency Trees

```bash
tix tree                          # Show all roots
tix tree t-a1b2c3d4               # Show tree from specific task
```

ASCII output:
```
t-root: Implement feature X [pending]
+-- t-a1b2: Design API [done]
|   +-- t-c3d4: Write tests [pending]
+-- t-e5f6: Implement core [pending]  (blocked by: t-a1b2)
```

## Validation

```bash
tix validate
```

Checks:
- Dependency references exist (three-state: resolved, stale, broken)
- No orphan dependencies
- Tombstone consistency
- ID uniqueness

## Batch Operations

```bash
tix batch operations.json         # From file
tix batch '[{"op": "task_add", "data": {...}}, ...]'  # Inline JSON
```

## Cache Management

```bash
tix sync                          # Sync cache from current branch git history
tix sync <branch>                 # Sync from specific branch
tix sync --all                    # Sync from all branches
tix compact                       # Sync + rewrite plan.jsonl (dedup, denormalize refs)
```

The SQLite cache uses schema versioning. When the schema version bumps (new fields added), the cache is automatically dropped and rebuilt from plan.jsonl.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TIX_LOG=<level>` | Set log level: `error`, `warn`, `info`, `debug`, `trace` |

## plan.jsonl Format

tix reads/writes `.tix/plan.jsonl` (append-only, line-delimited JSON):
```jsonl
{"t":"task","id":"t-1a2b","name":"...","s":"p","author":"jane","spec":"coverage.md"}
{"t":"task","id":"t-1a2b","name":"...","s":"d","done_at":"abc123","completed_at":"2026-02-07T14:30:00-08:00","cost":0.52,"tokens_in":50000,"tokens_out":3000,"iterations":5,"model":"claude-sonnet-4-20250514"}
{"t":"issue","id":"i-7g8h","name":"...","author":"ralph"}
{"t":"accept","id":"t-1a2b","done_at":"abc123","reason":"","name":"..."}
{"t":"reject","id":"t-3c4d","done_at":"def456","reason":"...","name":"..."}
{"t":"delete","id":"t-5e6f"}
```

Status values (`s`): `"p"` = pending, `"d"` = done, `"a"` = accepted. Zero/empty values are omitted from output.

## ID Format

- Tasks: `t-{hex8}` (e.g., `t-a1b2c3d4`)
- Issues: `i-{hex8}` (e.g., `i-a1b2c3d4`)
- Notes: `n-{hex8}` (e.g., `n-a1b2c3d4`)

## Building tix

```bash
cd app/tix
make build        # Debug build (Ninja)
make build-asan   # AddressSanitizer build
make test         # Run all 94 E2E tests
make test-asan    # Tests under ASAN
make lint         # clang-tidy
make install      # Copy to powerplant/tix
```

## Common Workflows

### Starting a new spec

```bash
tix init                          # If not already initialized
tix task add '[
  {"name": "Task 1", "spec": "my-spec.md", "accept": "criterion 1"},
  {"name": "Task 2", "spec": "my-spec.md", "accept": "criterion 2", "deps": ["t-xxx"]}
]'
tix status                        # Verify state
```

### Working through tasks

```bash
tix query tasks                   # See what's pending
# ... do the work ...
tix task done                     # Mark first pending task done
tix task accept t-xxxx            # Accept after verification
```

### Attaching telemetry after build

```bash
tix task done t-xxxx
tix task update t-xxxx '{"cost": 1.23, "tokens_in": 80000, "tokens_out": 5000, "iterations": 3, "model": "claude-sonnet-4-20250514"}'
```

### Investigating issues

```bash
tix issue add "Found problem X"
tix query issues                  # Review open issues
# ... investigate and create tasks ...
tix task add '{"name": "Fix X", "created_from": "i-xxxx", "accept": "..."}'
tix issue done i-xxxx             # Resolve the issue
```
