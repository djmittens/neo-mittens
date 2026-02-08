"""Additional default prompt templates for Ralph stages.

Contains VERIFY, INVESTIGATE, and DECOMPOSE stage prompts, plus the
example spec template. Loaded at runtime from the package — no files
are written to the target repository.

All prompts use [RALPH_OUTPUT] structured output format. The agent never
calls task/issue CLI commands directly — the harness reconciles via tix.
"""

DEFAULT_PROMPT_VERIFY = """# VERIFY Stage

Verify that done tasks meet their acceptance criteria.

## Done Tasks to Verify

```json
{{DONE_TASKS_JSON}}
```

Total: {{DONE_COUNT}} tasks

## Spec: {{SPEC_FILE}}

{{SPEC_CONTENT}}

## Instructions

1. **For each done task**, spawn a subagent (Task tool) to verify its acceptance criteria. Run all verifications in parallel.

2. Each subagent should:
   - Search the codebase for the implementation
   - Run any tests/commands in the acceptance criteria
   - Return whether the task passes or fails, with evidence

3. **Check spec acceptance criteria** in `ralph/specs/{{SPEC_FILE}}`:
   - For checked criteria (`- [x]`): verify they still hold
   - For unchecked criteria (`- [ ]`): identify what's missing

4. For unchecked criteria not covered by existing tasks, include them in `new_tasks`.

5. **Report cross-cutting issues** in `issues`: problems that affect multiple tasks or indicate a missing prerequisite. Examples:
   - A shared dependency is broken causing several tasks to fail the same way
   - A prerequisite setup step is missing from the environment
   - A spec assumption is incorrect and needs clarification

## Rejection Quality

When a task fails, the `reason` MUST be diagnostic — not just what failed, but why:
- Include specific **file paths and line numbers** where the problem is
- Include the **actual error output** (first meaningful lines)
- State the **root cause** if apparent (e.g., "function signature changed but callers not updated")

Bad: `"test_pool fails"`
Good: `"src/pool.c:67 — error path skips free(conn). test-asan output: 'LeakSanitizer: detected memory leak of 64 bytes'"`

## Output

When done, output your result between markers EXACTLY like this:

```
[RALPH_OUTPUT]
{
  "results": [
    {"task_id": "t-xxx", "passed": true},
    {"task_id": "t-yyy", "passed": false, "reason": "src/pool.c:67 — error path skips free(conn). test-asan fails with: LeakSanitizer detected 64 byte leak"}
  ],
  "issues": [
    {"desc": "libfoo.so missing from test env — causes 3 tasks to fail with 'shared library not found'. Need a setup task to install it.", "priority": "high"}
  ],
  "spec_complete": false,
  "new_tasks": [
    {"name": "Fix failing criterion", "notes": "Detailed: file paths, approach, min 50 chars", "accept": "measurable command + expected result"}
  ]
}
[/RALPH_OUTPUT]
```

- `results`: one entry per done task — `passed: true` to accept, `passed: false` to reject
- `reason`: required when `passed: false` — diagnostic with file paths, error output, and root cause
- `issues`: cross-cutting problems not tied to a single task (missing prerequisites, broken shared deps, spec issues)
  - `desc` MUST be specific — include file paths, error messages, and what needs to happen
  - `priority`: "high" for blocking issues, "medium" for non-blocking
- `spec_complete`: true only if ALL spec criteria are satisfied and no new work needed
- `new_tasks`: tasks for uncovered spec criteria (notes must have file paths, accept must be measurable)

**You MUST output the [RALPH_OUTPUT] block as your final action before exiting.**
"""

