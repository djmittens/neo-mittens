# Ralph Plan System

## Overview

Replace the markdown-based IMPLEMENTATION_PLAN.md with a JSONL plan file (`ralph/plan.jsonl`) and CLI commands for querying/mutating the plan. This enables task lifecycle tracking, git-based history queries, and LLM-friendly structured output.

## Requirements

### Plan File Format

`ralph/plan.jsonl` stores current work state (JSONL for git-friendly merges):

```jsonl
{"t": "spec", "spec": "coverage.md"}
{"t": "task", "id": "t-1a2b", "spec": "coverage.md", "name": "Add parser unit tests", "notes": "Cover edge cases", "accept": "pytest tests/test_parser.py passes", "s": "p"}
{"t": "task", "id": "t-3c4d", "spec": "coverage.md", "name": "Fix tokenizer edge case", "deps": ["t-1a2b"], "accept": "No panic on malformed input", "s": "p"}
{"t": "task", "id": "t-5e6f", "spec": "coverage.md", "name": "Integration tests", "deps": ["t-1a2b", "t-3c4d"], "accept": "All tests pass", "s": "p"}
{"t": "issue", "id": "i-7g8h", "spec": "coverage.md", "desc": "Flaky test in CI"}
```

#### Task Fields

| Field | Required | Description |
|-------|----------|-------------|
| `t` | yes | Type identifier, always `"task"` |
| `id` | yes | Unique ID with `t-` prefix (e.g., `t-1a2b`) |
| `spec` | yes | Spec file this task belongs to |
| `name` | yes | Short task name (what to do) |
| `notes` | no | Implementation notes/context (how to do it) |
| `accept` | no | Acceptance criteria / test plan (how to verify) |
| `deps` | no | List of task IDs this depends on (e.g., `["t-1a2b", "t-3c4d"]`) |
| `s` | yes | Status: `"p"` (pending) or `"d"` (done) |
| `done_at` | no | Commit hash when marked done |
| `priority` | no | Priority level: `"high"`, `"medium"`, or `"low"` |
| `reject` | no | Rejection reason if task failed VERIFY and is being retried |
| `kill` | no | Kill reason: `"timeout"` or `"context"` if iteration was killed |
| `kill_log` | no | Path to log file from killed iteration |
| `parent` | no | Task ID this was decomposed from (set by DECOMPOSE stage) |
| `created_from` | no | Issue ID this task was created from (set by INVESTIGATE stage) |
| `supersedes` | no | Task ID this replaces (when rejection leads to new approach vs retry) |

Tasks are executed in topological order based on dependencies. A task is "blocked" until all its dependencies are done.

#### Task Relationships

Tasks can have three types of relationships:

1. **`parent`**: Set when DECOMPOSE breaks a killed task into subtasks. Enables tracing "why does this task exist?" back to the original oversized task.

2. **`created_from`**: Set when INVESTIGATE creates a task from an issue. Enables tracing "why does this task exist?" back to the discovered issue.

3. **`supersedes`**: Set when a rejected task is replaced with a completely new approach rather than retried. The old task remains rejected; the new task supersedes it.

#### Issue Fields

| Field | Required | Description |
|-------|----------|-------------|
| `t` | yes | Type identifier, always `"issue"` |
| `id` | yes | Unique ID with `i-` prefix (e.g., `i-5e6f`) |
| `spec` | yes | Spec file this issue relates to |
| `desc` | yes | Issue description |

#### Notes

- Task/issue IDs are short random strings
- File is committed to git after each mutation
- The top-level `{"t": "spec", ...}` line indicates the *current* active spec

### Git Behavior

The plan.jsonl file is designed to work well with git operations:

#### JSONL Format Benefits
- **Line-based**: Each task/issue is one line, minimizing merge conflicts
- **Append-friendly**: New tasks are added as new lines
- **Independent records**: No array syntax means no comma conflicts

#### Merge Conflicts
If a merge conflict occurs in plan.jsonl:
- Each line is independent - resolve by keeping both versions of conflicting lines
- Duplicate task IDs should not occur (random 4-char suffix)
- If duplicates somehow occur, ralph will load both but behavior is undefined

#### Rebases and Squashes
- **Rebase**: Safe. The `done_at` commit hashes will point to pre-rebase commits (now orphaned), but this is acceptable - they serve as timestamps, not references
- **Squash**: Safe. Same as rebase - old commit hashes become orphaned but harmless
- **Interactive rebase**: If commits that modified plan.jsonl are dropped, the file state will reflect the surviving commits

