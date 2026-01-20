# Agent Mode

## Overview

Agent mode extends Ralph with a persistent execution mode that processes specs from an inbox queue. Unlike construct mode which works on a single spec and exits, agent mode runs continuously, completing one spec then automatically starting the next from the queue. This enables hands-off autonomous development where users can submit specs while Ralph works.

## Requirements

### Mode Distinction

Ralph supports two execution modes:

| Mode | Command | Behavior |
|------|---------|----------|
| **Construct** | `ralph construct [spec]` | Work on planned tasks for current spec, exit when complete |
| **Agent** | `ralph agent` | Process specs from inbox queue continuously until queue empty |

Construct mode remains unchanged - it is the building block that agent mode orchestrates.

### Inbox Queue

The inbox is a persistent queue of specs awaiting processing.

**Storage**: `ralph/inbox.jsonl`

**Record Format**:
```jsonl
{"t": "inbox", "id": "q-a1b2", "spec": "feature-x.md", "added_at": "2025-01-20T10:30:00Z", "status": "pending"}
{"t": "inbox", "id": "q-c3d4", "spec": "bugfix-y.md", "added_at": "2025-01-20T11:00:00Z", "status": "pending"}
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `t` | string | Always `"inbox"` |
| `id` | string | Unique ID matching pattern `q-[a-z0-9]{4}` |
| `spec` | string | Spec filename (relative to `ralph/specs/`) |
| `added_at` | string | ISO 8601 timestamp |
| `status` | string | `"pending"`, `"active"`, `"done"`, `"failed"` |
| `started_at` | string? | ISO 8601 timestamp when processing began |
| `completed_at` | string? | ISO 8601 timestamp when processing finished |
| `error` | string? | Error message if status is `"failed"` |

**Queue Ordering**: FIFO - specs are processed in the order they were added.

### CLI Commands

#### Submit Spec to Inbox

```bash
ralph inbox add <spec.md>
```

- Validates spec file exists in `ralph/specs/`
- Generates unique queue ID (`q-xxxx`)
- Appends record to `ralph/inbox.jsonl` with status `"pending"`
- Prints: `Queued: q-xxxx <spec.md>`

#### List Inbox

```bash
ralph inbox
ralph inbox list
```

Output format:
```
Inbox (3 specs):
  q-a1b2  pending   feature-x.md      (added 2h ago)
  q-c3d4  pending   bugfix-y.md       (added 1h ago)
  q-e5f6  active    refactor-z.md     (started 10m ago)
```

#### Remove from Inbox

```bash
ralph inbox remove <id>
ralph inbox remove <spec.md>
```

- Removes matching record from inbox
- Cannot remove `"active"` specs (must stop agent first)
- Prints: `Removed: q-xxxx <spec.md>`

#### Clear Inbox

```bash
ralph inbox clear
```

- Removes all `"pending"` specs from inbox
- Does not affect `"active"`, `"done"`, or `"failed"` records
- Prints: `Cleared N pending specs`

#### Query Inbox

```bash
ralph query inbox
```

Returns JSON array of all inbox records:
```json
[
  {"id": "q-a1b2", "spec": "feature-x.md", "status": "pending", "added_at": "..."},
  ...
]
```

### Agent Mode Execution

#### Start Agent

```bash
ralph agent
ralph agent --max-specs 5
ralph agent --max-cost 10.00
```

**Options**:

| Option | Default | Description |
|--------|---------|-------------|
| `--max-specs N` | unlimited | Stop after completing N specs |
| `--max-cost N` | unlimited | Stop when cumulative cost exceeds $N |
| `--max-failures N` | 3 | Stop after N consecutive spec failures |
| `--dry-run` | false | Plan each spec but don't execute |

**Execution Loop**:

```
┌─────────────────────────────────────────────────────────┐
│                     AGENT LOOP                          │
│                                                         │
│  ┌─────────┐     ┌──────────┐     ┌─────────────────┐  │
│  │  FETCH  │────>│   PLAN   │────>│    CONSTRUCT    │  │
│  │  next   │     │   spec   │     │   (full loop)   │  │
│  │  spec   │     │          │     │                 │  │
│  └─────────┘     └──────────┘     └────────┬────────┘  │
│       ^                                     │           │
│       │         ┌──────────┐               │           │
│       └─────────│  COMMIT  │<──────────────┘           │
│                 │  & mark  │                           │
│                 │  done    │                           │
│                 └──────────┘                           │
└─────────────────────────────────────────────────────────┘
```

**FETCH Stage**:
1. Read `ralph/inbox.jsonl`
2. Find first record with status `"pending"`
3. If none found, exit with message: `Inbox empty. Agent stopping.`
4. Update record: `status: "active"`, `started_at: <now>`
5. Set spec as current: write `{"t": "spec", "spec": "<file>"}` to plan.jsonl

**PLAN Stage**:
1. Run `ralph plan <spec>` to generate tasks from spec
2. If planning fails, mark spec as `"failed"` with error, continue to next

**CONSTRUCT Stage**:
1. Run full construct mode state machine (INVESTIGATE -> BUILD -> VERIFY loop)
2. Construct mode runs until COMPLETE or circuit breaker trips

**COMMIT Stage**:
1. Create git commit with all changes from this spec
2. Commit message format: `ralph: complete <spec-name>`
3. Update inbox record: `status: "done"`, `completed_at: <now>`
4. Loop back to FETCH

#### Stop Agent

Agent stops when any condition is met:
- Inbox is empty (all specs processed)
- `--max-specs` limit reached
- `--max-cost` limit exceeded
- `--max-failures` consecutive failures reached
- User sends SIGINT (Ctrl+C)

On SIGINT:
1. Complete current construct iteration (don't kill mid-task)
2. Mark current spec as `"pending"` (will resume on next agent start)
3. Exit cleanly

#### Agent Status

```bash
ralph status
```

Extended output when agent mode active:
```
Mode: agent
Current spec: refactor-z.md (q-e5f6)
Inbox: 2 pending, 1 active, 5 done, 0 failed
Session: 3 specs completed, $2.45 spent, 1h 23m elapsed

