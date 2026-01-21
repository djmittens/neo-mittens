"""Ralph init command.

Creates ralph directory structure, prompt templates, and initial plan.jsonl.
Supports both fresh initialization and updating existing installations.
"""

import sys
from pathlib import Path
from typing import Optional

from ralph.prompts import merge_prompts
from ralph.state import RalphState, save_state
from ralph.utils import Colors


DEFAULT_PROMPT_PLAN = """## Target Spec: {{SPEC_FILE}}

1. Run `ralph query` to see current state
2. Read the spec file: `ralph/specs/{{SPEC_FILE}}`

## CRITICAL: Use Subagents for Research

Your context window is LIMITED. Do NOT read many files yourself.

**Launch subagents in parallel to research different aspects:**

```
Task: "Research how [aspect] is currently implemented. Find relevant files, understand the patterns used, and report back what exists and what's missing for [spec requirement]"
```

Launch multiple Task calls in a single message to parallelize research.

## Task: Gap Analysis for {{SPEC_FILE}}

Compare the spec against the CURRENT codebase and generate a task list:

1. Use subagents to study the spec and relevant source code thoroughly
2. For each requirement in the spec, check if it's already implemented
3. Create tasks ONLY for what's missing or broken
4. DO NOT implement anything - planning only

## Output

For each task identified, run:
```
ralph task add \'{"name": "Short task name", "notes": "Implementation details", "accept": "How to verify", "deps": ["t-xxxx"]}\'
```

Task fields:
- `name` (required): Short description of what to do (e.g., "Add unit tests for parser")
- `notes` (optional): Implementation context, hints, relevant files
- `accept` (optional): Acceptance criteria / test plan (e.g., "pytest tests/test_parser.py passes")
- `deps` (optional): List of task IDs this task depends on

The command returns the new task ID (e.g., "Task added: t-1a2b - ..."). Use this ID when other tasks depend on it.

Rules:
- Each task should be completable in ONE iteration
- Add tasks in dependency order - add prerequisite tasks first so you have their IDs
- Be specific - "Add X to Y" not "Improve Z"
- Tasks are for {{SPEC_FILE}} only
- Include `accept` criteria when testable
- Use `deps` when a task requires another task to be done first

When done adding tasks, output:
```
[RALPH] PLAN_COMPLETE: Added N tasks for {{SPEC_FILE}}
```
"""

