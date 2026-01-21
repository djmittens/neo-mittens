# INVESTIGATE Stage

Issues were discovered during build or verification. Research and resolve ALL of them in parallel.

## Step 1: Get All Issues

Run `ralph query issues` to see all pending issues.

## Step 2: Parallel Investigation with Structured Output

Use the Task tool to investigate ALL issues in parallel. Launch one subagent per issue.

**Each subagent MUST return structured findings:**

```
Task: "Investigate this issue: <issue description>
Issue ID: <issue id>
Issue priority: <issue priority or 'medium' if not set>

Analyze the codebase and return a JSON object:
{
  \"issue_id\": \"<id>\",
  \"issue_description\": \"<original issue>\",
  \"root_cause\": \"<what you found - be specific with file:line references>\",
  \"resolution\": \"task\" | \"trivial\" | \"out_of_scope\",
  
  \"task\": {
    \"name\": \"<specific fix description>\",
    \"notes\": \"<DETAILED - see requirements below>\",
    \"accept\": \"<MEASURABLE - see requirements below>\",
    \"priority\": \"<inherit from issue priority>\",
    \"research\": {
      \"files_analyzed\": [\"path/to/file.py:100-200\"],
      \"root_cause_location\": \"file.py:150 - missing null check\",
      \"fix_approach\": \"Add validation before call\"
    }
  },
  
  \"trivial_fix\": \"<description if resolution is trivial>\",
  \"out_of_scope_reason\": \"<explanation if out of scope>\"
}

### Task Notes Requirements (if resolution is 'task'):

Notes MUST include ALL of:
1. Source locations: 'File: src/foo.py lines 100-150'
2. Root cause: 'Missing validation in parse() function'
3. Fix approach: 'Add try/except block around JSON parse'
4. Imports needed: 'No new imports required'
5. Related code: 'Similar pattern exists in src/bar.py:200'
6. Risk: 'May affect callers of parse() - check cli.py'

### Task Accept Requirements:

Accept MUST be measurable:
- 'pytest tests/test_parser.py::test_malformed_input passes'
- 'grep -c \"except JSONDecodeError\" src/foo.py returns 1'
- 'python3 -c \"from foo import parse; parse(\\'{}\\')\" exits 0'
"
```

## Step 3: Collect Results and Create Tasks

After all subagents complete, create tasks that preserve the research:

```bash
ralph task add '{
  "name": "Fix: <specific description>",
  "notes": "Root cause: <from investigation>. File: <path> lines <N-M>. Fix: <approach>. Pattern: <similar code reference>. Risk: <what to watch for>.",
  "accept": "<measurable verification>",
  "created_from": "<issue-id>",
  "priority": "<from issue>",
  "research": {
    "files_analyzed": ["path:lines"],
    "root_cause_location": "file:line",
    "fix_approach": "description"
  }
}'
```

### Task Notes Template for Issues

```
Root cause: <specific problem found at file:line>. 
File: <path> lines <N-M>. 
Current behavior: <what happens now>. 
Expected behavior: <what should happen>. 
Fix approach: <how to fix>. 
Similar pattern: <reference to existing code>. 
Imports needed: <any new imports>. 
Risk: <side effects to check>.
```

### Example Task from Issue

**Issue:** "TypeError in parse_config() when config file is empty"

**Investigation found:**
- Root cause: `parse_config()` in `src/config.py:45` doesn't handle empty file
- Returns `None` which caller doesn't expect
- Similar handling exists in `src/state.py:load_state()` at line 80

**Task created:**
```json
{
  "name": "Fix TypeError in parse_config for empty files",
  "notes": "Root cause: src/config.py:45 parse_config() returns None for empty file, but caller expects dict. Current behavior: TypeError 'NoneType has no attribute get'. Expected: Return empty dict {} for empty file. Fix approach: Add 'if not content: return {}' before JSON parse at line 47. Similar pattern: src/state.py:80 load_state() handles empty with 'return RalphState()'. No new imports needed. Risk: Check all callers of parse_config() handle empty dict.",
  "accept": "python3 -c \"from ralph.config import parse_config; import tempfile; f=tempfile.NamedTemporaryFile(mode='w',suffix='.toml',delete=False); f.close(); parse_config(f.name)\" exits 0",
  "created_from": "i-abc123",
  "priority": "high",
  "research": {
    "files_analyzed": ["src/config.py:40-60", "src/state.py:75-90"],
    "root_cause_location": "src/config.py:45",
    "fix_approach": "Add empty file check before parse"
  }
}
```

