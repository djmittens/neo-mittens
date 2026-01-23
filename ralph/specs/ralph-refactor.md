# Ralph Refactor

## Overview

Refactor ralph from a monolithic 6,949-line Python script (`powerplant/ralph`) into a well-structured modular package at `app/ralph/` with clear separation of concerns, comprehensive test coverage, and self-maintaining SDLC. The refactored ralph remains in this repository, is built/installed via `bootstrap.sh`, and operates locally with immediate testability of changes.

## Critical Guardrails

### Protected Files - DO NOT MODIFY

The following file is the **production ralph implementation** and MUST NOT be modified as part of this refactor:

```
powerplant/ralph    # The original monolithic Python script - DO NOT TOUCH
```

**Why this matters:**
- `powerplant/ralph` is the working, tested implementation currently in use
- The new `python -m ralph` package is being developed **in parallel**, not as a replacement
- Until the refactored package achieves 100% feature parity and passes all acceptance criteria, the original must remain intact
- Modifying `powerplant/ralph` during development could break the production tool

**What you CAN do:**
- Create and modify files in the `app/ralph/` package directory
- Create tests in `app/ralph/tests/`
- Modify `app/ralph/AGENTS.md`, `ralph/specs/*.md`, `ralph/PROMPT_*.md`

**What you MUST NOT do:**
- Edit, delete, or replace `powerplant/ralph`
- Create a wrapper script at `powerplant/ralph` (this is Phase 7, after full parity)
- Modify `powerplant/ralph` "to fix a bug" or "to add a feature"

The wrapper script replacement (Phase 7) happens ONLY after:
1. All acceptance criteria pass
2. Full command parity is verified
3. All tests pass
4. Human approval is given

## Requirements

### Directory Structure

Relocate ralph from `powerplant/ralph` to a proper Python package:

```
app/ralph/
├── __init__.py              # Package init, version
├── __main__.py              # Entry point: python -m ralph
├── cli.py                   # Argparse setup, command dispatch
├── config.py                # GlobalConfig, profile loading
├── state.py                 # RalphState, load/save JSONL, git sync
├── models.py                # Task, Issue, Tombstone, RalphPlanConfig dataclasses
├── stages/
│   ├── __init__.py
│   ├── base.py              # Stage enum, StageResult, StageOutcome
│   ├── investigate.py       # INVESTIGATE stage logic
│   ├── build.py             # BUILD stage logic
│   ├── verify.py            # VERIFY stage logic
│   └── decompose.py         # DECOMPOSE stage logic
├── context.py               # Metrics, context pressure, compaction
├── prompts.py               # Prompt building, PROMPT_*.md loading, merge logic
├── tui/
│   ├── __init__.py
│   ├── dashboard.py         # Textual TUI dashboard
│   ├── fallback.py          # ANSI fallback dashboard
│   └── art.py               # Ralph Wiggum ASCII art
├── commands/
│   ├── __init__.py
│   ├── init.py              # cmd_init
│   ├── status.py            # cmd_status
│   ├── config_cmd.py        # cmd_config (avoid name collision)
│   ├── watch.py             # cmd_watch
│   ├── stream.py            # cmd_stream
│   ├── plan.py              # cmd_plan
│   ├── construct.py         # cmd_construct
│   ├── query.py             # cmd_query
│   ├── task.py              # task subcommands (add, done, accept, reject, etc.)
│   └── issue.py             # issue subcommands (add, done, done-all, etc.)
├── analysis.py              # Rejection pattern analysis
├── git.py                   # Git operations (sync, push, status checks)
├── opencode.py              # OpenCode integration (spawn, parse output)
├── utils.py                 # ANSI colors, id generation, misc utilities
├── AGENTS.md                # Ralph's own SDLC and development rules
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Pytest fixtures
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_models.py
│   │   ├── test_state.py
│   │   ├── test_config.py
│   │   ├── test_context.py
│   │   ├── test_analysis.py
│   │   ├── test_prompts.py
│   │   ├── test_git.py
│   │   └── test_utils.py
│   └── e2e/
│       ├── __init__.py
│       ├── test_cli.py
│       ├── test_init.py
│       ├── test_task_workflow.py
│       └── test_construct_flow.py
└── py.typed                 # PEP 561 marker for type hints
```

### Bootstrap Integration

Update `bootstrap.sh` to support the refactored ralph **in parallel** with the original:

1. **DO NOT modify `powerplant/ralph`** - it remains the production implementation

