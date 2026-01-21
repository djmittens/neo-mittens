# DECOMPOSE Stage

A task was killed because it was too large (exceeded context or timeout limits).
You must break it down into smaller subtasks.

## Step 1: Get the Failed Task

Run `ralph query` to see the task that needs decomposition.
The `next.task` field shows:
- `name`: The task that failed
- `notes`: Original implementation guidance
- `kill_reason`: Why it was killed ("timeout" or "context_limit")
- `kill_log`: Path to the log from the failed iteration

## Step 2: Review the Failed Iteration Log

If `kill_log` is provided, review it to understand what went wrong.

**CRITICAL**: The log file may be HUGE (it killed the previous iteration's context!). 
NEVER read the entire file. Always use head/tail:

```bash
# First check the size
wc -l <kill_log_path>

# Read ONLY the header (first 50 lines) - shows what task started
head -50 <kill_log_path>

# Read ONLY the tail (last 100 lines) - shows where it stopped  
tail -100 <kill_log_path>

# If you need to search for specific content
grep -n -E "error|Error|ERROR|failed|FAILED" <kill_log_path> | head -20
```

From this limited sample, determine:
- What work was started but not completed
- Where the iteration got stuck or ran out of context
- Which files were being modified
- Any partial progress that was made
- **What output flooded the context** (e.g., sanitizer output, verbose test logs)

## Step 3: Research the Breakdown

Use subagents to understand what the task requires and how to split it:

```
Task: "Analyze how to decompose this task: [task name]

Original notes: [task notes]
Kill reason: [timeout/context_limit]

Research the codebase and return a JSON object:
{
  \"original_scope\": \"<what the task was trying to do>\",
  \"progress_made\": \"<what was completed before kill, if any>\",
  \"remaining_work\": [
    {
      \"subtask\": \"<specific piece of work>\",
      \"files\": [{\"path\": \"file.py\", \"lines\": \"100-150\", \"action\": \"what to do\"}],
      \"imports\": [\"from X import Y\"],
      \"effort\": \"small|medium\",
      \"order\": 1
    }
  ],
  \"dependencies_between_subtasks\": \"<which subtasks must complete before others>\",
  \"context_risks\": \"<what caused context explosion - verbose output? large files?>\",
  \"mitigation\": \"<how subtasks should avoid same problem>\"
}"
```

## Step 4: Create Subtasks with Full Context

Break the original task into 2-5 smaller tasks. Each subtask MUST:
- Be completable in ONE iteration (< 100k tokens)
- Have full context so BUILD stage doesn't need to re-research
- Include `parent` to link back to original task

### Subtask Notes Requirements

**MUST INCLUDE ALL OF:**

1. **Source locations**: Exact file paths with line numbers
   - "Source: powerplant/ralph lines 4643-4800 (first half of FallbackDashboard)"

2. **What to do**: Specific bounded action
   - "Extract DashboardState dataclass only (lines 4022-4045)"

3. **How to do it**: Implementation approach
   - "Copy class definition, add imports for dataclass, field, Optional"

4. **Imports/Dependencies**: What's needed
   - "Import from ralph.tui.art: RALPH_ART (created by t-i1oe9h)"

5. **Context from parent**: What was learned
   - "Parent task found: class uses deque for log buffering, needs collections import"

6. **Risk mitigation**: How to avoid re-kill
   - "Avoid running full test suite - just verify import works"

**Subtask Template:**
```json
{
  "name": "Specific bounded subtask",
  "notes": "Source: <file> lines <N-M> (subset of parent). <Specific action>. Imports: <list>. Pattern: <approach>. Context from parent: <what was learned>. Risk mitigation: <avoid context explosion by...>",
  "accept": "<measurable: command + expected result>",
  "parent": "<original-task-id>",
  "deps": ["<any-prerequisite-subtasks>"]
}
```

### Subtask Acceptance Criteria Requirements

Each subtask MUST have measurable acceptance criteria:
- "test -f ralph/tui/fallback.py && wc -l ralph/tui/fallback.py shows > 50 lines"
- "python3 -c 'from ralph.tui.fallback import DashboardState' exits 0"
- "grep -c 'class FallbackDashboard' ralph/tui/fallback.py returns 1"

### Example Decomposition

**Original killed task:**
```
name: "Extract FallbackDashboard to tui/fallback.py"
notes: "Extract FallbackDashboard class from powerplant/ralph to ralph/tui/fallback.py"
kill_reason: "context_limit"
```

**Decomposed into:**

```json
{
  "name": "Create fallback.py with DashboardState dataclass",
  "notes": "Source: powerplant/ralph lines 4022-4045 (DashboardState dataclass only). Create ralph/tui/fallback.py with just the DashboardState dataclass. Imports: dataclass, field from dataclasses; Optional from typing; deque from collections. This is the smallest extractable unit. Risk mitigation: Don't extract FallbackDashboard yet - just the dataclass.",
  "accept": "test -f ralph/tui/fallback.py && python3 -c 'from ralph.tui.fallback import DashboardState' exits 0",
  "parent": "t-original",
  "priority": "high"
}
```

```json
{
  "name": "Add FallbackDashboard class to fallback.py",
  "notes": "Source: powerplant/ralph lines 4643-4948 (FallbackDashboard class). Add to existing ralph/tui/fallback.py. Imports: sys, os, time, select, datetime. Import from ralph.utils: Colors. Import from ralph.tui.art: RALPH_ART, RALPH_WIDTH. Class uses DashboardState (already in file from subtask 1). Context from parent: class has update(), render(), run() methods. Risk mitigation: Copy class definition without modification first, test import before any refactoring.",
  "accept": "python3 -c 'from ralph.tui.fallback import FallbackDashboard' exits 0",
  "parent": "t-original",
  "deps": ["t-subtask1"]
}
```

```json
{
  "name": "Add render_dashboard function to fallback.py",
  "notes": "Source: powerplant/ralph lines 4950-5106 (render_dashboard function). Add to existing ralph/tui/fallback.py after FallbackDashboard class. Function uses DashboardState and FallbackDashboard (both already in file). Add to __all__ exports. Risk mitigation: This is the final piece - run full import test after adding.",
  "accept": "python3 -c 'from ralph.tui.fallback import DashboardState, FallbackDashboard, render_dashboard' exits 0 && grep '__all__' ralph/tui/fallback.py | grep -q render_dashboard",
  "parent": "t-original",
  "deps": ["t-subtask2"]
}
```

## Step 5: Add Subtasks

For each subtask:
```bash
ralph task add '{"name": "...", "notes": "...", "accept": "...", "parent": "<original-task-id>", "deps": [...]}'
```

The `parent` field links subtasks to the original killed task for traceability.

## Step 6: Delete Original Task

After adding all subtasks:
```bash
ralph task delete <original-task-id>
```

## Step 7: Report

```
[RALPH] === DECOMPOSE COMPLETE ===
[RALPH] Original: <original task name>
[RALPH] Kill reason: <timeout|context_limit>
[RALPH] Context risk: <what caused explosion>
[RALPH] Mitigation: <how subtasks avoid it>
[RALPH] Split into: N subtasks
[RALPH] Subtask IDs: t-xxx, t-yyy, t-zzz
```

Then EXIT to let the build loop process the new subtasks.

## Rules

1. **ALWAYS review kill log first** (head/tail only!) to understand what happened
2. **Each subtask < 100k tokens** - completable in ONE iteration
3. **Preserve context**: Copy relevant findings from parent task notes
4. **Be specific**: "Extract lines 100-150 from X to Y" not "Extract part of X"
5. **Include line numbers**: Every subtask needs specific source locations
6. **Measurable acceptance**: Every `accept` must have a verifiable command
7. **Risk mitigation**: Each subtask should note how to avoid re-kill
8. **Maximum decomposition depth**: Tasks can only be decomposed 3 levels deep
9. **DO NOT implement** - just create the task breakdown
