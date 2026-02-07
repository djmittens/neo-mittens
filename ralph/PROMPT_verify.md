# VERIFY Stage

Verify that done tasks meet their acceptance criteria.

## Done Tasks to Verify

```json
{{DONE_TASKS_JSON}}
```

Total: {{DONE_COUNT}} tasks

## Spec: {{SPEC_FILE}}

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

## Output

When done, output your result between markers EXACTLY like this:

```
[RALPH_OUTPUT]
{
  "results": [
    {"task_id": "t-xxx", "passed": true},
    {"task_id": "t-yyy", "passed": false, "reason": "test X fails with error Y"}
  ],
  "spec_complete": false,
  "new_tasks": [
    {"name": "Fix failing criterion", "notes": "Detailed: file paths, approach, min 50 chars", "accept": "measurable command + expected result"}
  ]
}
[/RALPH_OUTPUT]
```

- `results`: one entry per done task — `passed: true` to accept, `passed: false` to reject
- `reason`: required when `passed: false` — specific reason for rejection
- `spec_complete`: true only if ALL spec criteria are satisfied and no new work needed
- `new_tasks`: tasks for uncovered spec criteria (notes must have file paths, accept must be measurable)

**You MUST output the [RALPH_OUTPUT] block as your final action before exiting.**