#### Branch Workflows
- **Feature branches**: Each branch has its own plan.jsonl state. Merge to main when spec is complete
- **Parallel work**: Two developers can work on different specs on different branches without conflict
- **Same spec, different branches**: May cause conflicts - coordinate or use separate specs

#### Reset and Revert
- `git reset --hard`: Will lose uncommitted plan changes (ralph auto-commits, so this is rare)
- `git revert`: Creates inverse commit, may leave plan in inconsistent state - manually fix plan.jsonl if needed

#### Best Practices
1. Complete a spec before switching branches
2. Commit plan.jsonl changes atomically with related code changes (ralph does this automatically)
3. Don't manually edit plan.jsonl - use ralph CLI commands
4. If plan gets corrupted, delete plan.jsonl and re-run `ralph plan <spec>`

### CLI Commands

#### Query Commands

| Command | Output | Description |
|---------|--------|-------------|
| `ralph query` | JSON | Full current state |
| `ralph query tasks` | JSON | Just tasks (pending + done) |
| `ralph query issues` | JSON | Just issues |
| `ralph query stage` | String | Current stage: PLAN, BUILD, VERIFY, INVESTIGATE, or COMPLETE |
| `ralph query next` | JSON | Next action to take with item |

#### Mutation Commands

| Command | Description |
|---------|-------------|
| `ralph task done` | Move first pending task to done, record commit |
| `ralph task add "desc"` | Add task to pending |
| `ralph task accept` | Clear all done tasks (validation passed) |
| `ralph issue done` | Remove first issue |
| `ralph issue add "desc"` | Add issue |
| `ralph set-spec <file>` | Set current spec |

All mutations:
1. Update plan.jsonl
2. Auto-commit with descriptive message
3. Print updated state

#### History Commands

| Command | Description |
|---------|-------------|
| `ralph log` | Recent state changes |
| `ralph log --all` | All tasks ever (reconstructed from git) |
| `ralph log --spec <file>` | History for a specific spec |
| `ralph log --branch <name>` | Work done on a branch |
| `ralph log --since <date>` | Changes since date/commit |

History output format:

```json
{
  "tasks": [
    {
      "id": "t-3c4d",
      "desc": "Fix edge case in tokenizer",
      "spec": "coverage.md",
      "branch": "feature/coverage",
      "author": "user@email",
      "created": {"commit": "aaa111", "date": "2026-01-18T10:00:00"},
      "done": {"commit": "bbb222", "date": "2026-01-18T10:30:00"},
      "accepted": {"commit": "ccc333", "date": "2026-01-18T11:00:00"}
    }
  ]
}
```

### Task Lifecycle

```
pending → done → accepted (removed from file, in git history)
                ↘ rejected (tombstone, retried or new task created)
```

1. `ralph plan <spec>` creates tasks in `pending`
2. `ralph task done` moves task to `done` with commit hash
3. BUILD stage repeats until `pending` is empty
4. VERIFY stage validates `done` tasks against spec
5. If verified: `ralph task accept` clears `done` tasks
6. If rejected: `ralph task reject` adds tombstone, moves task back to pending (or creates new task)
7. INVESTIGATE handles issues similarly

### Task Rejection

When VERIFY determines a "done" task doesn't meet its acceptance criteria, it must be rejected rather than accepted. This creates a tombstone record for audit purposes.

#### Tombstone Format

```jsonl
{"t": "reject", "id": "t-1a2b", "done_at": "abc123", "reason": "Output format doesn't match spec"}
```

| Field | Required | Description |
|-------|----------|-------------|
| `t` | yes | Type identifier, always `"reject"` |
| `id` | yes | Task ID that was rejected |
| `done_at` | yes | The commit hash where task was marked done |
| `reason` | yes | Why the task was rejected |

#### Rejection Flow

1. Worker marks task done → commit with `s: "d"`, `done_at: "abc123"`
2. VERIFY checks task against acceptance criteria
3. If rejected:
   - Add tombstone: `{"t": "reject", "id": "t-1a2b", "done_at": "abc123", "reason": "..."}`
   - Either move task back to pending (`s: "p"`) for retry, or create new task
4. Next `ralph plan <new-spec>` clears all tombstones (they served their audit purpose)

#### CLI Command