2. **Add ralph package to PYTHONPATH** in bootstrap:
   - Add `export PYTHONPATH="$REPO_ROOT/app:$PYTHONPATH"` to shell configs
   - The `app/ralph/` directory becomes an importable package
   - This enables `python -m ralph` to run the new implementation for testing

3. **Preserve existing PATH setup** for `powerplant/` directory
   - The `ralph` command continues to invoke `powerplant/ralph`
   - Use `python -m ralph` to test the refactored version

4. **Keep shell completions working** - no changes needed during development

**During development:**
- `ralph` → runs `powerplant/ralph` (production)
- `python -m ralph` → runs the new modular package (testing)

**After Phase 7 (with human approval):**
- `powerplant/ralph` becomes a wrapper that invokes `python -m ralph`
- Both commands run the same code

### Local Development Mode

The new `python -m ralph` package operates with this repository as source of truth:

1. **No pip install required** - direct execution via PYTHONPATH
2. **Changes take effect immediately** - no rebuild/reinstall step
3. **Editable development** - modify any module in `app/ralph/`, run `python -m ralph`, see changes

Verification command:
```bash
# After making a change to app/ralph/cli.py, this reflects the change immediately:
python -m ralph --help

# The production ralph command is UNAFFECTED by changes to app/ralph/:
ralph --help  # Still runs powerplant/ralph
```

### Test Harness

#### Unit Tests

Each module has corresponding unit tests in `app/ralph/tests/unit/`:

| Module | Test File | Key Tests |
|--------|-----------|-----------|
| `models.py` | `test_models.py` | Task/Issue creation, status transitions, serialization |
| `state.py` | `test_state.py` | JSONL parsing, state load/save, merge logic |
| `config.py` | `test_config.py` | TOML loading, profile resolution, defaults |
| `context.py` | `test_context.py` | Metrics tracking, pressure thresholds, compaction |
| `analysis.py` | `test_analysis.py` | Rejection pattern detection |
| `prompts.py` | `test_prompts.py` | Prompt building, merge logic |
| `git.py` | `test_git.py` | Git command mocking, sync logic |
| `utils.py` | `test_utils.py` | ID generation, ANSI formatting |

Unit tests must:
- Use mocking for external dependencies (git, opencode, filesystem)
- Run without network access
- Complete in < 30 seconds total
- Use minimal fixtures to reduce token consumption when reading

#### E2E Tests

End-to-end tests in `app/ralph/tests/e2e/` validate complete workflows:

| Test File | Scenarios |
|-----------|-----------|
| `test_cli.py` | Command parsing, help output, version |
| `test_init.py` | Initialize ralph in temp repo, verify file creation |
| `test_task_workflow.py` | Add task, mark done, accept/reject |
| `test_construct_flow.py` | Mock opencode, verify stage transitions |

E2E tests must:
- Use temporary directories for isolation
- Mock opencode calls to avoid token usage
- Clean up after themselves
- Complete in < 60 seconds total

#### Test Commands

```bash
# Run all tests
pytest app/ralph/tests/

# Run only unit tests (fast)
pytest app/ralph/tests/unit/

# Run only e2e tests
pytest app/ralph/tests/e2e/

# Run with coverage
pytest app/ralph/tests/ --cov=ralph --cov-report=term-missing
```

### Module Responsibilities

#### `cli.py`
- Argparse setup with subcommands
- Command dispatch to `commands/` modules
- Global exception handling
- Exit code management

#### `config.py`
- `GlobalConfig` dataclass
- Load from `~/.config/ralph/config.toml`
- Profile support via `RALPH_PROFILE`
- Default values and validation

#### `models.py`
- `Task` dataclass with all fields (id, name, spec, notes, accept, deps, status, priority, parent, created_from, supersedes)
- `Issue` dataclass
- `Tombstone` dataclass
- `RalphPlanConfig` dataclass
- Serialization to/from JSONL dicts

#### `state.py`
- `RalphState` class holding tasks, issues, tombstones, config
- `load_state(path)` - parse plan.jsonl
- `save_state(state, path)` - write plan.jsonl
- State validation and integrity checks

#### `stages/base.py`
- `Stage` enum: INVESTIGATE, BUILD, VERIFY, DECOMPOSE, COMPLETE
- `StageOutcome` enum: SUCCESS, FAILURE, SKIP
- `StageResult` dataclass
- `ConstructStateMachine` class

#### `stages/investigate.py`, `build.py`, `verify.py`, `decompose.py`
- Each contains a `run(state, config) -> StageResult` function
- Single responsibility per file
- Clear input/output contracts

