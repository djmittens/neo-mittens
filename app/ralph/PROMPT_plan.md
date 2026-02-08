## Target Spec: {{SPEC_FILE}}

Read the spec file: `ralph/specs/{{SPEC_FILE}}`

{{TIX_HISTORY}}

## Instructions

1. **Use subagents** (Task tool) to research different aspects of the codebase in parallel. Your context window is limited.

2. **Gap analysis**: Compare the spec against the current codebase. For each requirement, check if it's already implemented.

3. **Learn from history**: Review the accepted and rejected tasks above (if any). Do NOT re-create tasks that were already accepted. For rejected tasks, study the rejection reasons and create improved tasks that avoid the same mistakes.

4. **Create tasks ONLY for what's missing or broken.** Do NOT implement anything — planning only.

5. Each task must have:
   - `name`: Short description ("Add X to Y", not "Improve Z")
   - `notes`: DETAILED — specific file paths, line numbers, approach (min 50 chars)
   - `accept`: MEASURABLE — command to run + expected result
   - `deps`: Task IDs this depends on (use IDs from earlier tasks in your list)
   - `priority`: One of `"high"`, `"medium"`, or `"low"` — high for foundational/blocking tasks, low for polish/docs

## Output

When done, output your result between markers EXACTLY like this:

```
[RALPH_OUTPUT]
{
  "tasks": [
    {
      "name": "Add timeout parameter to aio/within builtin",
      "notes": "In src/aio/aio_combinators.c: Add valk_builtin_aio_within() after aio_race. Pattern: race(handle, then(sleep(sys, ms), fail(timeout))). Register in valk_lenv_put_builtins() table.",
      "accept": "grep -c 'aio/within' src/builtins.c returns 1",
      "deps": [],
      "priority": "high"
    },
    {
      "name": "Add tests for aio/within",
      "notes": "Create test/test_aio_within.valk: Test timeout before completion, completion before timeout, handle failure. Use aio/sleep for timing.",
      "accept": "make test passes including test_aio_within",
      "deps": ["t-PREV_ID"],
      "priority": "medium"
    }
  ]
}
[/RALPH_OUTPUT]
```

Rules:
- Each task should be completable in ONE iteration
- Add prerequisite tasks first so you have their IDs for `deps`
- Tasks without detailed notes will be REJECTED
- Vague acceptance criteria ("works correctly") will be REJECTED
- Do NOT create tasks for work that was already accepted (see history above)
- If a previous task was rejected, address the rejection reason in your new task's notes

**You MUST output the [RALPH_OUTPUT] block as your final action before exiting.**
