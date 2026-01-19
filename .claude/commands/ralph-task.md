---
description: Execute ONE task from the Ralph implementation plan
---

Execute exactly ONE task from the implementation plan, then stop.

## Prerequisites

Check that `ralph/IMPLEMENTATION_PLAN.md` exists. If not, tell user to run `/ralph-plan` first.

## Steps

1. Read `ralph/IMPLEMENTATION_PLAN.md`

2. Pick the SINGLE most important incomplete task (first incomplete task in the file)

3. Identify which `## Spec:` section this task belongs to

4. Read ONLY that specific spec file from `ralph/specs/` - do NOT read all specs

5. Before implementing, search the codebase to confirm it's not already done

6. Implement the task fully:
   - No placeholders or stubs
   - No comments unless explicitly required
   - Follow existing code patterns

7. Run tests/build to validate ONLY the functionality related to this spec - do NOT validate all specs

8. Update `ralph/IMPLEMENTATION_PLAN.md`:
   - Mark task as complete: `- [x] Task`
   - Add any discovered issues
   - Add any new tasks found

7. Commit with descriptive message

8. Report completion:
   ```
   [RALPH] === DONE: <task name> ===
   [RALPH] RESULT: <summary>
   ```

## CRITICAL

- Complete ONE task only
- Do not start another task
- The user will run this command again for the next task

## If Stuck

If stuck for more than 5 minutes on the same issue:
1. Document what you tried in `ralph/IMPLEMENTATION_PLAN.md` under "## Discovered Issues"
2. Move on and report the blocker
