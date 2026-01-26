# DECOMPOSE Stage

A task was killed due to context/timeout limits. Break it into smaller subtasks.

## Killed Task

```json
{{TASK_JSON}}
```

**Task**: {{TASK_NAME}}
**Kill Reason**: {{KILL_REASON}}
**Kill Log**: `{{KILL_LOG_PATH}}`
**Decompose Depth**: {{DECOMPOSE_DEPTH}} / {{MAX_DEPTH}}

## Original Notes

{{TASK_NOTES}}

## Kill Log Preview

<log>
{{KILL_LOG_PREVIEW}}
</log>

## Instructions

### 1. Analyze the Log

The log preview shows head + tail. Determine:
- What was completed before kill
- What caused context explosion
- Partial progress to preserve

### 2. Research Breakdown

Spawn a subagent:

```
Task: "Analyze how to decompose: {{TASK_NAME}}
Notes: {{TASK_NOTES}}

Return JSON:
{
  \"remaining_work\": [
    {\"subtask\": \"specific piece\", \"files\": [{\"path\": \"file.py\", \"lines\": \"100-150\"}], \"effort\": \"small|medium\"}
  ],
  \"context_risks\": \"what caused explosion\",
  \"mitigation\": \"how subtasks avoid it\"
}"
```

### 3. Create Subtasks

Each subtask MUST include:
- **Source locations**: file paths with line numbers
- **Bounded action**: completable in ONE iteration
- **Risk mitigation**: how to avoid re-kill
- **Context from parent**: what was learned

```
ralph2 task add '{"name": "...", "notes": "Source: file lines N-M. Action. Risk mitigation: ...", "accept": "...", "parent": "{{TASK_ID}}"}'
```

### 4. Delete Original

```
ralph2 task delete {{TASK_ID}}
```

### 5. Report

```
[RALPH] === DECOMPOSE COMPLETE ===
[RALPH] Original: {{TASK_NAME}}
[RALPH] Kill reason: {{KILL_REASON}}
[RALPH] Split into: N subtasks
```

## Rules

1. Each subtask must be completable in ONE iteration (<100k tokens)
2. Include file:line references for every subtask
3. Include risk mitigation for each subtask
4. Maximum depth: {{MAX_DEPTH}} levels (current: {{DECOMPOSE_DEPTH}})
5. DO NOT implement - just create the breakdown

---

## Spec Content (Reference)

<spec>
{{SPEC_CONTENT}}
</spec>