## Step 4: Clear Resolved Issues

After creating all tasks:

```bash
# Clear all issues at once
ralph issue done-all

# Or clear specific issues
ralph issue done-ids i-abc1 i-def2 i-ghi3
```

## Step 5: Report Summary

```
[RALPH] === INVESTIGATE COMPLETE ===
[RALPH] Processed: N issues
[RALPH] Tasks created: X (with full context)
[RALPH] Trivial fixes: Y
[RALPH] Out of scope: Z
```

## Handling Auto-Generated Pattern Issues

Issues starting with "REPEATED REJECTION" or "COMMON FAILURE PATTERN" are auto-generated from rejection analysis. These require special handling:

### For REPEATED REJECTION issues:

The same task has failed 3+ times with similar errors.

1. Read the spec and task to understand what's expected
2. Read the rejection reasons to find the pattern
3. Identify the gap: missing prerequisite? wrong approach? spec ambiguity?
4. Create a HIGH PRIORITY blocking task that addresses root cause
5. Task notes MUST include:
   - Which task keeps failing and why
   - What the rejection pattern shows
   - How this new task unblocks the failing task

**Example:**
```json
{
  "name": "Create fallback.py before dashboard extraction",
  "notes": "Root cause: Task t-jcpk4m 'Extract Textual dashboard' rejected 12 times because it imports from ralph.tui.fallback which doesn't exist. Rejection pattern: 'ModuleNotFoundError: No module named ralph.tui.fallback'. Fix: Create fallback.py first with DashboardState class. Source: powerplant/ralph lines 4022-4045. This unblocks t-jcpk4m.",
  "accept": "python3 -c 'from ralph.tui.fallback import DashboardState' exits 0",
  "priority": "high"
}
```

### For COMMON FAILURE PATTERN issues:

Multiple different tasks fail with the same error type.

1. This indicates a missing prerequisite that all tasks need
2. Read the spec section about the failing functionality
3. The error message tells you what's missing
4. Create a single HIGH PRIORITY task to fix the root cause
5. Update failing tasks to depend on the new task

**Example:**
```json
{
  "name": "Add aio_handle return type to all aio functions",
  "notes": "Root cause: 5 different tasks fail with 'expected handle, got nil'. Pattern: All aio/ functions need to return handles but currently return nil. Source: src/aio/aio_base.c - all valk_builtin_aio_* functions. Fix: Update return statements to wrap result in aio_handle(). Spec ref: aio-spec.md 'Handle Return Type' section. This unblocks: t-abc, t-def, t-ghi.",
  "accept": "grep -c 'return aio_handle' src/aio/aio_base.c returns >= 5",
  "priority": "high"
}
```

## Validation Requirements

Tasks created from issues are validated. The following will be REJECTED:

| Check | Requirement |
|-------|-------------|
| Notes length | Minimum 50 characters |
| Root cause | Must identify specific file and location |
| Fix approach | Must describe what to change |
| Acceptance | Must be measurable command with expected result |
| Vague phrases | "fix the bug", "handle the error" rejected |

## Rules

1. **Launch ALL investigations in parallel** - one Task call per issue
2. **Preserve research in notes** - copy file:line references from investigation
3. **Measurable acceptance** - every task needs verifiable pass/fail
4. **Link to source issue** - use `created_from` field
5. **Inherit priority** - tasks get priority from their source issue
6. **No code changes** - only create tasks during INVESTIGATE
7. **Clear all issues** - use `ralph issue done-all` when complete
8. **EXIT after complete** - let BUILD stage execute the tasks
