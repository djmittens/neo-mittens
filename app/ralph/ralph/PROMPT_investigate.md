# INVESTIGATE Stage

Issues were discovered during verification or build. Research them and produce actionable tasks.

## Issues to Investigate

```json
{{ISSUES_JSON}}
```

Total: {{ISSUE_COUNT}} issues

## Spec: {{SPEC_FILE}}

{{SPEC_CONTENT}}

## Instructions

1. **Launch one subagent per issue** (Task tool) -- investigate all in parallel.

2. Each subagent should:
   - Read relevant code to understand the problem
   - Determine root cause
   - Decide: needs a fix task, trivial fix, or out of scope

3. For issues needing fix tasks, include detailed task definitions in output.

4. **Do NOT make code changes** -- only research and produce tasks.

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