#### `context.py`
- `Metrics` dataclass for session tracking
- `IterationKillInfo` for killed iterations
- `ToolSummaries` for conversation summarization
- `CompactedContext` for resumption
- Threshold constants: WARNING_PCT=70, COMPACT_PCT=85, KILL_PCT=95

#### `prompts.py`
- `load_prompt(stage)` - load PROMPT_*.md
- `build_prompt_with_rules(prompt, rules_path)` - combine with project rules
- `merge_prompts(old, new, strategy)` - prompt update handling

#### `git.py`
- `sync_with_remote()` - fetch and merge remote changes
- `push_with_retry(retries=3)` - push with retry logic
- `has_uncommitted_plan()` - check git status
- `get_current_commit()` - get HEAD hash

#### `opencode.py`
- `spawn_opencode(prompt, cwd, timeout)` - spawn opencode process
- `parse_json_stream(output)` - parse structured output
- `extract_metrics(output)` - extract cost/token metrics
- Environment setup (XDG_STATE_HOME, permissions)

#### `analysis.py`
- `analyze_rejection_patterns(tombstones)` - detect recurring failures
- `suggest_issues(patterns)` - generate issues from patterns

#### `tui/dashboard.py`
- Textual-based dashboard app
- Real-time status display
- Stage progress visualization

#### `tui/fallback.py`
- ANSI-based fallback for terminals without Textual
- Same information, simpler rendering

#### `tui/art.py`
- Ralph Wiggum ASCII art in multiple styles
- Art selection based on state/stage

### Cyclomatic Complexity Targets

Each function must have cyclomatic complexity ≤ 10:

| Metric | Target |
|--------|--------|
| Max function complexity | ≤ 10 |
| Max function length | ≤ 50 lines |
| Max module length | ≤ 500 lines |
| Max class methods | ≤ 15 |

Use `radon` for measurement:
```bash
radon cc app/ralph/ -a -s  # Show complexity with average
radon cc app/ralph/ --min C  # Show only functions with complexity ≥ C
```

### AGENTS.md (Ralph's SDLC)

Create `app/ralph/AGENTS.md` with ralph's own development rules:

```markdown
# Ralph Development Rules

## Overview
Ralph is developed by Ralph. This file defines the SDLC for ralph development.

## Development Workflow
1. Changes to ralph code go through ralph's own construct mode
2. All changes require tests
3. Complexity limits are enforced

## Testing Requirements
- New functions require unit tests
- New commands require e2e tests
- Coverage must not decrease

## Code Style
- Type hints on all public functions
- Docstrings on all public functions
- No function > 50 lines
- No complexity > 10

## Self-Improvement Loop
Ralph can create specs for its own improvement in `ralph/specs/`.
Ralph runs `ralph construct` on its own specs.
```

### Migration Path

The refactor must be incremental to maintain functionality:

**Phase 1: Structure**
1. Create `app/ralph/` directory structure
2. Create `__init__.py` and `__main__.py`
3. Update `bootstrap.sh` with PYTHONPATH setup
4. Verify `python -m ralph --help` works

**Phase 2: Extract Modules**
1. Extract `models.py` (dataclasses)
2. Extract `config.py` (GlobalConfig)
3. Extract `state.py` (JSONL operations)
4. Extract `utils.py` (utilities)
5. Extract `git.py` (git operations)

**Phase 3: Extract Commands**
1. Create `commands/` package
2. Extract each command to its own file
3. Update `cli.py` to import from commands

**Phase 4: Extract Stages**
1. Create `stages/` package
2. Extract stage logic to individual files
3. Keep state machine in `stages/base.py`

**Phase 5: Extract TUI**
1. Create `tui/` package
2. Extract dashboard code
3. Extract ASCII art

**Phase 6: Tests**
1. Create test structure
2. Write unit tests for extracted modules
3. Write e2e tests for CLI

**Phase 7: Cleanup (REQUIRES HUMAN APPROVAL)**

⚠️ **DO NOT EXECUTE PHASE 7 AUTONOMOUSLY** ⚠️

Phase 7 modifies `powerplant/ralph` and requires explicit human approval:

1. **Human verification**: All acceptance criteria must be manually verified
2. **Human approval**: Get explicit "proceed with Phase 7" confirmation
3. Replace `powerplant/ralph` with wrapper script (only after approval)
4. Verify all commands work via the new wrapper
5. Run complexity checks
6. Final human sign-off

Until Phase 7 is explicitly approved, `powerplant/ralph` remains the production implementation and `python -m ralph` runs in parallel for testing.

## Acceptance Criteria

