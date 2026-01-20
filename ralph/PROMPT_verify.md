# VERIFY Stage

All tasks are done. Verify the spec is actually complete.

## CRITICAL: The Spec File is the Source of Truth

**Do NOT just check task acceptance criteria.** The spec file may have been updated since tasks were created. You MUST verify against the CURRENT spec file content.

## Step 1: Read the Spec File

Read the ENTIRE spec file: `ralph/specs/<spec>`

Extract ALL requirements, including:
- Acceptance criteria checkboxes (`- [ ]`)
- Requirements stated in prose
- Behavioral expectations in examples
- Edge cases mentioned anywhere

**List every requirement you find.** Do not skip any.

## Step 2: Get Completed Tasks

Run `ralph query` to see completed tasks (status "done").

## Step 3: Verify Each Done Task (Parallelized)

For EACH done task, spawn a subagent to verify:

```
Task: "Verify task '{task.name}' with acceptance criteria: {task.accept}

1. RE-CHECK: Does the implementation meet the acceptance criteria?
   - Search codebase for the implementation
   - Run any tests specified
   - Check edge cases

2. ALIGNMENT CHECK (only if re-check passes): 
   - Does the acceptance criteria fully cover the related spec requirement?
   - Are there aspects of the spec requirement not covered by the criteria?

Return JSON:
{
  \"task_id\": \"{task.id}\",
  \"recheck_passed\": true | false,
  \"recheck_evidence\": \"<what you found>\",
  \"alignment_ok\": true | false,  // only if recheck passed
  \"alignment_gap\": \"<what criteria missed>\"  // only if alignment failed
}"
```

**Run all task verification subagents in parallel** (fork/join pattern).

## Step 4: Verify Spec Coverage (Parallelized)

For EACH requirement extracted from the spec file, spawn a subagent:

```
Task: "Verify this spec requirement is satisfied: <requirement>

1. Search codebase for the implementation
2. Check if it fully satisfies the requirement
3. Identify any gaps

Return JSON:
{
  \"requirement\": \"<the requirement>\",
  \"satisfied\": true | false,
  \"evidence\": \"<what you found>\",
  \"gap\": \"<what's missing>\"  // only if not satisfied
}"
```

**Run all spec verification subagents in parallel** (fork/join pattern).

## Step 5: Collect Results and Apply

After all subagents return:

### For each task:
- **Re-check failed** → `ralph task reject "<task_id>" "<reason>"`
- **Re-check passed, alignment gap** → `ralph task accept` + create new task for gap
- **Both passed** → `ralph task accept`

### For spec gaps:
- Create new task: `ralph task add '{"name": "what's missing", "accept": "how to verify"}'`

### Final decision:

If NO rejections and NO gaps:
```
[RALPH] SPEC_COMPLETE
```

If ANY rejections or gaps:
```
[RALPH] SPEC_INCOMPLETE: <summary>
```

The loop will continue with BUILD stage.

## Progress Reporting

```
[RALPH] === VERIFY: <spec name> ===
[RALPH] Requirements found: <count>
[RALPH] Tasks to verify: <count>
[RALPH] Verifying...
```

## EXIT after applying all verdicts
