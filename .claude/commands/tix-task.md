---
description: Execute ONE task from the tix task list
---

Execute exactly ONE task from the pending task list, then stop.

## Prerequisites

Check that `.tix/` exists. If not, tell user to run `tix init` first.

## Steps

1. Run `tix query tasks` to get pending tasks as JSON

2. Pick the SINGLE highest-priority incomplete task (first one returned)

3. Read the task's spec file if it has one

4. Before implementing, search the codebase to confirm it's not already done

5. Implement the task fully:
   - No placeholders or stubs
   - Follow existing code patterns

6. Run tests/build to validate

7. Mark the task done: `tix task done <id>`

8. Report completion:
   ```
   [TIX] === DONE: <task name> ===
   [TIX] RESULT: <summary>
   ```

## CRITICAL

- Complete ONE task only
- Do not start another task
- The user will run this command again for the next task
