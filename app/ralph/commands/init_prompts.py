"""Default prompt templates for Ralph init command.

These prompts are written to ralph/PROMPT_*.md files during initialization.
Contains PLAN and BUILD stage prompts. See init_prompts_extra.py for others.
"""

from ralph.commands.init_prompts_extra import (
    DEFAULT_PROMPT_VERIFY,
    DEFAULT_PROMPT_INVESTIGATE,
    DEFAULT_PROMPT_DECOMPOSE,
    EXAMPLE_SPEC,
)

DEFAULT_PROMPT_PLAN = """# PLAN Stage: Gap Analysis for {{SPEC_FILE}}

## Step 1: Understand Current State

1. Run `ralph query` to see current state
2. Read the spec file: `ralph/specs/{{SPEC_FILE}}`

## Step 2: Research with Subagents

Your context window is LIMITED. Do NOT read many files yourself.

**Launch subagents in parallel to research different aspects. Each subagent MUST return structured findings:**

```
Task: "Research [requirement] for spec {{SPEC_FILE}}

Analyze the codebase and return a JSON object:
{
  \\"requirement\\": \\"<spec requirement being researched>\\",
  \\"current_state\\": \\"<what exists now - implemented/partial/missing>\\",
  \\"files_to_modify\\": [
    {\\"path\\": \\"src/foo.py\\", \\"lines\\": \\"100-150\\", \\"what\\": \\"extract X function\\", \\"how\\": \\"move to new module Y\\"}
  ],
  \\"files_to_create\\": [
    {\\"path\\": \\"src/bar.py\\", \\"template\\": \\"similar to src/existing.py\\", \\"purpose\\": \\"new module for Z\\"}
  ],
  \\"imports_needed\\": [\\"from X import Y\\", \\"from Z import W\\"],
  \\"dependencies\\": {
    \\"internal\\": [\\"requires module A to exist first\\"],
    \\"external\\": [\\"needs package X installed\\"]
  },
  \\"patterns_to_follow\\": \\"<reference similar existing code>\\",
  \\"spec_section\\": \\"<which section of spec defines this requirement>\\",
  \\"risks\\": [\\"could break if X\\", \\"depends on Y being complete\\"],
  \\"verification\\": \\"<how to verify this works: specific command + expected output>\\"
}"
```

Launch multiple Task calls in a single message to parallelize research.

## Step 3: Create Tasks from Research

For each gap identified, create a task that **captures the research findings**:

```
ralph task add '{"name": "Short task name", "notes": "<DETAILED>", "accept": "<MEASURABLE>", "deps": ["t-xxxx"], "research": {"files_analyzed": ["path:lines"], "spec_section": "Section"}}'
```

## Task Field Requirements

### `notes` (required) - MUST INCLUDE ALL OF:

1. **Source locations**: Exact file paths with line numbers (e.g., "Source: src/foo.py lines 100-150")
2. **What to do**: Specific actions with targets
3. **How to do it**: Implementation approach or pattern to follow
4. **Imports/Dependencies**: What's needed
5. **Spec reference**: Which spec section
6. **Risks/Prerequisites**: What could go wrong

**Notes Template:**
```
Source: <file> lines <N-M>. <What to extract/modify>. 
Imports needed: <list>. Pattern: follow <similar code>. 
Spec ref: <section>. Prerequisites: <deps>. 
Risk: <what to watch for>.
```

### `accept` (required) - MUST BE:

1. **Specific**: Name exact files, commands, outputs
2. **Measurable**: Has concrete pass/fail condition
3. **Executable**: Can run command and check result

**Good examples:**
- `test -f ralph/tui/fallback.py && python3 -c "from ralph.tui.fallback import X" exits 0`
- `pytest ralph/tests/unit/test_parser.py passes`
- `grep -c 'pattern' file.py returns 1`

**Bad examples (WILL BE REJECTED):**
- "works correctly" - not measurable
- "tests pass" - which tests?

### `research` (optional but recommended)

Structured research findings:
```json
{"files_analyzed": ["file:lines"], "patterns_found": "...", "spec_section": "..."}
```

## Validation

Tasks are validated. REJECTED if:
- Notes < 50 chars or missing file paths
- Modification tasks without line numbers or function names
- Acceptance criteria is vague ("works correctly", "is implemented")

## Output

When done:
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

PROMPT_TEMPLATES = {
    "PROMPT_plan.md": DEFAULT_PROMPT_PLAN,
    "PROMPT_build.md": DEFAULT_PROMPT_BUILD,
    "PROMPT_verify.md": DEFAULT_PROMPT_VERIFY,
    "PROMPT_investigate.md": DEFAULT_PROMPT_INVESTIGATE,
    "PROMPT_decompose.md": DEFAULT_PROMPT_DECOMPOSE,
}