DEFAULT_PROMPT_BUILD = """# BUILD Stage

Implement the next pending task.

## Step 1: Get Task

Run `ralph query` to get current state. The `next.task` field shows:
- `name`: what to do
- `notes`: implementation hints (if provided)
- `accept`: how to verify it works (if provided)
- `reject`: why it was rejected (if this is a retry)

## Step 2: Check if Rejected Task

If `reject` field is present, this task was previously attempted and rejected by VERIFY:

1. **Read the rejection reason** - understand why it failed
2. **The code is already there** - don't start from scratch
3. **Fix the specific gap** - the rejection reason tells you what's wrong

Do NOT re-explore the whole codebase. Focus on fixing what's broken.

## Step 3: Understand Context

1. Read the spec file: `ralph/specs/<spec>`
2. Review `notes` for implementation hints
3. **Use subagents for research** - see below

## CRITICAL: Use Subagents for Codebase Research

Your context window is LIMITED. Do NOT read many files yourself - you will run out of context and be killed.

**For any research task, use the Task tool to spawn subagents:**

```
Task: "Find how X is implemented in the codebase. Search for Y, read relevant files, and report back:
1. Which files contain X
2. How it currently works
3. What would need to change for Z"
```

**When to use subagents:**
- Understanding how a feature currently works
- Finding all usages of a function/type
- Exploring unfamiliar parts of the codebase
- Any task requiring reading more than 2-3 files

**When NOT to use subagents:**
- You already know exactly which file to edit
- Making a small, targeted change
- Running tests or build commands

Each subagent gets a fresh context window. Use them liberally for exploration.

## Step 4: Implement

Build the feature/fix. Rules:
- Complete implementations only, no stubs
- No code comments unless explicitly requested

## Step 5: Check Acceptance Criteria

Before marking done, verify the task's acceptance criteria:
1. Check **only** the `accept` criteria for this task
2. Run any tests specified in the criteria
3. Do NOT re-read the full spec - that's VERIFY stage's job

If acceptance criteria pass, mark done. VERIFY stage will do the thorough spec check later.

## Step 6: Complete

```
ralph task done
```

This marks the task done and auto-commits.

## Discovering Issues - IMPORTANT

You MUST record any problems you notice, even if unrelated to the current task:
```
ralph issue add "description of issue"
```

**Always add an issue when you see:**
- Test warnings (TSAN, ASAN, valgrind warnings)
- Compiler warnings
- Code that "works but has problems" (memory leaks, thread leaks, etc.)
- TODOs or FIXMEs you encounter
- Potential bugs you notice while reading code
- Missing test coverage you observe

**Do NOT ignore problems** just because your current task passes. If you see something wrong, record it.

Issues are investigated later in the INVESTIGATE stage.

## Spec Ambiguities - CRITICAL

**Do NOT make design decisions yourself.** If the spec is ambiguous or conflicts with technical constraints:

1. **Log an issue** with the ambiguity:
   ```
   ralph issue add "Spec ambiguity: <what the spec says> vs <technical reality>. Options: (1) ... (2) ..."
   ```

2. **Skip the task** or implement a minimal stub that makes the conflict visible

3. **Do NOT "interpret" the spec** - your interpretation may be wrong

**Examples of spec ambiguities:**
- Spec requires X but the architecture doesn't support X
- Spec is vague about behavior in edge case Y
- Two parts of the spec contradict each other
- Spec assumes a capability that doesn't exist

**Wrong:** "The pragmatic interpretation is..." then implementing your guess
**Right:** `ralph issue add "Spec says X but Y prevents this. Need clarification."`

Design decisions belong to the user, not the agent.

## Progress Reporting

```
[RALPH] === START: <task name> ===
```

```
[RALPH] === DONE: <task name> ===
[RALPH] RESULT: <summary>
```

## EXIT after marking task done
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

## Step 4: Check for Gaps

Read the spec\\'s **Acceptance Criteria section only** (not entire spec):
`ralph/specs/<spec-name>` - scroll to "## Acceptance Criteria"

For any unchecked criteria (`- [ ]`) not covered by existing tasks:
```
ralph task add \'{"name": "...", "accept": "..."}\'
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

Issues were discovered during build. Research and resolve ALL of them in parallel.

## Step 1: Get All Issues

Run `ralph query issues` to see all pending issues.

## Step 2: Parallel Investigation

Use the Task tool to investigate ALL issues in parallel. Launch one subagent per issue:

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
  \\"issue_id\\": \\"<id>\\",
  \\"root_cause\\": \\"<what you found>\\",
  \\"resolution\\": \\"task\\" | \\"trivial\\" | \\"out_of_scope\\",
  \\"task\\": {  // only if resolution is \\"task\\"
    \\"name\\": \\"<fix description>\\",
    \\"notes\\": \\"<root cause and approach>\\",
    \\"accept\\": \\"<how to verify>\\",
    \\"priority\\": \\"<inherit from issue priority above>\\"
  },
  \\"trivial_fix\\": \\"<description>\\"  // only if resolution is \\"trivial\\"
}
"
```

## Step 3: Collect Results and Apply

After all subagents complete:

1. Add all tasks in batch (include `created_from` to link back to issue, and `priority` from originating issue):
```
ralph task add \'{"name": "...", "notes": "...", "accept": "...", "created_from": "i-xxxx", "priority": "high|medium|low"}\'
ralph task add \'{"name": "...", "notes": "...", "accept": "...", "created_from": "i-yyyy", "priority": "high|medium|low"}\'
...
```

2. Clear all issues in one command:
```
ralph issue done-all
```

Or if only clearing specific issues:
```
ralph issue done-ids i-abc1 i-def2 i-ghi3
```

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
6. Mark existing failing tasks as depending on this new task using `ralph task add \'{"deps": [...]}\'`

**Example:**
If multiple tasks fail with "grep returns 0, expected 1" and they all involve `aio/then`, likely:
- The API wasn't changed to return handles yet
- A prerequisite C implementation task is missing
- Create: `ralph task add \'{"name": "Refactor X to return handle", "priority": "high", "notes": "..."}\'`

## IMPORTANT

- Launch ALL investigations in parallel using multiple Task tool calls in a single message
- Wait for all results before applying any changes
- Do NOT make code changes during investigation - only create tasks
- Use `ralph issue done-all` to clear all issues at once
- EXIT after all issues are resolved
"""

