# BUILD Stage

Implement the task below.

## Current Task

```json
{{TASK_JSON}}
```

**Task**: {{TASK_NAME}}
**Spec**: `ralph/specs/{{SPEC_FILE}}`
**Is Retry**: {{IS_RETRY}}

{{#if IS_RETRY}}
## Retry Context

This task was previously rejected:
> {{TASK_REJECT}}

**Do NOT re-explore the codebase.** The code is already there. Fix the specific gap identified above.
{{/if}}

## Implementation Notes

{{TASK_NOTES}}

## Acceptance Criteria

{{TASK_ACCEPT}}

## Instructions

1. **Implement the task** - complete implementations only, no stubs
2. **Check acceptance criteria** before marking done
3. **Use subagents for research** (>3 files) - your context is limited

### Subagent Usage

For codebase research, spawn subagents:
```
Task: "Find how X is implemented. Report: files, current behavior, changes needed for Y"
```

### Completing the Task

When implementation passes acceptance criteria:
```
ralph2 task done
```

## Issue Discovery

Record problems you notice (even if unrelated):
```
ralph2 issue add "description"
```

**Always report**: test warnings, compiler warnings, TODOs, potential bugs, missing coverage.

## Spec Ambiguities

**Do NOT interpret ambiguous specs.** Instead:
1. Log: `ralph2 issue add "Spec ambiguity: X vs Y. Options: (1)... (2)..."`
2. Skip or stub the ambiguous part

---

## Spec Content (Reference)

<spec>
{{SPEC_CONTENT}}
</spec>
