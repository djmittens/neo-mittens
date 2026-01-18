# Ralph Wiggum - Autonomous AI Development

Ralph is a bash loop that runs Claude Code autonomously until tasks are complete.
Named after Ralph Wiggum from The Simpsons - perpetually confused, always making 
mistakes, but never stopping.

> "Ralph is a Bash loop" - Geoffrey Huntley

## Quick Start

```bash
# Initialize ralph in your repo
cd your-project
ralph init

# Write specs describing what you want to build
vim ralph/specs/my-feature.md

# Generate implementation plan
ralph plan

# Let ralph build it
ralph 10  # Run 10 iterations
```

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                      YOUR SPECS                              │
│                   ralph/specs/*.md                          │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                   PLANNING MODE                              │
│              ralph plan                                      │
│                                                              │
│  • Reads specs                                               │
│  • Analyzes existing code                                    │
│  • Creates IMPLEMENTATION_PLAN.md                            │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    BUILD MODE                                │
│                 ralph [N]                                    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  ITERATION LOOP (runs N times or until Ctrl+C)      │    │
│  │                                                      │    │
│  │  1. Read IMPLEMENTATION_PLAN.md                      │    │
│  │  2. Pick highest priority task                       │    │
│  │  3. Implement it                                     │    │
│  │  4. Run tests                                        │    │
│  │  5. Commit & push                                    │    │
│  │  6. Update plan                                      │    │
│  │  7. EXIT (fresh context for next iteration)          │    │
│  │                                                      │    │
│  └──────────────────────┬───────────────────────────────┘    │
│                         │                                    │
│                         ▼                                    │
│                    Loop restarts                             │
└─────────────────────────────────────────────────────────────┘
```

## Commands

```bash
ralph init          # Initialize ralph in current repo
ralph plan          # Generate implementation plan from specs (runs once)
ralph status        # Show current status
ralph watch         # Live dashboard (run in separate terminal)
ralph log           # Tail the current log
ralph help          # Show help

# Build mode (implement from plan)
ralph               # Run forever (until Ctrl+C or no tasks left)
ralph 10            # Run max 10 iterations then stop
ralph build 10      # Same as above (explicit)
```

**Iteration limits:** The number after `ralph` or `ralph build` sets how many
iterations to run before stopping. Default is **unlimited** (runs until Ctrl+C
or no tasks remain). Use limits for unattended runs (e.g., `ralph 50` overnight).

**Planning vs Building:**
- `ralph plan` - Analyzes specs and code, creates a task list. Runs once. Does NOT write code.
- `ralph` / `ralph build` - Implements tasks from the plan, one per iteration.

## Directory Structure

After `ralph init`, your repo will have:

```
your-project/
├── ralph/
│   ├── PROMPT_plan.md          # Planning mode instructions
│   ├── PROMPT_build.md         # Build mode instructions  
│   ├── IMPLEMENTATION_PLAN.md  # Auto-managed task list
│   └── specs/
│       └── *.md                # Your requirement specs
├── build/
│   └── ralph-logs/             # Iteration logs (gitignored)
└── ... your code ...
```

## Writing Specs

Specs go in `ralph/specs/`. Each file describes one feature or topic.

**Good spec structure:**

```markdown
# Feature Name

## Overview
What this feature does and why.

## Requirements
- Specific requirement 1
- Specific requirement 2

## Acceptance Criteria
- [ ] Testable criterion 1
- [ ] Testable criterion 2

## Notes
Any context that helps implementation.
```

**Tips:**
- One topic per spec file
- Be specific about acceptance criteria
- Include examples where helpful
- Smaller specs = faster convergence

## Customizing Prompts

Edit `ralph/PROMPT_build.md` to customize how Ralph works:

- Add project-specific build/test commands
- Include coding standards
- Add constraints (e.g., "no comments", "use TypeScript")
- Specify how to handle errors

Example additions:

```markdown
## Build Commands
- `npm run build` - Build the project
- `npm test` - Run tests
- `npm run lint` - Check linting

## Code Style
- Use TypeScript strict mode
- No console.log in production code
- All functions must have JSDoc
```

## Monitoring

```bash
# Watch live output
ralph log

# Or manually
tail -f build/ralph-logs/ralph-*.log

# Check commits
git log --oneline -10

# See status
ralph status
```

## Safety

Ralph uses `--dangerously-skip-permissions` to run autonomously.

**Recommendations:**
- Run in a sandboxed environment for untrusted code
- Use a separate git branch
- Review commits before merging to main
- Set reasonable iteration limits

**Recovery:**
- `Ctrl+C` stops the loop
- `git reset --hard HEAD~N` undoes N commits
- Delete and regenerate `IMPLEMENTATION_PLAN.md` if stuck

## Integration with AGENTS.md

If your repo has an `AGENTS.md` (Claude Code's project instructions), Ralph 
will use it automatically. You can add Ralph-specific guidance there:

```markdown
## Ralph-Specific

- Run `make test` after changes
- Coverage must stay above 80%
- Always update CHANGELOG.md
```

## Re-planning

Run `ralph plan` again whenever:
- You update specs
- The plan feels stale or wrong
- Ralph seems stuck

**The plan is disposable.** Planning does a fresh gap analysis of specs vs current
code. It ignores old pending tasks and regenerates from scratch. Completed tasks
and discovered issues are preserved as history.

Think of it like clay on a pottery wheel - if something isn't right, throw it
back on the wheel.

## Philosophy

**Why the loop works:**

1. **Fresh context** - Each iteration starts clean with full context budget
2. **One task at a time** - Focused work, not scattered attention
3. **Eventual consistency** - Mistakes get fixed in subsequent iterations
4. **Backpressure** - Tests/lints/builds reject bad work

**Key principles:**

- Let Ralph Ralph (trust the loop)
- Specs drive everything
- Tests are your safety net
- The plan is disposable (regenerate anytime)

## Credits

Based on the Ralph Wiggum technique by [Geoffrey Huntley](https://ghuntley.com/ralph/).