| Command | Description |
|---------|-------------|
| `ralph task reject "reason"` | Reject first done task with reason, add tombstone, move back to pending |

#### History Interpretation

`ralph log --all` uses tombstones to distinguish outcomes:

| Task State | Tombstone | Interpretation |
|------------|-----------|----------------|
| `done_at` set, removed from file | None | Accepted (completed successfully) |
| `done_at` set, removed from file | Present | Rejected (attempted but failed verification) |
| No `done_at`, removed from file | N/A | Cancelled (never attempted) |

#### Git Durability

Tombstones are stored in plan.jsonl, so they survive:
- Merges
- Rebases  
- Squashes
- Force pushes

They are ephemeral - cleaned up on next `ralph plan` - but persist in git history for audit.

### Stage Logic

`ralph query stage` computes current stage:

- `PLAN` - No spec set or plan.jsonl missing
- `BUILD` - Has pending tasks
- `VERIFY` - No pending tasks, has done tasks
- `INVESTIGATE` - No pending/done tasks, has issues
- `COMPLETE` - Empty state (spec finished)

### Pre-flight Checks

#### Build Command

`ralph build` requires plan.jsonl to be committed before starting. If uncommitted changes exist:
- Prompt user: "plan.jsonl has uncommitted changes. Commit now? [Y/n]"
- Y/Enter: auto-commit with message "ralph: update plan"
- n/Ctrl+C: abort

#### Plan Command - Unfinished Tasks

When running `ralph plan <new-spec>` and there are existing pending or done tasks from a previous spec, prompt the user with options:

```
Found unfinished tasks from spec 'old-spec.md':
  - [pending] t-1a2b: Add unit tests for parser
  - [done] t-3c4d: Fix edge case in tokenizer

What would you like to do?
  [c] Cancel existing tasks and start fresh
  [a] Abort (keep current plan)
```

- **Cancel (c)**: Remove all tasks from plan.jsonl (they remain in git history as cancelled)
- **Abort (a)**: Exit without changes, user can finish current work first

This prevents accidentally losing work when switching specs.

### Stage-based Prompts

Each stage uses a dedicated prompt file:

| Stage | Prompt File | Purpose |
|-------|-------------|---------|
| PLAN | `PROMPT_plan.md` | Gap analysis, task creation |
| BUILD | `PROMPT_build.md` | Implement one task |
| VERIFY | `PROMPT_verify.md` | Check spec completeness |
| INVESTIGATE | `PROMPT_investigate.md` | Research and resolve issues |

The build loop automatically selects the prompt based on current stage from `ralph query stage`.

### Integration with Build Loop

Update `ralph plan <spec>`:
- Check for unfinished tasks (see Pre-flight Checks above)
- Calls `ralph set-spec <spec>`
- Generates tasks via LLM
- Calls `ralph task add` for each task

Build loop (`ralph` or `ralph build`):
- Each iteration: load state, get stage, select prompt, run LLM
- `ralph query` for state inspection
- `ralph task done` to complete tasks
- `ralph issue add` for discovered issues

### Remove IMPLEMENTATION_PLAN.md

- Delete template from `ralph init`
- Remove all references to IMPLEMENTATION_PLAN.md in prompts
- plan.jsonl is the single source of truth

## Acceptance Criteria

- [x] plan.jsonl format implemented with task IDs
- [x] `ralph query` returns current state as JSON
- [x] `ralph query stage` returns computed stage
- [x] `ralph task done/add/accept` mutations work and auto-commit
- [x] `ralph issue done/add` mutations work and auto-commit
- [x] `ralph set-spec` updates state
- [x] `ralph log` parses git history and returns structured task history
- [x] `ralph log --all` reconstructs full task history from git
- [x] `ralph plan` uses new state system instead of markdown
- [x] Stage-based prompts (PROMPT_build.md, PROMPT_verify.md, PROMPT_investigate.md)
- [x] Build loop selects prompt based on current stage
- [x] IMPLEMENTATION_PLAN.md removed from init and prompts
- [x] `ralph build` checks for uncommitted plan.jsonl and offers to commit
- [x] `ralph plan` checks for unfinished tasks and offers cancel/abort options
- [ ] `ralph task reject "reason"` adds tombstone and moves task back to pending
- [ ] `ralph log --all` uses tombstones to distinguish accepted vs rejected tasks
- [ ] `ralph plan` clears tombstones when starting fresh
