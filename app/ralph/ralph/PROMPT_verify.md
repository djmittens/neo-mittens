# VERIFY Stage

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
