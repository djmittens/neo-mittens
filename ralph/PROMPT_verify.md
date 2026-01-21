# VERIFY Stage

Done tasks need verification against their acceptance criteria.

## Step 1: Get Done Tasks

Run `ralph query tasks --done` to get the list of done tasks that need verification.

This returns a JSON array of done tasks, each with:
- `id`: task ID (e.g., "t-abc123")
- `name`: task name
- `accept`: acceptance criteria to verify
- `notes`: implementation notes (if any)

## Step 2: Verify Each Done Task

For EACH done task, spawn a subagent to verify:

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

## Step 4: Check for Gaps

Read the spec's **Acceptance Criteria section only** (not entire spec):
`ralph/specs/<spec-name>` - scroll to "## Acceptance Criteria"

For any unchecked criteria (`- [ ]`) not covered by existing tasks, research what's needed and create a well-defined task:
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
