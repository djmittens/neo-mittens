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

Use this skill when managing tasks, issues, and notes through the `tix` CLI. tix is a high-performance C binary that replaces Ralph's Python ticket system, reading and writing `ralph/plan.jsonl`.

## Quick Reference

```bash
tix init                          # Initialize .tix/ in current repo
tix status                        # Human-readable dashboard
tix query                         # Full state as JSON
tix task add '<json>'             # Add task(s)
tix task done [id]                # Mark task done
tix task accept <id>              # Accept done task
tix task reject <id> "reason"     # Reject done task
tix issue add "description"       # Add issue
tix issue done [id]               # Resolve issue
tix search "keywords"             # Search tickets
tix tree [id]                     # Dependency tree
tix report                        # Progress report
tix validate                      # Integrity check
tix log                           # Git history of plan changes
```

## Data Flow

```
ralph/plan.jsonl  <---->  tix  <---->  .tix/cache.db (SQLite)
      |                                      |
   git tracked                          gitignored
   (primary storage)                    (read cache)
```

tix reads/writes `ralph/plan.jsonl` (the git-tracked source of truth) and caches state in `.tix/cache.db` for fast reads. The cache is rebuilt automatically when the git HEAD changes.

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
├── t-a1b2: Design API [done]
│   └── t-c3d4: Write tests [pending]
└── t-e5f6: Implement core [pending]  (blocked by: t-a1b2)
```

## Validation

```bash
tix validate
```

Checks:
- Dependency references exist
- No orphan dependencies
- Tombstone consistency
- ID uniqueness

## Batch Operations

```bash
tix batch operations.json         # From file
tix batch '[{"op": "task_add", "data": {...}}, ...]'  # Inline JSON
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TIX_LOG=<level>` | Set log level: `error`, `warn`, `info`, `debug`, `trace` |

## plan.jsonl Format

tix reads/writes Ralph's `plan.jsonl` format:
```jsonl
{"t": "config", "timeout_ms": 900000, "max_iterations": 10}
{"t": "spec", "spec": "coverage.md"}
{"t": "stage", "stage": "BUILD"}
{"t": "task", "id": "t-1a2b", "spec": "coverage.md", "name": "...", "s": "p"}
{"t": "issue", "id": "i-7g8h", "spec": "coverage.md", "desc": "..."}
{"t": "accept", "id": "t-1a2b", "done_at": "abc123", "reason": ""}
{"t": "reject", "id": "t-3c4d", "done_at": "def456", "reason": "..."}
```

## ID Format

- Tasks: `t-{hex8}` (e.g., `t-a1b2c3d4`)
- Issues: `i-{hex8}` (e.g., `i-a1b2c3d4`)
- Notes: `n-{hex8}` (e.g., `n-a1b2c3d4`)

## Integration with Ralph

tix is the backend for Ralph's ticket operations. Ralph calls tix for:
- Task CRUD (add, done, accept, reject, delete, prioritize)
- Issue CRUD (add, done, done-all, done-ids)
- State queries (query, status)
- Validation and reporting

The plan.jsonl file is shared between Ralph and tix. Both can read/write it.

## Building tix

```bash
cd app/tix
make build        # Debug build
make test         # Run all 31 tests
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

### Investigating issues

```bash
tix issue add "Found problem X"
tix query issues                  # Review open issues
# ... investigate and create tasks ...
tix task add '{"name": "Fix X", "created_from": "i-xxxx", "accept": "..."}'
tix issue done i-xxxx             # Resolve the issue
```
