# VERIFY Stage

Verify that done tasks meet their acceptance criteria.

## Step 1: Get Current Batch

Run `ralph query next` to get the current batch of tasks to verify:
- `tasks`: list of tasks in THIS BATCH (may be a subset of all done tasks)
- `count`: number of tasks in this batch
- `total`: total done tasks across all batches
- `batch_progress`: shows which batch this is

**IMPORTANT**: Only verify the tasks returned in `tasks`. Ralph processes tasks in batches to avoid context overflow.

## Step 2: Verify Each Task in Batch

For EACH task in the batch, spawn a subagent to verify:

```
Task: "Verify task '{task.name}' meets its acceptance criteria: {task.accept}

1. Search codebase for the implementation
2. Check if acceptance criteria is satisfied
3. Run any tests mentioned in criteria

Return JSON:
{
  \"task_id\": \"{task.id}\",
  \"passed\": true | false,
  \"evidence\": \"<what you found>\",
  \"reason\": \"<why it failed>\"  // only if passed=false
}"
```

**Run all verifications in parallel.**

## Step 3: Apply Results

### For each task:

**If passed** → `ralph task accept <task-id>`

**If failed** → Choose one:

1. **Implementation bug** (can be fixed):
   `ralph task reject <task-id> "<reason>"`

2. **Architectural blocker** (cannot be done):
   `ralph issue add "Task <task-id> blocked: <why>"`
   `ralph task delete <task-id>`
   
Signs of architectural blocker:
- "Cannot do X mid-execution"
- Same rejection reason recurring
- Requires changes outside this spec

## Step 4: Verify Spec Acceptance Criteria

Read the spec's **Acceptance Criteria section only** (not entire spec):
`ralph/specs/<spec-name>` - scroll to "## Acceptance Criteria"

### 4a: Verify Checked Criteria Still Pass

For each **checked** criterion (`- [x]`), spawn a subagent to verify it still holds:

```
Task: "Verify spec acceptance criterion: {criterion_text}

1. Search codebase for relevant implementation
2. Run any tests or commands that verify this criterion
3. Check that the implementation still satisfies this criterion

Return JSON:
{
  \"criterion\": \"{criterion_text}\",
  \"passed\": true | false,
  \"evidence\": \"<what you found>\",
  \"reason\": \"<why it failed>\"  // only if passed=false
}"
```

**Run all verifications in parallel.**

If any checked criterion no longer passes:
- `ralph issue add "Spec criterion regressed: <criterion>. Reason: <why>"`
- Uncheck it in the spec file

### 4b: Create Tasks for Unchecked Criteria

For any **unchecked** criteria (`- [ ]`) not covered by existing tasks, research what's needed and create a well-defined task:
```
ralph task add '{"name": "<specific action>", "notes": "<DETAILED: file paths + approach>", "accept": "<measurable verification>"}\'
```

**IMPORTANT**: 
- `notes` MUST include SPECIFIC file paths and implementation approach (minimum 50 chars)
- `notes` should answer: Which files? What functions/lines? What pattern to use?
- `accept` MUST be measurable: command to run, expected exit code, or specific output to check
- Vague notes like "implement X" or acceptance like "works correctly" will be REJECTED

## Step 5: Final Decision

If all tasks accepted and no new tasks created:
```
[RALPH] SPEC_COMPLETE
```

Otherwise:
```
[RALPH] SPEC_INCOMPLETE: <summary>
```

## EXIT after completing