DEFAULT_PROMPT_DECOMPOSE = """# DECOMPOSE Stage

A task was killed because it was too large (exceeded context or timeout limits).
You must break it down into smaller subtasks.

## Step 1: Get the Failed Task

Run `ralph query` to see the task that needs decomposition.
The `next.task` field shows:
- `name`: The task that failed
- `kill_reason`: Why it was killed ("timeout" or "context_limit")
- `kill_log`: Path to the log from the failed iteration

## Step 2: Review the Failed Iteration Log (if available)

If `kill_log` is provided in the task, review it to understand what went wrong.

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
  - This is important! Subtasks may need to suppress or redirect verbose output

If no `kill_log` is provided, skip this step and proceed to analyze the task based on its description.

## Step 3: Analyze the Task

Use subagents to understand what the task requires:

```
Task: "Analyze what's needed to implement: [task name]

Research the codebase and report:
1. Which files need to be modified
2. What are the distinct pieces of work
3. What order should they be done in
4. Any dependencies between pieces"
```

## Step 4: Create Subtasks

Break the original task into 2-5 smaller tasks that:
- Can each be completed in ONE iteration
- Have clear, specific scope
- Together accomplish the original task
- Account for any partial progress from the failed iteration

For each subtask, **include `parent` to link back to the original task**:
```
ralph task add \'{"name": "Specific subtask", "notes": "What to do", "accept": "How to verify", "parent": "<original-task-id>"}\'
```

Use `deps` to specify order if needed.

## Step 5: Remove the Original Task

After adding all subtasks, delete the original oversized task:
```
ralph task delete <task-id>
```

## Step 6: Report

```
[RALPH] === DECOMPOSE COMPLETE ===
[RALPH] Original: <original task name>
[RALPH] Kill reason: <timeout|context_limit>
[RALPH] Split into: N subtasks
```

Then EXIT to let the build loop process the new subtasks.

## Rules

- ALWAYS read the log file first to understand what happened
- Each subtask should be completable in ONE iteration (< 100k tokens)
- Be specific: "Add X to file Y" not "Implement feature Z"
- If a subtask is still too big, it will be killed and decomposed again
- DO NOT try to implement anything - just create the task breakdown
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

PROMPT_TEMPLATES = {
    "PROMPT_plan.md": DEFAULT_PROMPT_PLAN,
    "PROMPT_build.md": DEFAULT_PROMPT_BUILD,
    "PROMPT_verify.md": DEFAULT_PROMPT_VERIFY,
    "PROMPT_investigate.md": DEFAULT_PROMPT_INVESTIGATE,
    "PROMPT_decompose.md": DEFAULT_PROMPT_DECOMPOSE,
}


def _prompt_merge_choice(filename: str) -> str:
    """Prompt user for merge choice when updating prompt files.

    Args:
        filename: The prompt file name.

    Returns:
        One of 'keep', 'override', or 'merge'.
    """
    print(f"\n{Colors.YELLOW}{filename} has been customized.{Colors.NC}")
    print("  [k] Keep existing (skip update)")
    print("  [o] Override with new default template")
    print("  [m] Merge customizations with new template (uses LLM)")

    while True:
        try:
            choice = input("Choice [k/o/m]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "keep"

        if choice in ("k", "keep"):
            return "keep"
        elif choice in ("o", "override"):
            return "override"
        elif choice in ("m", "merge"):
            return "merge"
        else:
            print("Please enter k, o, or m")


def _handle_prompt_file(prompt_path: Path, new_content: str, repo_root: Path) -> None:
    """Handle creating or updating a prompt file with merge options.

    Args:
        prompt_path: Path to the prompt file.
        new_content: The new default template content.
        repo_root: The repository root directory.
    """
    if not prompt_path.exists():
        prompt_path.write_text(new_content)
        return

    existing_content = prompt_path.read_text()

    if existing_content.strip() == new_content.strip():
        print(f"  {Colors.DIM}{prompt_path.name} - unchanged{Colors.NC}")
        return

    choice = _prompt_merge_choice(prompt_path.name)

    if choice == "keep":
        print(f"  {Colors.YELLOW}Keeping existing {prompt_path.name}{Colors.NC}")
    elif choice == "override":
        prompt_path.write_text(new_content)
        print(
            f"  {Colors.GREEN}Replaced {prompt_path.name} with default template{Colors.NC}"
        )
    elif choice == "merge":
        print(f"  {Colors.CYAN}Merging {prompt_path.name} with LLM...{Colors.NC}")
        merged = merge_prompts(
            existing_content, new_content, prompt_path.name, repo_root
        )
        if merged:
            prompt_path.write_text(merged)
            print(f"  {Colors.GREEN}Merged {prompt_path.name} successfully{Colors.NC}")
        else:
            print(
                f"  {Colors.YELLOW}Merge failed, keeping existing {prompt_path.name}{Colors.NC}"
            )


def cmd_init(repo_root: Optional[Path] = None) -> int:
    """Initialize or update Ralph in a repository.

    Creates the ralph directory structure, prompt templates, and initial
    plan.jsonl file. If ralph is already initialized, offers to update
    prompt templates with merge options.

    Args:
        repo_root: Repository root directory. If None, uses current directory.

    Returns:
        Exit code (0 for success).
    """
    if repo_root is None:
        repo_root = Path.cwd()

    ralph_dir = repo_root / "ralph"
    specs_dir = ralph_dir / "specs"
    plan_file = ralph_dir / "plan.jsonl"

    is_update = ralph_dir.exists()

    if is_update:
        print(f"Updating Ralph in {repo_root}")
    else:
        print(f"Initializing Ralph in {repo_root}")

    ralph_dir.mkdir(parents=True, exist_ok=True)
    specs_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in PROMPT_TEMPLATES.items():
        prompt_path = ralph_dir / filename
        _handle_prompt_file(prompt_path, content, repo_root)

    if not is_update:
        example_spec = specs_dir / "example.md"
        if not example_spec.exists():
            example_spec.write_text(EXAMPLE_SPEC)

        if not plan_file.exists():
            save_state(RalphState(), plan_file)

    if is_update:
        print(f"\n{Colors.GREEN}Ralph updated!{Colors.NC}")
        print(f"""
Updated files:
  ralph/
  ├── PROMPT_plan.md        (planning mode)
  ├── PROMPT_build.md       (build stage)
  ├── PROMPT_verify.md      (verify stage)
  ├── PROMPT_investigate.md (investigate stage)
  └── PROMPT_decompose.md   (decompose stage)

Preserved:
  ├── plan.jsonl
  └── specs/*
""")
    else:
        print(f"\n{Colors.GREEN}Ralph initialized!{Colors.NC}")
        print("""
Next steps:
  1. Write specs in ralph/specs/
  2. Run 'ralph plan <spec.md>' to generate tasks
  3. Run 'ralph' to start building

Files created:
  ralph/
  ├── PROMPT_plan.md        (planning mode)
  ├── PROMPT_build.md       (build stage)
  ├── PROMPT_verify.md      (verify stage)
  ├── PROMPT_investigate.md (investigate stage)
  ├── PROMPT_decompose.md   (decompose stage)
  ├── plan.jsonl            (task/issue state)
  └── specs/
      └── example.md        (delete and add your own)
""")

    return 0
