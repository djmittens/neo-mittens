# Ralph Agent Development Lifecycle (SDLC)

## Development Workflow

### Stages of Change
1. All changes to Ralph go through the `construct` stage
2. Each change requires comprehensive testing
3. Code must pass strict quality checks before acceptance

### Migration Phases
1. **Structure:** Establish core architectural layout
2. **Extract Modules:** Break monolithic code into modular components
3. **Extract Commands:** Separate command-line interface logic
4. **Extract Stages:** Modularize stage-specific behaviors
5. **Extract TUI:** Separate terminal user interface components
6. **Tests:** Comprehensive test suite implementation
7. **Cleanup:** Refine, optimize, and remove technical debt

## Testing Requirements

### Unit Tests
- All new functions require unit tests
- Use mocking for external dependencies
- Tests must:
  - Run without network access
  - Complete in < 30 seconds
  - Use minimal fixtures
- Coverage must not decrease

### End-to-End (E2E) Tests
- New commands require E2E tests
- Tests must:
  - Use temporary directories for isolation
  - Mock opencode calls
  - Clean up after execution
  - Complete in < 60 seconds

## Code Style Guidelines

### Function and Module Constraints
- Type hints required on all public functions
- Docstrings mandatory for public functions
- Max function length: ≤ 50 lines
- Max function complexity: ≤ 10
- Max module length: ≤ 500 lines
- Max class methods: ≤ 15

### Complexity Targets
- Use `radon cc` to verify complexity
- No function should have complexity ≥ 11
- Aim for clear, concise, and readable code

## Self-Improvement Loop

### Specification Generation
- Ralph can create and improve its own specs
- Use `ralph construct` on specs in `ralph/specs/`
- Continuous, incremental self-refinement

## Local Development

### Development Mode
- Changes take effect immediately
- Bootstrap ensures seamless package installation
- Maintain existing functionality during refactoring

## Principles

1. Incremental Refactoring
2. Maintain Existing Behavior
3. Strict Quality Enforcement
4. Automated Testing and Validation
5. Continuous Self-Improvement

## Task Quality Standards

### Gold Standard Task Example

Tasks MUST capture sufficient context for autonomous execution. Here's what a well-formed task looks like:

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

### Notes Requirements

Task notes MUST include:

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

### Notes Template

```
Source: <file> lines <N-M>. <What to extract/modify>. 
Imports needed: <list>. Pattern: follow <similar code>. 
Spec ref: <section>. Prerequisites: <deps>. 
Risk: <what to watch for>.
```

### Acceptance Criteria Requirements

Acceptance criteria MUST be:

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

### Task Validation

Tasks are validated before creation. REJECTED if:

| Check | Requirement |
|-------|-------------|
| Notes length | Minimum 50 characters |
| File paths | Must contain at least one specific file path |
| Line numbers | Modification tasks MUST include line numbers or function names |
| Implementation guidance | Must have action verbs (add, create, modify, extract, etc.) |
| Acceptance criteria | Must be measurable (command + expected result) |
| Vague phrases | "works correctly", "as needed", "implement the feature" rejected |

### Research Field

The optional `research` field preserves structured findings from PLAN/INVESTIGATE/DECOMPOSE stages:

```json
{
  "files_analyzed": ["powerplant/ralph:3757-4341", "ralph/tui/art.py"],
  "patterns_found": "Textual App subclass pattern",
  "imports_needed": ["from textual.app import App"],
  "spec_section": "tui/dashboard.py",
  "root_cause_location": "file.py:150",
  "fix_approach": "Add validation before call"
}
```

This helps BUILD stage execute without re-researching the codebase.