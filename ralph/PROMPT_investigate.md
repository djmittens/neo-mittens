# INVESTIGATE Stage

Issues were discovered during build. Research and resolve them in parallel.

## Step 1: Get Current Batch

Run `ralph query next` to get the current batch of issues to investigate:
- `items`: list of issues in THIS BATCH (may be a subset of all issues)
- `count`: number of issues in this batch
- `total`: total issues across all batches
- `batch_progress`: shows which batch this is

**IMPORTANT**: Only investigate the issues returned in `items`. Ralph processes issues in batches to avoid context overflow.

## Step 2: Parallel Investigation

Use the Task tool to investigate ALL issues in this batch in parallel. Launch one subagent per issue:

```
For each issue, launch a Task with prompt:
"Investigate this issue: <issue description>
Issue priority: <issue priority or 'medium' if not set>

1. Read relevant code to understand the problem
2. Determine root cause
3. Decide resolution:
   - If fix is non-trivial: describe the fix task needed
   - If fix is trivial: describe the simple fix
   - If out of scope: explain why

Return a JSON object:
{
  \"issue_id\": \"<id>\",
  \"root_cause\": \"<what you found>\",
  \"resolution\": \"task\" | \"trivial\" | \"out_of_scope\",
  \"task\": {  // only if resolution is \"task\"
    \"name\": \"<fix description>\",
    \"notes\": \"<DETAILED: specific file paths, functions, and implementation approach - min 50 chars>\",
    \"accept\": \"<MEASURABLE: command + expected result, e.g. 'make test passes' or 'grep X file returns 1'>\",
    \"priority\": \"<inherit from issue priority above>\"
  },
  \"trivial_fix\": \"<description>\"  // only if resolution is \"trivial\"
}
"
```

## Step 3: Collect Results and Apply

After all subagents complete:

1. Add all tasks in batch (include `created_from` to link back to issue, and `priority` from originating issue):
```
ralph task add '{"name": "...", "notes": "...", "accept": "<measurable: command + expected result>", "created_from": "i-xxxx", "priority": "high|medium|low"}'
ralph task add '{"name": "...", "notes": "...", "accept": "<measurable: command + expected result>", "created_from": "i-yyyy", "priority": "high|medium|low"}'
...
```

2. Clear the issues from this batch:
```
ralph issue done-ids <id1> <id2> <id3> ...
```

**IMPORTANT**: Only clear the issues that were in THIS batch (from Step 1), not all issues.

## Step 4: Report Summary

```
[RALPH] === INVESTIGATE COMPLETE ===
[RALPH] Processed: N issues
[RALPH] Tasks created: X
[RALPH] Trivial fixes: Y
[RALPH] Out of scope: Z
```

## Handling Auto-Generated Pattern Issues

Issues starting with "REPEATED REJECTION" or "COMMON FAILURE PATTERN" are auto-generated from rejection analysis.
These require special handling:

**For REPEATED REJECTION issues:**
1. The same task has failed 3+ times with similar errors
2. Read the spec and task to understand what's expected
3. Compare with rejection reasons to find the gap
4. Usually indicates: missing prerequisite, wrong approach, or spec ambiguity
5. Create a HIGH PRIORITY blocking task that addresses the root cause
6. Consider if the failing task's `deps` should include the new task

**For COMMON FAILURE PATTERN issues:**
1. Multiple different tasks fail with the same error type
2. This strongly indicates a missing prerequisite that all tasks need
3. Read the spec section about the failing functionality
4. The error message tells you what's missing (e.g., "argument count mismatch" = API changed)
5. Create a single HIGH PRIORITY task to fix the root cause
6. Mark existing failing tasks as depending on this new task using `ralph task add '{"deps": [...]}'`

**Example:**
If multiple tasks fail with "grep returns 0, expected 1" and they all involve `aio/then`, likely:
- The API wasn't changed to return handles yet
- A prerequisite C implementation task is missing
- Create: `ralph task add '{"name": "Refactor X to return handle", "priority": "high", "notes": "..."}'`

## IMPORTANT

- Launch ALL investigations for THIS BATCH in parallel using multiple Task tool calls in a single message
- Wait for all results before applying any changes
- Do NOT make code changes during investigation - only create tasks
- Only clear issues from THIS batch using `ralph issue done-ids`
- EXIT after this batch is processed (Ralph will run another iteration for remaining batches)
