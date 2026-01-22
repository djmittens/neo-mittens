"""Additional prompt templates for Ralph init command.

These prompts are written to ralph/PROMPT_*.md files during initialization.
Contains VERIFY, INVESTIGATE, and DECOMPOSE stage prompts.
"""

DEFAULT_PROMPT_VERIFY = """# VERIFY Stage

All tasks are done. Verify they meet their acceptance criteria.

## Step 1: Get State

Run `ralph query` to get:
- `spec`: the current spec name (e.g., "construct-mode.md")
- `tasks.done`: list of done tasks with their acceptance criteria

## Step 2: Verify Each Done Task

For EACH done task, spawn a subagent to verify:

```
Task: "Verify task '{task.name}' meets its acceptance criteria: {task.accept}

1. Search codebase for the implementation
2. Check if acceptance criteria is satisfied
3. Run any tests mentioned in criteria

Return JSON:
{
  \\"task_id\\": \\"{task.id}\\",
  \\"passed\\": true | false,
  \\"evidence\\": \\"<what you found>\\",
  \\"reason\\": \\"<why it failed>\\"  // only if passed=false
}"
```

**Run all verifications in parallel.**

## Step 3: Apply Results

### For each task:

**If passed** -> `ralph task accept <task-id>`

**If failed** -> Choose one:

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

Read the spec\\'s **Acceptance Criteria section only** (not entire spec):
`ralph/specs/<spec-name>` - scroll to "## Acceptance Criteria"

### 4a: Verify checked criteria still pass

For each **checked** criterion (`- [x]`), spawn a subagent to verify it still holds:

```
Task: "Verify spec criterion still passes: \\'<criterion text>\\'

1. Search codebase for the implementation
2. Run any tests or commands that validate this criterion
3. Check that the criterion is still satisfied

Return JSON:
{
  \\"criterion\\": \\"<criterion text>\\",
  \\"passed\\": true | false,
  \\"evidence\\": \\"<what you found>\\",
  \\"reason\\": \\"<why it failed>\\"  // only if passed=false
}"
```

**Run all verifications in parallel.**

If any checked criterion fails:
- Uncheck it in the spec (`- [x]` -> `- [ ]`)
- Create a task to fix the regression:
  ```
  ralph task add '{"name": "Fix regression: <criterion>", "notes": "<DETAILED: what broke, file paths, approach>", "accept": "<measurable verification>"}'
  ```

### 4b: Check for uncovered criteria

For any **unchecked** criteria (`- [ ]`) not covered by existing tasks:
```
ralph task add '{"name": "...", "notes": "<DETAILED: file paths + approach>", "accept": "..."}'
```

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
"""

DEFAULT_PROMPT_INVESTIGATE = """# INVESTIGATE Stage

Issues were discovered during build or verification. Research and resolve ALL of them in parallel.

## Step 1: Get All Issues

Run `ralph query issues` to see all pending issues.

## Step 2: Parallel Investigation with Structured Output

Use the Task tool to investigate ALL issues in parallel. Each subagent MUST return structured findings:

```
Task: "Investigate this issue: <issue description>
Issue ID: <id>
Issue priority: <priority or 'medium'>

Analyze the codebase and return a JSON object:
{
  \\"issue_id\\": \\"<id>\\",
  \\"root_cause\\": \\"<specific file:line reference>\\",
  \\"resolution\\": \\"task\\" | \\"trivial\\" | \\"out_of_scope\\",
  \\"task\\": {
    \\"name\\": \\"<specific fix>\\",
    \\"notes\\": \\"Root cause: <file:line>. Fix: <approach>. Imports: <needed>. Risk: <side effects>.\\",
    \\"accept\\": \\"<measurable command + expected result>\\",
    \\"priority\\": \\"<from issue>\\",
    \\"research\\": {\\"files_analyzed\\": [\\"path:lines\\"], \\"root_cause_location\\": \\"file:line\\"}
  }
}"
```

## Step 3: Create Tasks with Full Context

After subagents complete, create tasks preserving research:

```
ralph task add '{"name": "Fix: <desc>", "notes": "Root cause: <file:line>. Fix: <approach>. Pattern: <similar code>. Risk: <effects>.", "accept": "<measurable>", "created_from": "<issue-id>", "priority": "<from issue>", "research": {"files_analyzed": ["path:lines"], "root_cause_location": "file:line"}}'
```

### Task Notes Template for Issues

```
Root cause: <file:line - specific problem>. 
Current behavior: <what happens>. Expected: <what should happen>. 
Fix approach: <how to fix>. Similar pattern: <existing code ref>. 
Imports needed: <any>. Risk: <side effects>.
```

## Step 4: Clear Issues

```
ralph issue done-all
```

## Step 5: Report

```
[RALPH] === INVESTIGATE COMPLETE ===
[RALPH] Processed: N issues
[RALPH] Tasks created: X (with full context)
```

## Handling Auto-Generated Pattern Issues

**REPEATED REJECTION issues:** Same task failed 3+ times
- Create HIGH PRIORITY blocking task addressing root cause
- Notes MUST include: which task fails, rejection pattern, how new task unblocks it

**COMMON FAILURE PATTERN issues:** Multiple tasks fail same way
- Create single HIGH PRIORITY task fixing root cause
- Notes MUST include: error pattern, affected tasks, fix approach

## Validation

Tasks from issues are validated. REJECTED if:
- Notes < 50 chars or missing root cause location
- Acceptance criteria is vague
- Missing file:line references

## Rules

- Launch ALL investigations in parallel
- Preserve research in notes with file:line references
- Measurable acceptance for every task
- Use `created_from` to link to source issue
- EXIT after all issues resolved
"""

