# BUILD Stage

Implement the assigned task.

## Your Task

```json
{{TASK_JSON}}
```

- **Name**: {{TASK_NAME}}
- **Notes**: {{TASK_NOTES}}
- **Acceptance criteria**: {{TASK_ACCEPT}}
- **Rejected reason** (if retry): {{TASK_REJECT}}

## Instructions

1. If this is a **retry** (reject field is set): the code is already there. Read the rejection reason, fix the specific gap. Do NOT re-explore the whole codebase.

2. **Use subagents for research** (Task tool). Your context window is limited. Never read more than 2-3 files yourself. Spawn subagents for any exploration.

3. **Implement** the task completely. No stubs, no placeholder code.

4. **Verify** the acceptance criteria before finishing. Run any tests specified.

5. **Report any issues** you discover (even if unrelated to this task) in the output below.

## Spec Ambiguities

Do NOT make design decisions yourself. If the spec is ambiguous or conflicts with technical constraints, report it as a blocked verdict with the ambiguity as the reason.

## Output

When done, output your result between markers EXACTLY like this:

```
[RALPH_OUTPUT]
{"verdict": "done", "summary": "what was implemented", "issues": []}
[/RALPH_OUTPUT]
```

If you cannot complete the task:

```
[RALPH_OUTPUT]
{"verdict": "blocked", "reason": "why it cannot be done", "issues": []}
[/RALPH_OUTPUT]
```

The `issues` array is for problems you discovered during implementation (optional):
```json
{"issues": [{"desc": "Memory leak in foo.c:123"}, {"desc": "Test flaky: bar_test"}]}
```

**You MUST output the [RALPH_OUTPUT] block as your final action before exiting.**
