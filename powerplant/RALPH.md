# Ralph Wiggum - Autonomous AI Development

Ralph is a bash loop that runs Claude Code autonomously until tasks are complete.
Named after Ralph Wiggum from The Simpsons - perpetually confused, always making 
mistakes, but never stopping.

> "Ralph is a Bash loop" - Geoffrey Huntley

## Requirements

- Python 3.10+
- [opencode](https://github.com/sst/opencode) - Claude Code CLI

**Optional (for enhanced TUI):**

```bash
# Arch Linux
sudo pacman -S python-textual

# macOS / other Linux (via pip)
pip3 install textual
```

Without textual, `ralph watch` uses a simpler but fully functional dashboard.

## Quick Start

```bash
# Initialize ralph in your repo
cd your-project
ralph init

# Write specs describing what you want to build
vim ralph/specs/my-feature.md

# Generate implementation plan from a spec
ralph plan my-feature.md

# Let ralph build it
ralph 10  # Run 10 iterations

# Or with safety limits
ralph 50 --max-cost 25  # Stop at 50 iterations or $25
ralph --completion-promise "ALL TESTS PASSING"  # Stop when done
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
│              ralph plan <spec.md>                            │
│                                                              │
│  • Reads the specified spec                                  │
│  • Analyzes existing code                                    │
│  • Creates tasks in plan.jsonl                               │
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
│  │  1. Read plan.jsonl                                  │    │
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
# Core commands
ralph init               # Initialize ralph in current repo
ralph plan <spec.md>     # Generate tasks from a spec file
ralph construct          # Construct mode, unlimited iterations
ralph construct 10       # Construct mode, max 10 iterations
ralph 10                 # Same as above (shorthand)

# State management
ralph config             # Show global config (model, timeouts, etc.)
ralph status             # Show current status
ralph query              # Show current state as JSON
ralph query stage        # Show current stage (PLAN/BUILD/VERIFY/etc)
ralph task done          # Mark first pending task as done
ralph task add "desc"    # Add a new task
ralph task accept        # Accept all done tasks
ralph issue add "desc"   # Add a discovered issue
ralph issue done         # Resolve first issue
ralph set-spec <spec.md> # Set current spec file

# Monitoring
ralph watch              # Live dashboard with cost tracking
ralph log                # Show state change history
ralph stream             # Pipe opencode JSON for pretty output

# Maintenance
ralph validate           # Check plan.jsonl for issues
ralph compact            # Convert legacy tasks to tombstones
```

## Options

```bash
--profile, -p PROFILE   # Cost profile: budget, balanced, hybrid, cost_smart
--max-cost N            # Stop when cumulative cost exceeds $N
--max-failures N        # Circuit breaker: stop after N consecutive failures (default: 3)
--timeout N             # Kill stage after N milliseconds (default: 900000)
--context-limit N       # Context window size in tokens (default: 200000)
--completion-promise T  # Stop when output contains text T
--no-ui                 # Disable interactive dashboard
```

**Examples:**

```bash
ralph 50 --max-cost 25              # Max 50 iterations or $25, whichever first
ralph --max-cost 10                 # Unlimited iterations, stop at $10
ralph --completion-promise "DONE"   # Stop when DONE appears in output
ralph 100 --max-failures 5          # Allow up to 5 consecutive failures
ralph -p budget 50                  # Use budget profile, 50 iterations
```

**Iteration limits:** The number after `ralph` or `ralph construct` sets how many
iterations to run before stopping. Default is **unlimited** (runs until Ctrl+C
or no tasks remain). Use limits for unattended runs (e.g., `ralph 50` overnight).

**Planning vs Construct:**
- `ralph plan <spec.md>` - Analyzes spec and code, creates tasks in plan.jsonl. Does NOT write code.
- `ralph` / `ralph construct` - Implements tasks from the plan, one per iteration.

## Directory Structure

After `ralph init`, your repo will have:

```
your-project/
├── ralph/
│   ├── PROMPT_plan.md          # Planning mode instructions
│   ├── PROMPT_build.md         # Build mode instructions
│   ├── PROMPT_verify.md        # Verify stage instructions
│   ├── PROMPT_investigate.md   # Investigate stage instructions
│   ├── PROMPT_decompose.md     # Decompose stage instructions
│   ├── plan.jsonl              # Auto-managed task list (JSONL format)
│   └── specs/
│       └── *.md                # Your requirement specs
└── ... your code ...

# Logs are stored in /tmp/ralph-logs/<repo>/<branch>/<spec>/
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
# Live dashboard with cost tracking
ralph watch

# Show state change history  
ralph log
ralph log --all              # Show full history
ralph log --spec my-feature  # Filter by spec

# Check current state
ralph status
ralph query stage            # Current stage (PLAN/BUILD/VERIFY/etc)
ralph query tasks            # List all tasks

# Check commits
git log --oneline -10
```

## Cost Tracking

During a run, `ralph watch` shows live cost information parsed from the output stream.
Cost resets each session (each `ralph` invocation).

## Safety

Ralph uses `--dangerously-skip-permissions` to run autonomously.

**Built-in Safety Features:**

1. **Cost limits** - Use `--max-cost N` to cap spending at $N
2. **Circuit breaker** - Stops after N consecutive failures (default: 3)
3. **Iteration limits** - Use `ralph N` to cap iterations
4. **Completion detection** - Use `--completion-promise` to stop on success
5. **Context limits** - Stages are killed at 95% context usage, compacted at 85%
6. **Timeouts** - Stages are killed after timeout (default: 15 minutes)

**Recommendations:**
- Run in a sandboxed environment for untrusted code
- Use a separate git branch
- Review commits before merging to main
- Set reasonable iteration AND cost limits for unattended runs
- Example overnight run: `ralph 100 --max-cost 50 --max-failures 5`

**Recovery:**
- `Ctrl+C` stops the loop
- `git reset --hard HEAD~N` undoes N commits
- Re-run `ralph plan <spec.md>` to regenerate tasks if stuck

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

Run `ralph plan <spec.md>` again whenever:
- You update the spec
- The plan feels stale or wrong
- Ralph seems stuck

**The plan is disposable.** Planning does a fresh gap analysis of spec vs current
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