### Structure
- [ ] `app/ralph/` directory exists
- [ ] `app/ralph/__init__.py` defines `__version__`
- [ ] `app/ralph/__main__.py` provides entry point
- [ ] `app/ralph/cli.py` contains argparse setup
- [ ] All modules listed in Directory Structure exist

### Bootstrap
- [ ] `powerplant/ralph` remains unchanged (original monolithic script intact)
- [ ] `bootstrap.sh` adds `app/` to PYTHONPATH
- [ ] `python -m ralph --version` works after running bootstrap
- [ ] `ralph --version` continues to work (runs original `powerplant/ralph`)
- [ ] Shell completions continue to work

### Local Development
- [ ] Editing `app/ralph/cli.py` and running `python -m ralph` reflects changes immediately
- [ ] No pip install or build step required for `python -m ralph`
- [ ] `python -m ralph` works from repository root
- [ ] `ralph` command continues to run `powerplant/ralph` (unaffected by changes to `app/ralph/`)

### Tests
- [ ] `pytest app/ralph/tests/unit/` runs without errors
- [ ] `pytest app/ralph/tests/e2e/` runs without errors
- [ ] Unit tests complete in < 30 seconds
- [ ] E2E tests complete in < 60 seconds
- [ ] E2E tests do not consume API tokens (opencode is mocked)
- [ ] `app/ralph/tests/conftest.py` provides common fixtures

### Complexity
- [ ] `radon cc app/ralph/ --min C` returns no results (no function with complexity ≥ C)
- [ ] No function exceeds 50 lines
- [ ] No module exceeds 500 lines

### Modules
- [ ] `models.py` contains Task, Issue, Tombstone, RalphPlanConfig dataclasses
- [ ] `state.py` contains load_state, save_state, RalphState
- [ ] `config.py` contains GlobalConfig with TOML loading
- [ ] `context.py` contains Metrics and context pressure logic
- [ ] `stages/*.py` each contain a single stage's logic
- [ ] `commands/*.py` each contain a single command's logic
- [ ] `tui/dashboard.py` contains Textual dashboard
- [ ] `tui/fallback.py` contains ANSI fallback

### SDLC
- [ ] `app/ralph/AGENTS.md` exists with development rules
- [ ] `python -m ralph construct` can run on specs in `ralph/specs/` (testing new implementation)
- [ ] All public functions have type hints
- [ ] All public functions have docstrings
- [ ] `powerplant/ralph` has NOT been modified (guardrail respected)

### Plan Mode Issue Handling

When `ralph plan` completes successfully:
- All issues for the same spec should be automatically closed
- Rationale: Plan mode does comprehensive gap analysis; any issues from prior failures are now superseded by the new plan
- This prevents stale issues from accumulating and cluttering status output

Implementation:
```python
# After PLAN_COMPLETE signal and task commit:
issues_for_spec = [i for i in state.issues if i.spec == spec_file]
if issues_for_spec:
    state.issues = [i for i in state.issues if i.spec != spec_file]
    save_state(state, config)
    print(f"Cleared {len(issues_for_spec)} issues (superseded by new plan)")
```

### Command Parity (python -m ralph vs powerplant/ralph)

The new `python -m ralph` must produce identical behavior to `powerplant/ralph`:

- [ ] `python -m ralph init` works identically to `ralph init`
- [ ] `python -m ralph status` works identically to `ralph status`
- [ ] `python -m ralph config` works identically to `ralph config`
- [ ] `python -m ralph watch` works identically to `ralph watch`
- [ ] `python -m ralph plan` works identically to `ralph plan`
- [ ] `python -m ralph construct` works identically to `ralph construct`
- [ ] `python -m ralph query` works identically to `ralph query`
- [ ] `python -m ralph task add/done/accept/reject/delete/prioritize` work identically
- [ ] `python -m ralph issue add/done/done-all/done-ids` work identically
- [ ] `python -m ralph stream` works identically to `ralph stream`
- [ ] `python -m ralph validate` works identically to `ralph validate`
- [ ] `python -m ralph compact` works identically to `ralph compact`

### Backwards Compatibility
- [ ] Existing `ralph/specs/*.md` files are preserved (note: specs stay in `ralph/specs/`, not `app/ralph/specs/`)
- [ ] Existing `ralph/plan.jsonl` files are readable by `python -m ralph`
- [ ] Existing `ralph/PROMPT_*.md` files work with `python -m ralph`
- [ ] Global config at `~/.config/ralph/config.toml` works with `python -m ralph`
- [ ] `powerplant/ralph` continues to work exactly as before (not modified)