DEFAULT_PROMPT_INVESTIGATE = """# INVESTIGATE Stage

Issues were discovered during verification or build. Research them and produce actionable tasks.

## Issues to Investigate

```json
{{ISSUES_JSON}}
```

Total: {{ISSUE_COUNT}} issues

## Spec: {{SPEC_FILE}}

{{SPEC_CONTENT}}

## Instructions

1. **Launch one subagent per issue** (Task tool) — investigate all in parallel.

2. Each subagent should:
   - Read relevant code to understand the problem
   - Determine root cause
   - Decide: needs a fix task, trivial fix, or out of scope

3. For issues needing fix tasks, include detailed task definitions in output.

4. **Do NOT make code changes** — only research and produce tasks.

## Handling Auto-Generated Issues

- "REPEATED REJECTION" issues: same task failed 3+ times. Find the root cause, create a HIGH priority blocking task.
- "COMMON FAILURE PATTERN" issues: multiple tasks fail the same way. Create a single HIGH priority prerequisite task.

## Output

When done, output your result between markers EXACTLY like this:

```
[RALPH_OUTPUT]
{
  "tasks": [
    {
      "name": "Fix memory leak in connection pool",
      "notes": "In src/pool.c lines 45-80: conn_acquire() allocates but error path at line 67 skips free. Add free(conn) before return NULL.",
      "accept": "make test-asan passes with no leaks in pool_test",
      "priority": "high",
      "created_from": "i-xxxx"
    }
  ],
  "out_of_scope": ["i-yyyy"],
  "summary": "Found 2 actionable issues, 1 out of scope"
}
[/RALPH_OUTPUT]
```

- `tasks`: one entry per issue that needs a fix task
  - `notes` MUST include specific file paths and approach (min 50 chars)
  - `accept` MUST be measurable (command + expected result)
  - `priority`: inherit from the originating issue
  - `created_from`: the issue ID that spawned this task
- `out_of_scope`: issue IDs that don't need action

**You MUST output the [RALPH_OUTPUT] block as your final action before exiting.**
"""

DEFAULT_PROMPT_DECOMPOSE = """# DECOMPOSE Stage

A task was killed (exceeded context or timeout). Break it into smaller subtasks.

## Failed Task

```json
{{TASK_JSON}}
```

- **Name**: {{TASK_NAME}}
- **Kill reason**: {{KILL_REASON}}
- **Kill log**: {{KILL_LOG_PATH}}
- **Decompose depth**: {{DECOMPOSE_DEPTH}} / {{MAX_DEPTH}}

## Spec Content

{{SPEC_CONTENT}}

## Instructions

1. **Review the kill log** (if available). The log may be HUGE — use head/tail only:
   ```bash
   head -50 <kill_log_path>    # What started
   tail -100 <kill_log_path>   # Where it stopped
   ```

2. **Use a subagent** to analyze what the task requires and how to break it down.

3. **Create 2-5 subtasks** that:
   - Can each be completed in ONE iteration (< 100k tokens)
   - Have clear, specific scope
   - Together accomplish the original task
   - Use `deps` for ordering if needed

## Output

When done, output your result between markers EXACTLY like this:

```
[RALPH_OUTPUT]
{
  "subtasks": [
    {
      "name": "Extract parser into separate module",
      "notes": "Move parse_expr() and parse_stmt() from src/main.c lines 200-400 to src/parser.c. Update includes.",
      "accept": "make build succeeds and make test passes",
      "deps": []
    },
    {
      "name": "Add error recovery to parser",
      "notes": "In src/parser.c parse_expr(): add synchronization points after syntax errors. Pattern: skip tokens until ';' or '}'.",
      "accept": "echo 'bad syntax;' | ./build/lang exits 1 without crash",
      "deps": []
    }
  ]
}
[/RALPH_OUTPUT]
```

- Each subtask `notes` MUST include specific file paths and approach (min 50 chars)
- Each subtask `accept` MUST be measurable
- Do NOT try to implement anything — just create the breakdown

**You MUST output the [RALPH_OUTPUT] block as your final action before exiting.**
"""

EXAMPLE_SPEC = """# Example Specification

Delete this file and create your own specs.

## Overview

Describe what you want to build.

## Requirements

- Requirement 1
- Requirement 2

## Acceptance Criteria

- [ ] Criterion 1
- [ ] Criterion 2
"""
