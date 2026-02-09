---
name: ralph-spec
description: Write Ralph specification documents - structured feature specs with clear requirements, acceptance criteria, and implementation guidance for autonomous task execution
license: MIT
compatibility: opencode
metadata:
  category: planning
  system: ralph
---

# Writing Ralph Specs

Use this skill when creating or improving specification documents for Ralph, the autonomous task execution system.

## How Specs Become Work

Understanding the pipeline is essential to writing good specs:

```
SPEC (you write)
  |
  v
PLAN stage (LLM reads spec, does gap analysis against codebase)
  |
  v
TASKS (LLM generates: name, notes, accept, deps, priority)
  |
  v
BUILD stage (separate LLM implements one task per iteration)
  |
  v
VERIFY stage (checks task's acceptance criteria)
```

**The spec is a requirements document.** It defines WHAT must be true when done and HOW to verify it. The planner decides task boundaries, implementation order, and per-task acceptance criteria. The builder writes the code.

A spec's job is to give the planner enough structure and clarity that it naturally produces well-scoped tasks. You do NOT need to prescribe task boundaries in the spec — but you DO need to write requirements at a granularity that makes good decomposition obvious.

## Hard Limits

| Constraint | Limit | Why |
|-----------|-------|-----|
| Spec length | **≤ 300 lines** | The planner must read the spec AND explore the codebase in one context window. Long specs crowd out codebase research. |
| Files touched | **≤ 10 files** per spec | More than this means the spec covers multiple concerns. Split it. |
| New concepts | **≤ 3** per spec | Each new type, API, protocol, or abstraction adds cognitive load. |
| Requirements subsections | **≤ 8** H3 sections | Each subsection is a natural task boundary for the planner. More than 8 and the planner starts merging them. |

If your spec exceeds any of these, **split it into multiple specs**.

## Spec File Location

Place specs in: `ralph/specs/<spec-name>.md`

Use kebab-case for filenames (e.g., `user-authentication.md`, `api-rate-limiting.md`).

## Required Sections

Every Ralph spec MUST have these sections in order:

### 1. Title (H1)

```markdown
# Feature Name
```

Short, descriptive name. This becomes the spec identifier.

### 2. Overview

```markdown
## Overview

One paragraph explaining WHAT this feature does and WHY it exists.
Focus on the problem being solved, not implementation details.
```

### 3. Requirements

```markdown
## Requirements

### Subsection Name

Detailed requirements organized by topic. Use:
- Bullet points for lists of requirements
- Code blocks for interfaces, signatures, schemas
- Tables for structured data (field definitions, command references)
```

**Granularity rule**: Each H3 subsection under Requirements should describe ONE cohesive deliverable. The planner will naturally create one task (or a small cluster) per subsection. If a subsection requires changes to more than 3 files, it's too big — split it.

### 4. Acceptance Criteria

```markdown
## Acceptance Criteria

- [ ] Criterion 1: Specific, testable requirement
- [ ] Criterion 2: Another testable requirement
- [ ] Criterion 3: Edge case handling
```