[existing construct status output...]
```

### State Persistence

Agent mode state survives restarts:

1. **Inbox state** (`ralph/inbox.jsonl`) - Queue records with statuses
2. **Current spec** (`ralph/plan.jsonl`) - Active spec and tasks
3. **Session stats** (`ralph/.agent-session`) - Current agent session metadata

**Session File Format** (`ralph/.agent-session`):
```json
{
  "started_at": "2025-01-20T10:00:00Z",
  "specs_completed": 3,
  "specs_failed": 0,
  "total_cost": 2.45,
  "current_spec_id": "q-e5f6"
}
```

Session file is deleted when agent exits normally (inbox empty or limit reached).

### Resumption Behavior

When `ralph agent` starts:

1. Check for `ralph/.agent-session`
2. If exists (previous agent interrupted):
   - Resume session stats
   - Find spec with `status: "active"` in inbox
   - Continue construct mode from current state
3. If not exists (fresh start):
   - Create new session file
   - Begin FETCH stage

### Git Integration

Agent mode creates atomic commits per spec:

**During CONSTRUCT**: No commits (working tree may be dirty)

**On Spec Completion**:
1. Stage all changes: `git add -A`
2. Create commit: `git commit -m "ralph: complete <spec-name>"`
3. Include spec summary in commit body:
   ```
   ralph: complete feature-x
   
   Spec: ralph/specs/feature-x.md
   Tasks completed: 8
   Duration: 15m 32s
   Cost: $0.82
   ```

**On Spec Failure**:
1. Stash or reset uncommitted changes (configurable)
2. Mark spec as failed in inbox
3. Continue to next spec

Default behavior: stash changes with message `ralph: failed <spec-name>`

### Error Handling

| Error Condition | Response |
|-----------------|----------|
| Spec file not found | Mark `"failed"`, log error, continue |
| Plan generation fails | Mark `"failed"`, log error, continue |
| Construct circuit breaker trips | Mark `"failed"`, log error, continue |
| Git commit fails | Retry once, then mark `"failed"` |
| Inbox file corrupt | Exit with error, require manual fix |

### Logging

Agent mode logs to `build/ralph-logs/agent-<timestamp>.log`:

```
[2025-01-20T10:00:00Z] Agent started
[2025-01-20T10:00:01Z] FETCH: q-a1b2 feature-x.md
[2025-01-20T10:00:05Z] PLAN: 8 tasks generated
[2025-01-20T10:00:06Z] CONSTRUCT: starting iteration 1
...
[2025-01-20T10:15:32Z] CONSTRUCT: complete
[2025-01-20T10:15:33Z] COMMIT: abc1234 "ralph: complete feature-x"
[2025-01-20T10:15:34Z] FETCH: q-c3d4 bugfix-y.md
...
[2025-01-20T11:23:45Z] Inbox empty. Agent stopping.
[2025-01-20T11:23:45Z] Session summary: 3 specs, $2.45, 1h 23m
```

## Acceptance Criteria

### Inbox Management
- [ ] `ralph inbox add <spec>` creates record in `ralph/inbox.jsonl` with status `"pending"`
- [ ] `ralph inbox add` fails with error if spec file doesn't exist
- [ ] `ralph inbox` lists all inbox records with status, spec name, and relative time
- [ ] `ralph inbox remove <id>` removes pending record from inbox
- [ ] `ralph inbox remove` fails with error when trying to remove active spec
- [ ] `ralph inbox clear` removes all pending specs, preserves active/done/failed
- [ ] `ralph query inbox` returns JSON array of all inbox records

### Agent Execution
- [ ] `ralph agent` processes specs from inbox in FIFO order
- [ ] Agent updates inbox record to `"active"` before starting each spec
- [ ] Agent runs `ralph plan` then full construct loop for each spec
- [ ] Agent creates git commit after each successful spec completion
- [ ] Agent marks spec as `"done"` with `completed_at` timestamp on success
- [ ] Agent marks spec as `"failed"` with error message on failure
- [ ] Agent continues to next spec after failure (doesn't exit)
- [ ] Agent exits cleanly when inbox is empty

### Limits and Options
- [ ] `--max-specs N` stops agent after N specs completed
- [ ] `--max-cost N` stops agent when cumulative cost exceeds $N
- [ ] `--max-failures N` stops agent after N consecutive failures
- [ ] Consecutive failure counter resets on successful spec completion

### Graceful Shutdown
- [ ] SIGINT allows current construct iteration to complete
- [ ] SIGINT marks current spec as `"pending"` (not `"active"`)
- [ ] Second SIGINT forces immediate exit

### State Persistence
- [ ] Agent session state persists in `ralph/.agent-session`
- [ ] `ralph agent` resumes interrupted session if `.agent-session` exists
- [ ] Session file deleted on normal agent exit

### Status Reporting
- [ ] `ralph status` shows agent mode info when agent session active
- [ ] Status includes: current spec, inbox counts, session stats

### Git Integration
- [ ] Commit created for each completed spec with message `ralph: complete <name>`
- [ ] Commit body includes spec path, task count, duration, cost
- [ ] Failed specs have changes stashed (not committed)

### Construct Mode Unchanged
- [ ] `ralph construct [spec]` behavior unchanged (single spec, exit on complete)
- [ ] Construct mode does not read or modify inbox
