"""Default prompt templates for Ralph init command.

These prompts are written to ralph/PROMPT_*.md files during initialization.
Contains PLAN and BUILD stage prompts. See init_prompts_extra.py for others.

All prompts use [RALPH_OUTPUT] structured output format. The agent never
calls task/issue CLI commands directly — the harness reconciles via tix.
"""

from ralph.commands.init_prompts_extra import (
    DEFAULT_PROMPT_VERIFY,
    DEFAULT_PROMPT_INVESTIGATE,
    DEFAULT_PROMPT_DECOMPOSE,
    EXAMPLE_SPEC,
)

DEFAULT_PROMPT_PLAN = """## Target Spec: {{SPEC_FILE}}

Read the spec file: `ralph/specs/{{SPEC_FILE}}`

## Instructions

1. **Use subagents** (Task tool) to research different aspects of the codebase in parallel. Your context window is limited.

2. **Gap analysis**: Compare the spec against the current codebase. For each requirement, check if it's already implemented.

3. **Create tasks ONLY for what's missing or broken.** Do NOT implement anything — planning only.

4. Each task must have:
   - `name`: Short description ("Add X to Y", not "Improve Z")
   - `notes`: DETAILED — specific file paths, line numbers, approach (min 50 chars)
   - `accept`: MEASURABLE — command to run + expected result
   - `deps`: Task IDs this depends on (use IDs from earlier tasks in your list)

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
      "deps": []
    },
    {
      "name": "Add tests for aio/within",
      "notes": "Create test/test_aio_within.valk: Test timeout before completion, completion before timeout, handle failure. Use aio/sleep for timing.",
      "accept": "make test passes including test_aio_within",
      "deps": ["t-PREV_ID"]
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

**You MUST output the [RALPH_OUTPUT] block as your final action before exiting.**
"""

DEFAULT_PROMPT_BUILD = """# BUILD Stage

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
"""

PROMPT_TEMPLATES = {
    "PROMPT_plan.md": DEFAULT_PROMPT_PLAN,
    "PROMPT_build.md": DEFAULT_PROMPT_BUILD,
    "PROMPT_verify.md": DEFAULT_PROMPT_VERIFY,
    "PROMPT_investigate.md": DEFAULT_PROMPT_INVESTIGATE,
    "PROMPT_decompose.md": DEFAULT_PROMPT_DECOMPOSE,
}
