# VERIFY Stage

Verify that done tasks meet their acceptance criteria.

## Done Tasks ({{DONE_COUNT}} total)

```json
{{DONE_TASKS_JSON}}
```

## Spec File

`ralph/specs/{{SPEC_FILE}}`

## Instructions

### 1. Verify Each Done Task

For EACH task above, spawn a subagent:

```
Task: "Verify task '{task.name}' meets: {task.accept}

1. Find the implementation
2. Check acceptance criteria
3. Run any tests in criteria

Return JSON:
{\"task_id\": \"...\", \"passed\": true|false, \"evidence\": \"...\", \"reason\": \"...\"}"
```

**Run all verifications in parallel.**

### 2. Apply Results

**Passed** -> `ralph2 task accept <task-id>`

**Failed** -> Choose one:
- Implementation bug: `ralph2 task reject <task-id> "<reason>"`
- Architectural blocker: `ralph2 issue add "..."` then `ralph2 task delete <task-id>`

### 3. Check Spec Acceptance Criteria

Read ONLY the "## Acceptance Criteria" section of the spec below.

For each **checked** criterion (`- [x]`), verify it still holds.
For each **unchecked** criterion (`- [ ]`) not covered by tasks, create a task.

### 4. Report

All tasks accepted, no new tasks:
```
[RALPH] SPEC_COMPLETE
```

Otherwise:
```
[RALPH] SPEC_INCOMPLETE: <summary>
```

---

## Spec Content (Acceptance Criteria Reference)

<spec>
{{SPEC_CONTENT}}
</spec>