**CRITICAL**: The VERIFY stage checks these. Each criterion must be independently verifiable — completing it should not require other criteria to be done first (unless there's an explicit dependency chain).

## Optional Sections

Add these when relevant:

### Architecture (for features with component interactions)

```markdown
## Architecture

Use ASCII diagrams for flows. Keep brief — architecture communicates
relationships, not implementation.
```

### Dependencies

```markdown
## Dependencies

- Requires `auth-core.md` to be implemented first
- Assumes `libfoo >= 2.0` is available
```

### Non-Requirements

```markdown
## Non-Requirements

- This spec does NOT change X
- Y is out of scope (see `other-spec.md`)
```

### Error Handling

```markdown
## Error Handling

| Error Condition | Response |
|-----------------|----------|
| Invalid input | Return error code X |
| Resource not found | Log warning, continue |
```

## What Goes in a Spec vs. What Doesn't

### YES — Put in the spec

- **Interfaces and signatures**: Function names, parameter types, return types
- **Struct/type layouts**: Field names, types, descriptions
- **Behavioral contracts**: "Function X must return Y when given Z"
- **Invariants**: "Field A must never be negative"
- **Verification commands**: "Run `pytest tests/unit/test_foo.py`"
- **Error conditions and responses**: What happens on each failure mode
- **Constraints**: Performance bounds, concurrency requirements

### NO — Keep out of the spec

- **Full function bodies**: The builder writes code, not the spec author. Including complete implementations means the builder just copy-pastes without understanding, and the planner has no signal about task boundaries. Provide signatures and contracts instead.
- **Line-by-line implementation instructions**: "On line 42 of foo.c, add..." — this is task-level detail that belongs in the planner's task notes, not the spec.
- **Design rationale essays**: Keep it to 1-2 sentences per design decision. If you need more, put it in a separate architecture document referenced by the spec.
- **Phase/step sequences**: Don't prescribe implementation order. The planner determines order based on dependencies. If order matters, express it as dependency relationships between acceptance criteria or between specs.

## Writing Requirements That Produce Good Plans

### The Granularity Test

For each H3 subsection in Requirements, ask:

1. Can a developer implement this by touching ≤ 3 files? **If no, split.**
2. Can a developer verify this with one specific command? **If no, make the acceptance criterion more targeted.**
3. Would a developer need more than ~30 minutes to implement this? **If yes, split.**

### Good: Requirements that guide the planner

```markdown
### System Config Struct

Define `valk_system_config_t` in `src/gc.h`:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `gc_heap_size` | `u64` | `0` | Initial heap size (0 = auto) |

Provide `valk_system_config_default()` inline function returning defaults.
```

This gives the planner exactly what it needs: a type to create, where it goes, its fields and semantics. The planner generates a task like "Add valk_system_config_t to src/gc.h" with clear acceptance.

### Bad: Requirements that overwhelm the planner

```markdown
### System API Implementation

Here are the complete function bodies for src/gc.c:

\```c
valk_system_t *valk_system_create(valk_system_config_t *config) {
  valk_system_t *sys = calloc(1, sizeof(valk_system_t));
  sys->heap = valk_gc_heap_create(config->gc_heap_size);
  // ... 30 more lines ...
}

void valk_system_shutdown(valk_system_t *sys, u64 deadline_ms) {
  // ... 25 more lines ...
}

void valk_system_destroy(valk_system_t *sys) {
  // ... 15 more lines ...
}
// ... 5 more functions ...
\```
```

This is ~100 lines of code that the planner sees as ONE blob. It creates one task: "Implement System API." That task is too large for one BUILD iteration. Instead, specify each function's signature and contract separately:

```markdown
### System Lifecycle

| Function | Signature | Purpose |
|----------|-----------|---------|
| `valk_system_create` | `valk_system_t *valk_system_create(valk_system_config_t *config)` | Allocate, create heap, init handle table, register calling thread |
| `valk_system_destroy` | `void valk_system_destroy(valk_system_t *sys)` | Free heap, handle table, barrier, mark queues, the struct |
| `valk_system_shutdown` | `void valk_system_shutdown(valk_system_t *sys, u64 deadline_ms)` | Stop subsystems, wait for threads, wait+destroy subsystems |

`valk_system_create` must:
- Allocate with `calloc`
- Set `valk_sys` global pointer
- Call `valk_system_register_thread` for the calling thread
- Return the allocated system (never NULL on success)

`valk_system_shutdown` must:
- Set `shutting_down` flag atomically
- Call `stop()` on each subsystem under lock
- Spin-wait for `threads_registered` to reach 1 (with deadline)
- Call `wait()` then `destroy()` on each subsystem under lock
```

Now the planner sees three distinct functions with clear contracts and can decide whether to make them one task or three.

## Splitting Large Features Into Multiple Specs

When a feature is too large for one spec, split it into multiple specs with explicit cross-references.

### Naming Convention

```
ralph/specs/
  system-refactor-00-heap-rename.md     # Mechanical rename prerequisite
  system-refactor-01-types.md           # New type definitions + shims
  system-refactor-02-lifecycle.md       # System create/destroy/shutdown
  system-refactor-03-stw-protocol.md    # Barrier-based STW replacement
  system-refactor-04-aio-integration.md # AIO as subsystem
```

### Cross-References

Each spec declares its dependencies explicitly:

```markdown
## Dependencies

- Requires `system-refactor-01-types.md` to be completed (types must exist)
- Assumes heap types have been renamed per `system-refactor-00-heap-rename.md`
```

Ralph processes specs one at a time. Dependency ordering is the user's responsibility when invoking `ralph construct`.

### The Mechanical Change Spec

Large renames, search-and-replace operations, and other mechanical changes deserve their own spec. These specs are unique:

- Requirements are a **rename table** (old name → new name)
- Acceptance criteria is a **negative grep** (old names must not appear)
- No design decisions needed — pure transformation

```markdown
# Heap Type Rename

## Overview

Remove vestigial "2" suffixes from heap types and functions left over from
the malloc→page heap migration. Purely mechanical — no logic changes.

## Requirements

### Type Renames

| Old | New |
|-----|-----|
| `valk_gc_heap2_t` | `valk_gc_heap_t` |
| `valk_gc_page2_t` | `valk_gc_page_t` |
| `valk_gc_tlab2_t` | `valk_gc_tlab_t` |

### Function Renames

| Old | New |
|-----|-----|
| `valk_gc_heap2_create` | `valk_gc_heap_create` |
| `valk_gc_heap2_destroy` | `valk_gc_heap_destroy` |

### Files Affected

Source: `src/gc_heap.h`, `src/gc_heap.c`, `src/gc_mark.c`, `src/gc.c`
Tests: `test/test_memory.c`, `test/unit/test_gc.c`

## Acceptance Criteria

- [ ] `grep -rE 'heap2_|tlab2_|page2_' src/ test/` returns no matches
- [ ] `make build` succeeds
- [ ] `make test` passes (existing tests are the validation)
```

## Acceptance Criteria Best Practices

### Format

Each criterion should follow the pattern:

```markdown
- [ ] [What] [Verification command] [Expected result]
```

### Good Examples

```markdown
- [ ] `valk_system_config_t` defined in `src/gc.h`: `grep -c 'valk_system_config_t' src/gc.h` returns >= 1
- [ ] System create allocates heap: `test -f test/test_system.c && make test_system && ./build/test_system --test create` passes
- [ ] No old symbols remain: `grep -rE 'valk_gc_coord[^_]|valk_runtime_' src/` returns no matches
- [ ] Event loop shares system heap (no per-loop heap): `grep -c 'valk_gc_heap_create' src/aio/aio_uv.c` returns 0
```

### Bad Examples

```markdown
- [ ] System works correctly  <!-- Too vague, no command -->
- [ ] Performance is acceptable  <!-- Not measurable -->
- [ ] All tests pass  <!-- Which tests? Whole suite is untargeted -->
- [ ] Code compiles  <!-- Obvious, not a meaningful criterion -->
```

### Independence

Each acceptance criterion should be satisfiable without requiring unrelated criteria to be done first. If criterion B depends on criterion A, either:

1. Make A a separate spec that B's spec depends on, OR
2. Make the dependency explicit: "After [A criterion], verify [B criterion]"

The planner uses acceptance criteria to generate task dependencies. If criteria are tangled, the planner creates tangled tasks.

## Avoiding Task-Level Circular Dependencies

**CRITICAL**: Acceptance criteria that reference tests can create unfulfillable task dependencies.

### The Anti-Pattern

```
Task A: "Create foo.c"
  accept: "test_foo.c passes"
  
Task B: "Write test_foo.c"  
  deps: [Task A]  # Can't write tests until code exists
```

Deadlock: Task A requires test_foo.c which doesn't exist yet.

### Solutions

**Option 1: Import/existence acceptance for code tasks**

```markdown
- [ ] `foo.c` implements FooClass: `grep -c 'FooClass' src/foo.c` returns >= 1
- [ ] `test_foo.c` passes: `make test_foo && ./build/test_foo` passes
```

The planner creates two independent tasks. The test task naturally depends on the code task.

**Option 2: Bundle code + test in one criterion**

```markdown
- [ ] `foo.c` implements FooClass AND `test_foo.c` covers it: `make test_foo && ./build/test_foo` passes
```

Single task that includes both.

## Writing Style Rules

### DO

- Use imperative mood: "Define X", "Return Y", "Reject Z"
- Be specific: "Return JSON with fields `id`, `name`, `status`"
- Include type signatures for all functions/methods
- Specify exact error messages and codes
- Define all acronyms on first use
- Use tables for structured information (types, fields, renames)

### DON'T

- Use vague language: "should be fast", "handle errors appropriately"
- Leave behavior undefined: "returns appropriate response"
- Assume context: always state dependencies explicitly
- Include full function implementations (signatures + contracts only)
- Use "etc.", "and so on", or "similar" — list everything explicitly
- Include "TBD" or "TODO" items — resolve before finalizing
- Prescribe implementation order — the planner decides order

## Verification Checklist

Before finalizing a spec, verify:

1. **Size**: ≤ 300 lines? ≤ 10 files? ≤ 3 new concepts? ≤ 8 requirement subsections?
2. **No code bodies**: Only signatures, types, contracts? No copy-paste implementations?
3. **Completeness**: Every requirement has at least one acceptance criterion?
4. **Clarity**: No ambiguous language? All terms defined?
5. **Testability**: Each criterion has a specific shell command with expected result?
6. **Independence**: Each criterion verifiable without completing unrelated criteria?
7. **No circular deps**: Code criteria don't require tests that don't exist yet?
8. **Scope**: Single coherent feature? Dependencies on other specs explicit?

## Common Mistakes

| Mistake | Problem | Fix |
|---------|---------|-----|
| 1200-line mega-spec | Planner can't fit gap analysis in context; creates coarse tasks | Split into 4-8 focused specs with cross-references |
| Full function bodies in spec | Builder copy-pastes without understanding; planner sees one blob | Signatures + behavioral contracts only |
| "Phase 1... Phase 2..." structure | Planner maps 1 phase = 1 task (too coarse) | Separate specs per phase, or remove phase labels and let planner determine order |
| "Handle errors gracefully" | Undefined behavior | Specify exact error response per condition |
| "Should be performant" | Not measurable | "Responds within 100ms for 99th percentile" |
| "Similar to X" | Requires inference | Spell out the behavior explicitly |
| "etc." or "and so on" | Incomplete list | List all items explicitly |
| Missing edge cases | Incomplete spec | Add criteria for: empty input, max limits, concurrency, partial failures |
| Acceptance criteria: "tests pass" | Which tests? Untargeted. | "pytest tests/unit/test_foo.py passes" |
| Requirements section with 15+ items | Planner creates one mega-task | Split into multiple H3 subsections, each ≤ 3 files |

## Example: Good Spec (Complete)

```markdown
# System Thread Registration

## Overview

Add thread registration and unregistration to valk_system_t so the GC
coordinator knows how many threads are active and can wake event loop
threads for STW pauses.

## Dependencies

- Requires `system-types.md` (valk_system_t must exist with threads[] array)
- Requires `system-lifecycle.md` (valk_system_create must exist)

## Requirements

### Thread Info Extension

Add `wake_fn` and `wake_ctx` fields to `valk_gc_thread_info_t` in `src/gc.h`,
after the existing `mark_queue` field:

| Field | Type | Purpose |
|-------|------|---------|
| `wake_fn` | `void (*)(void *wake_ctx)` | Called to wake thread for STW |
| `wake_ctx` | `void *` | Opaque context passed to wake_fn |

Event loop threads set `wake_fn` to a `uv_async_send` wrapper.
Main thread sets `wake_fn = NULL` (woken by its own safe point check).

### Register Function

`void valk_system_register_thread(valk_system_t *sys, void (*wake_fn)(void *), void *wake_ctx)`

Must:
- Call `valk_mem_init_malloc()` for the calling thread
- Set `valk_thread_ctx.heap = sys->heap`
- Set `valk_thread_ctx.system = sys`
- Atomically increment `sys->threads_registered` and use the old value as slot index
- Populate `sys->threads[slot]` with ctx, thread_id, active=true, wake_fn, wake_ctx

### Unregister Function

`void valk_system_unregister_thread(valk_system_t *sys)`

Must:
- Call `VALK_GC_SAFE_POINT()` to participate in any pending STW
- Set `sys->threads[id].active = false` and `wake_fn = NULL`
- Atomically decrement `sys->threads_registered`
- Set `valk_thread_ctx.gc_registered = false`

### Wake All Function

`void valk_system_wake_threads(valk_system_t *sys)`

Iterate `sys->threads[0..MAX]`. For each active thread with non-NULL
`wake_fn`, call `wake_fn(wake_ctx)`.

## Acceptance Criteria

- [ ] `valk_gc_thread_info_t` has `wake_fn` and `wake_ctx` fields: `grep -c 'wake_fn' src/gc.h` returns >= 1
- [ ] Register function exists: `grep -c 'valk_system_register_thread' src/gc.c` returns >= 1
- [ ] Unregister function exists: `grep -c 'valk_system_unregister_thread' src/gc.c` returns >= 1
- [ ] Wake function exists: `grep -c 'valk_system_wake_threads' src/gc.c` returns >= 1
- [ ] After create, calling thread is registered: test in `test/test_system.c` — `make test_system && ./build/test_system --test create` passes
- [ ] Two registrations get unique slots: test in `test/test_system.c` — `make test_system && ./build/test_system --test register_unique_slot` passes
- [ ] Wake function calls wake_fn for active threads: test in `test/test_system.c` — `make test_system && ./build/test_system --test wake_threads` passes
```

This spec is 70 lines. The planner will likely create 3-5 tasks from it (struct extension, register, unregister, wake, tests). Each requirement subsection maps cleanly to a deliverable.

## Integration with Ralph Workflow

Once the spec is written:

1. **Plan**: `ralph plan <spec>` generates tasks from the spec
2. **Construct**: `ralph construct <spec>` enters construct mode:
   - **INVESTIGATE**: Converts issues into actionable tasks
   - **BUILD**: Executes tasks in priority/dependency order
   - **VERIFY**: Checks done tasks against acceptance criteria
   - **DECOMPOSE**: Breaks down failed tasks (timeout/context exceeded)
3. **Iterate**: Loop continues until all acceptance criteria satisfied

### Stage Flow

```
INVESTIGATE -> BUILD -> VERIFY
     ^                    |
     |     [gaps found]   |
     +--------------------+
            
     [failure: timeout/context]
              |
              v
         DECOMPOSE -> (next iteration)
```

## Tips for Spec Authors

1. **Start with acceptance criteria** — write what "done" looks like first, then fill in requirements
2. **Count your lines** — if over 200, start looking for split points; if over 300, split mandatory
3. **No code bodies** — signatures, types, tables, and contracts. The builder writes code.
4. **One concern per spec** — a "concern" is a cohesive set of changes that make sense together
5. **Think like the planner** — will the planner see clear task boundaries from your H3 sections?
6. **Think like the verifier** — can someone unfamiliar with the code run each acceptance criterion?
7. **Mechanical changes are their own spec** — renames, migrations, and search-replace ops are simple specs with rename tables and negative-grep acceptance criteria

## Ralph CLI Commands Reference

| Command | Description |
|---------|-------------|
| `ralph plan <spec>` | Generate tasks from spec (gap analysis) |
| `ralph construct <spec>` | Enter construct mode for spec |
| `ralph query` | Get full current state as JSON |
| `ralph query stage` | Get current stage |
| `ralph task add '<json>'` | Add single task |
| `ralph task add '[...]'` | Batch add tasks |
| `ralph task done` | Mark current task as done |
| `ralph task accept <id>` | Accept a done task |
| `ralph task reject <id> "reason"` | Reject a done task |

## Context Management

Ralph uses tiered context management:

| Threshold | Action |
|-----------|--------|
| 70% | Warning logged, execution continues |
| 85% | Compaction attempted |
| 95% | Kill current task, trigger DECOMPOSE |

Keep specs small to minimize context pressure. A 300-line spec plus codebase exploration can consume 40-60% of context before the planner even starts outputting tasks.

## Log Files

Ralph logs are stored in `/tmp/ralph-logs/<repo>/<branch>/<spec>/`.
Logs are auto-cleared on system restart.