DEFAULT_PROMPT_DECOMPOSE = """# DECOMPOSE Stage

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

**CRITICAL**: Log may be HUGE. NEVER read entire file:

```bash
wc -l <kill_log_path>
head -50 <kill_log_path>
tail -100 <kill_log_path>
```

Determine: what was completed, what caused context explosion, partial progress.

## Step 3: Research the Breakdown

Use subagent to analyze:

```
Task: "Analyze how to decompose: [task name]
Original notes: [task notes]

Return JSON:
{
  \\"remaining_work\\": [
    {\\"subtask\\": \\"<specific piece>\\", \\"files\\": [{\\"path\\": \\"file.py\\", \\"lines\\": \\"100-150\\"}], \\"effort\\": \\"small|medium\\"}
  ],
  \\"context_risks\\": \\"<what caused explosion>\\",
  \\"mitigation\\": \\"<how subtasks avoid it>\\"
}"
```

## Step 4: Create Subtasks with Full Context

Each subtask MUST include:

1. **Source locations**: Exact file paths with line numbers
2. **What to do**: Specific bounded action
3. **How to do it**: Implementation approach
4. **Context from parent**: What was learned
5. **Risk mitigation**: How to avoid re-kill

**Template:**
```
ralph task add '{"name": "Specific subtask", "notes": "Source: <file> lines <N-M>. <Action>. Imports: <list>. Context from parent: <findings>. Risk mitigation: <avoid context explosion by...>", "accept": "<measurable>", "parent": "<task-id>"}'
```

**Example:**
```json
{
  "name": "Create fallback.py with DashboardState dataclass",
  "notes": "Source: powerplant/ralph lines 4022-4045 (DashboardState only). Create ralph/tui/fallback.py with just dataclass. Imports: dataclass, field, Optional, deque. Risk mitigation: Don't extract full class yet - just dataclass.",
  "accept": "python3 -c 'from ralph.tui.fallback import DashboardState' exits 0",
  "parent": "t-original"
}
```

## Step 5: Delete Original Task

```
ralph task delete <original-task-id>
```

## Step 6: Report

```
[RALPH] === DECOMPOSE COMPLETE ===
[RALPH] Original: <task name>
[RALPH] Kill reason: <timeout|context_limit>
[RALPH] Context risk: <what caused explosion>
[RALPH] Mitigation: <how subtasks avoid it>
[RALPH] Split into: N subtasks
```

## Validation

Subtasks are validated. REJECTED if:
- Notes < 50 chars or missing source line numbers
- Modification tasks without specific locations
- Acceptance criteria is vague

## Rules

1. ALWAYS review kill log first (head/tail only!)
2. Each subtask < 100k tokens - completable in ONE iteration
3. Preserve context from parent task notes
4. Include line numbers for every subtask
5. Measurable acceptance criteria
6. Include risk mitigation for each subtask
7. Maximum decomposition depth: 3 levels
8. DO NOT implement - just create task breakdown
"""

EXAMPLE_SPEC = """# Example Specification

Delete this file and create your own specs.

## Overview

Describe what you want to build.

## Requirements

- Requirement 1
- Requirement 2

## Acceptance Criteria

- [ ] Criterion 1
- [ ] Criterion 2
"""
