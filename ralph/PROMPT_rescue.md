# RESCUE Stage

A batch of items failed during VERIFY or INVESTIGATE stage after maximum retries.
This is a step-level failure (not a task-level failure like DECOMPOSE handles).

## Step 1: Understand the Failure

Run `ralph query` to see the rescue context in `next`:
- `failed_stage`: Which stage failed (VERIFY or INVESTIGATE)
- `failed_batch`: List of item IDs that were in the failed batch
- `reason`: Why it failed ("timeout" or "context_limit")
- `log`: Path to the log from the failed batch

## Step 2: Review the Failed Batch Log

If `log` is provided, review it to understand what went wrong.

**CRITICAL**: The log file may be HUGE. NEVER read the entire file. Always use head/tail:

```bash
# First check the size
wc -l <log_path>

# Read ONLY the header (first 50 lines)
head -50 <log_path>

# Read ONLY the tail (last 100 lines) - shows where it stopped  
tail -100 <log_path>

# If you need to search for specific content
grep -n -E "error|Error|ERROR|failed|FAILED" <log_path> | head -20
```

## Step 3: Determine Recovery Action

Based on the failure mode, choose the appropriate recovery:

### A. Batch Too Large (context_limit)
The batch had too many items for the context window.

**Action**: The batch size will be automatically reduced on retry. Simply exit and let Ralph retry with a smaller batch. If specific items are problematic:
```
ralph issue add "Item <id> causes context explosion: <why>"
```

### B. Single Item Causing Problems
One item in the batch is problematic (e.g., causes infinite loops, huge output).

**Action**: Identify and handle the problematic item:
- For VERIFY batches: If a task's verification is problematic, reject it:
  ```
  ralph task reject <task-id> "Verification failed: <reason>"
  ```
- For INVESTIGATE batches: If an issue can't be investigated, clear it:
  ```
  ralph issue done <issue-id>
  ralph issue add "Deferred: <issue description> - <why it's problematic>"
  ```

### C. Timeout (work taking too long)
The batch took too long to complete.

**Action**: Determine if the work is legitimate or stuck:
- If legitimate (e.g., running slow tests): The timeout will be extended on retry
- If stuck in a loop: Identify the problematic item and handle per case B

### D. External Failure
Something outside Ralph failed (network, tools, etc.).

**Action**: Simply exit and let Ralph retry. If it's a persistent external issue:
```
ralph issue add "External blocker: <description>"
```

## Step 4: Report and Exit

After taking recovery action:

```
[RALPH] === RESCUE COMPLETE ===
[RALPH] Failed stage: <VERIFY|INVESTIGATE>
[RALPH] Failed batch: <list of IDs>
[RALPH] Reason: <timeout|context_limit>
[RALPH] Action taken: <what you did>
```

Then EXIT to let Ralph retry the stage.

## Key Differences from DECOMPOSE

| DECOMPOSE | RESCUE |
|-----------|--------|
| Single task too large | Batch of items failed |
| Break down into subtasks | Identify and handle problematic items |
| Task-centric | Step-centric |
| Always creates new tasks | May reject, defer, or just retry |

## Rules

- DO NOT try to complete the work that failed - just handle the failure
- If you can't identify a specific problem, just exit and let Ralph retry
- The batch size will automatically shrink if context was the issue
- If the same batch fails repeatedly, escalate by creating an issue
