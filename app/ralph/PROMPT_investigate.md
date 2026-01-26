# INVESTIGATE Stage

Research and resolve all pending issues.

## Issues ({{ISSUE_COUNT}} total)

```json
{{ISSUES_JSON}}
```

## Spec File

`ralph/specs/{{SPEC_FILE}}`

## Instructions

### 1. Parallel Investigation

Launch a subagent for EACH issue above:

```
Task: "Investigate: {issue.desc}
Issue ID: {issue.id}
Priority: {issue.priority}

Return JSON:
{
  \"issue_id\": \"...\",
  \"root_cause\": \"file:line reference\",
  \"resolution\": \"task\" | \"trivial\" | \"out_of_scope\",
  \"task\": {
    \"name\": \"Fix: ...\",
    \"notes\": \"Root cause: file:line. Fix: approach. Imports: list. Risk: effects.\",
    \"accept\": \"measurable command + result\",
    \"priority\": \"high|medium|low\"
  }
}"
```

**Run ALL investigations in parallel.**

### 2. Create Tasks

For each subagent result with `resolution: "task"`:

```
ralph2 task add '{"name": "...", "notes": "Root cause: file:line. Fix: approach.", "accept": "...", "created_from": "<issue-id>", "priority": "..."}'
```

### 3. Clear Issues

```
ralph2 issue done-all
```

### 4. Report

```
[RALPH] === INVESTIGATE COMPLETE ===
[RALPH] Processed: N issues
[RALPH] Tasks created: X
```

## Pattern Issues

**REPEATED REJECTION**: Same task failed 3+ times
- Create HIGH PRIORITY task addressing root cause
- Notes must include: which task fails, pattern, how to unblock

**COMMON FAILURE PATTERN**: Multiple tasks fail same way
- Create single HIGH PRIORITY task fixing root cause

---

## Spec Content (Reference)

<spec>
{{SPEC_CONTENT}}
</spec>
