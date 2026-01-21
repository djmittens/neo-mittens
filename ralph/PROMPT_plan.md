# PLAN Stage: Gap Analysis for {{SPEC_FILE}}

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
  \"requirement\": \"<spec requirement being researched>\",
  \"current_state\": \"<what exists now - implemented/partial/missing>\",
  \"files_to_modify\": [
    {\"path\": \"src/foo.py\", \"lines\": \"100-150\", \"what\": \"extract X function\", \"how\": \"move to new module Y\"}
  ],
  \"files_to_create\": [
    {\"path\": \"src/bar.py\", \"template\": \"similar to src/existing.py\", \"purpose\": \"new module for Z\"}
  ],
  \"imports_needed\": [\"from X import Y\", \"from Z import W\"],
  \"dependencies\": {
    \"internal\": [\"requires module A to exist first\"],
    \"external\": [\"needs package X installed\"]
  },
  \"patterns_to_follow\": \"<reference similar existing code, e.g., 'Follow pattern from tui/art.py extraction'>\",
  \"spec_section\": \"<which section of spec defines this requirement>\",
  \"risks\": [\"could break if X\", \"depends on Y being complete\"],
  \"verification\": \"<how to verify this works: specific command + expected output>\"
}"
```

Launch multiple Task calls in a single message to parallelize research.

## Step 3: Create Tasks from Research

For each gap identified, create a task that **captures the research findings**:

```
ralph task add '{
  "name": "Short task name",
  "notes": "<DETAILED notes - see requirements below>",
  "accept": "<MEASURABLE criteria - see requirements below>",
  "deps": ["t-xxxx"],
  "research": {
    "files_analyzed": ["path/to/file.py:100-200"],
    "patterns_found": "description of patterns",
    "spec_section": "Section Name"
  }
}'
```

## Task Field Requirements

### `name` (required)
Short description of what to do (e.g., "Extract FallbackDashboard to tui/fallback.py")

### `notes` (required) - MUST INCLUDE ALL OF:

1. **Source locations**: Exact file paths with line numbers
   - "Source: powerplant/ralph lines 3757-4341"
   - "Modify ralph/cli.py lines 50-100 in create_parser()"

2. **What to do**: Specific actions with targets
   - "Extract RalphDashboard(App) class to new file"
   - "Add valk_builtin_aio_within() function after aio_race"

3. **How to do it**: Implementation approach
   - "Follow pattern from tui/art.py extraction"
   - "Register in valk_lenv_put_builtins() table"

4. **Imports/Dependencies**: What's needed
   - "Import from ralph.utils: Colors, generate_id"
   - "Requires t-68rt9c to complete first for DashboardState"

5. **Spec reference**: Which spec section
   - "See ralph-refactor.md 'tui/dashboard.py' section"

6. **Risks/Prerequisites**: What could go wrong
   - "Must update cli.py import after extraction"
   - "Depends on fallback.py existing for DashboardState import"

**Notes Template:**
```
Source: <file> lines <N-M>. <What to extract/modify>. 
Imports needed: <list>. Pattern: follow <similar code>. 
Spec ref: <section>. Prerequisites: <deps>. 
Risk: <what to watch for>.
```

**Good notes example:**
```
Source: powerplant/ralph lines 4643-4948 (FallbackDashboard class) and lines 4022-4045 (DashboardState dataclass). Extract to ralph/tui/fallback.py. Required imports: dataclass from dataclasses, Optional from typing, deque from collections, sys, os, time, datetime. Import from ralph.utils: Colors. Import from ralph.tui.art: RALPH_ART, RALPH_WIDTH. Must also extract render_dashboard() at lines 4950-5106. Add __all__ = ['DashboardState', 'FallbackDashboard', 'render_dashboard']. Spec ref: ralph-refactor.md 'tui/fallback.py' section. Risk: cli.py cmd_watch() imports FallbackDashboard - update import path after extraction.
```

**Bad notes (WILL BE REJECTED):**
- "Add the feature" - no file paths, no approach
- "Extract the dashboard" - which lines? what imports?
- "Write tests" - which files? what behaviors?
- "Update code as needed" - no specifics

### `accept` (required) - MUST BE:

1. **Specific**: Name exact files, commands, outputs
2. **Measurable**: Has concrete pass/fail condition
3. **Executable**: Can run command and check result

**Good examples:**
- `test -f ralph/tui/fallback.py && python3 -c "from ralph.tui.fallback import FallbackDashboard" exits 0`
- `pytest ralph/tests/unit/test_parser.py passes`
- `grep -c 'aio/within' src/builtins.c returns 1`
- `ralph --version outputs version string and exits 0`
- `head -2 powerplant/ralph shows '#!/usr/bin/env bash' on line 1`

**Bad examples (WILL BE REJECTED):**
- "works correctly" - not measurable
- "tests pass" - which tests?
- "is implemented" - how to verify?
- "feature works" - no command specified

### `deps` (optional)
List of task IDs this task depends on. Add prerequisite tasks first to get their IDs.

### `research` (optional but recommended)
Structured research findings for future reference:
```json
{
  "files_analyzed": ["powerplant/ralph:3757-4341", "ralph/tui/art.py"],
  "patterns_found": "Textual App subclass pattern",
  "imports_needed": ["from textual.app import App"],
  "spec_section": "tui/dashboard.py"
}
```

## Gold Standard Task Example

```json
{
  "name": "Extract FallbackDashboard to tui/fallback.py",
  "notes": "Source: powerplant/ralph lines 4643-4948 (FallbackDashboard class), lines 4022-4045 (DashboardState dataclass), lines 4950-5106 (render_dashboard function). Extract all three to ralph/tui/fallback.py. Required imports: dataclass/field from dataclasses, Optional from typing, deque from collections, sys, os, time, select, datetime. Import from ralph.utils: Colors. Import from ralph.tui.art: RALPH_ART, RALPH_WIDTH. Import from ralph.state: load_state, RalphState. Import from ralph.config: RalphConfig. Add DEFAULT_CONTEXT_WINDOW constant. Export via __all__ = ['DashboardState', 'FallbackDashboard', 'render_dashboard']. Spec ref: ralph-refactor.md 'tui/fallback.py' section. Risk: cli.py and dashboard.py import from this module - create before dashboard extraction.",
  "accept": "test -f ralph/tui/fallback.py && python3 -c \"from ralph.tui.fallback import FallbackDashboard, DashboardState, render_dashboard\" exits 0",
  "deps": ["t-i1oe9h"],
  "research": {
    "files_analyzed": ["powerplant/ralph:4022-4045", "powerplant/ralph:4643-4948", "powerplant/ralph:4950-5106"],
    "patterns_found": "ANSI dashboard with skeleton animation, uses DashboardState dataclass for state tracking",
    "imports_needed": ["from ralph.utils import Colors", "from ralph.tui.art import RALPH_ART"],
    "spec_section": "tui/fallback.py"
  }
}
```

## Rules

1. **One iteration per task**: Each task should be completable in ONE iteration (< 100k tokens)
2. **Dependency order**: Add prerequisite tasks first so you have their IDs for `deps`
3. **Be specific**: "Extract X from file Y lines N-M to file Z" not "Refactor X"
4. **Capture research**: Copy subagent findings directly into task notes
5. **Verify measurably**: Every `accept` must have a command that returns pass/fail
6. **Reference spec**: Every task should link back to which spec section it implements

## Validation

Tasks are validated before creation. The following will be REJECTED:

| Check | Requirement |
|-------|-------------|
| Notes length | Minimum 50 characters |
| File paths | Must contain at least one specific file path |
| Line numbers | Should include line numbers or function names |
| Implementation guidance | Must have action verbs (add, create, modify, extract, etc.) |
| Acceptance criteria | Must be measurable (command + expected result) |
| Vague phrases | "works correctly", "as needed", "implement the feature" rejected |

## Output

When done adding tasks, output:
```
[RALPH] PLAN_COMPLETE: Added N tasks for {{SPEC_FILE}}
```
