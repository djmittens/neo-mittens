# Experiment 001: Profile Showdown

## Question

Which ralph profile combination yields the best autonomous results for
a complex, multi-phase C systems refactoring spec, given:

- A Claude Max subscription (quota-limited, not dollar-limited)
- A local Devstral model on an RTX 5090 (96K context, zero quota cost)
- The need to run unattended overnight with full guardrails

## Hypothesis

The **hybrid** profile (Opus reasoning + local Devstral BUILD) will achieve
the best efficiency score because:

1. Reasoning stages (PLAN, INVESTIGATE, VERIFY, DECOMPOSE) benefit most
   from Opus-class intelligence -- they make architectural decisions.
2. BUILD is the highest-volume stage and mostly applies well-specified
   changes. A local model can handle it with zero quota burn.
3. The quota savings from local BUILD let you run more iterations before
   hitting Max plan limits.

The **opus** profile will complete the most tasks (quality ceiling) but burn
quota fastest. The **devstral** profile will likely stall on complex phases
that require understanding C threading primitives and GC internals.

## Target

- **Project**: Valkyria -- a Lisp interpreter in C with GC, async I/O, HTTP/2
- **Spec**: `system-architecture-refactor.md` (1230 lines, 9 phases)
  - Phase 0: Mechanical rename of ~90 symbols across ~30 files
  - Phases 1-7: Architectural refactor (new struct, STW protocol, AIO integration)
  - Phase 8-9: Cleanup and verification
- **Base**: tag `ralph-experiment-refactor-spec` (commit `534d11f` on `networking`)
- **Machine**: redbox (Ryzen 9 9900X 12C/24T, 64GB RAM, RTX 5090 32GB)

## Profiles Under Test

| Profile | Reasoning Model | BUILD Model | Expected Quota |
|---------|----------------|-------------|----------------|
| `hybrid` | Opus 4.6 (cloud) | Devstral (local) | Low |
| `opus` | Opus 4.6 (cloud) | Opus 4.6 (cloud) | Highest |
| `sonnet` | Sonnet 4.5 (cloud) | Sonnet 4.5 (cloud) | Medium |
| `opus-sonnet` | Opus 4.6 (cloud) | Sonnet 4.5 (cloud) | Medium-High |
| `sonnet-hybrid` | Sonnet 4.5 (cloud) | Devstral (local) | Low |
| `devstral` | Devstral (local) | Devstral (local) | Zero |

All profiles defined in `~/.config/ralph/config.toml`.

## Parameters

- **Max iterations**: 25 per run
- **Max wall time**: 2 hours per run
- **Max consecutive failures**: 3 (circuit breaker)
- **Stage timeout**: 15 minutes (from config default)
- **Context kill threshold**: 95% (from config default)

## What Gets Measured

All metrics are captured automatically by Ralph's telemetry system. No
manual instrumentation needed.

### Primary Metrics (from `runs.jsonl`)

| Metric | Why |
|--------|-----|
| Tasks completed / total | **Main outcome** -- did it make progress? |
| Exit reason | Did it finish, stall, or break? |
| Total iterations | How much work did it attempt? |
| Wall-clock duration | Real-world time cost |
| Remote API calls | Quota pressure on Max plan |
| Local API calls | Free computation used |
| Kill counts (timeout/context/loop) | Failure mode distribution |

### Per-Iteration Metrics (from `iterations.jsonl`)

| Metric | Why |
|--------|-----|
| Stage + outcome per iteration | Where does each profile spend time? |
| Cost + tokens per iteration | Granular cost attribution |
| Precheck acceptance rate | How often does auto-verify skip the agent? |
| Validation retries | Output quality signal per model |
| Kill reasons | Which stages cause kills for which profiles? |

### Correctness Metrics (from collect-report.sh)

| Metric | Why |
|--------|-----|
| `make build` pass/fail | Did the code changes compile? |
| `make test` pass/fail | Did existing tests break? |
| Phase 0 gate (old symbols) | Did the rename phase complete cleanly? |
| Commits + lines changed | Productivity proxy |

### Derived Metrics (from analyze.py)

| Metric | Formula |
|--------|---------|
| Completion rate | completed / total |
| Efficiency score | rate / (0.3 * norm_cost + 0.3 * norm_time + 0.01) |
| Quota efficiency | tasks completed per remote API call |
| Local offload % | local API calls / total API calls |

## Execution Plan

### Prerequisites

1. llama-server running with Devstral for local model profiles:
   ```bash
   llama-server -m /path/to/devstral-small-2.gguf \
     --ctx-size 98304 --flash-attn --port 8080 -ngl 99
   ```

2. opencode configured and authenticated with Claude Max subscription.

3. tix built and in PATH:
   ```bash
   cd ~/src/neo-mittens/app/tix && make build
   ```

### Step 1: Setup Worktrees

```bash
cd ~/src/neo-mittens/ralph/experiments
bash bench/scripts/setup-worktrees.sh 001-profile-showdown/experiment.conf
```

This creates 6 isolated worktrees under `~/src/valkyria-experiments/`.

### Step 2: Generate the Plan

Run plan generation once from any worktree, then propagate:

```bash
cd ~/src/valkyria-experiments/hybrid-run1
RALPH_PROFILE=opus ralph2 plan system-architecture-refactor.md

# Commit the plan
git add .tix/ ralph/
git commit -m "ralph: generate plan for profile showdown experiment"
PLAN_SHA=$(git rev-parse HEAD)

# Propagate to all other worktrees
for profile in opus sonnet opus-sonnet sonnet-hybrid devstral; do
  (cd ~/src/valkyria-experiments/${profile}-run1 && git cherry-pick $PLAN_SHA)
done
```

### Step 3: Run Experiments

Run one cloud-model experiment at a time to avoid Claude Max session limits.
Local-only runs can overlap with a cloud run.

```bash
cd ~/src/neo-mittens/ralph/experiments
CONF="001-profile-showdown/experiment.conf"

# Round 1: baseline + quality floor (can run in parallel)
bash bench/scripts/run-experiment.sh $CONF hybrid &
bash bench/scripts/run-experiment.sh $CONF devstral &
wait

# Round 2: quality ceiling
bash bench/scripts/run-experiment.sh $CONF opus

# Round 3
bash bench/scripts/run-experiment.sh $CONF sonnet

# Round 4
bash bench/scripts/run-experiment.sh $CONF opus-sonnet

# Round 5
bash bench/scripts/run-experiment.sh $CONF sonnet-hybrid
```

Or run them sequentially in a tmux session overnight:

```bash
cd ~/src/neo-mittens/ralph/experiments
CONF="001-profile-showdown/experiment.conf"
for profile in hybrid devstral opus sonnet opus-sonnet sonnet-hybrid; do
  echo "=== Starting $profile at $(date) ==="
  bash bench/scripts/run-experiment.sh $CONF $profile
  echo "=== Finished $profile at $(date) ==="
  sleep 30  # breathing room between runs
done
```

### Step 4: Analyze

```bash
cd ~/src/neo-mittens/ralph/experiments
python3 bench/scripts/analyze.py 001-profile-showdown/experiment.conf
```

For JSON output (pipe to jq, store, etc.):
```bash
python3 bench/scripts/analyze.py 001-profile-showdown/experiment.conf --json > results.json
```

Filter to one profile:
```bash
python3 bench/scripts/analyze.py 001-profile-showdown/experiment.conf --profile hybrid
```

### Step 5: Inspect Failures

If a run underperformed, debug it:

```bash
# Check what happened
cd ~/src/valkyria-experiments/<profile>-run1
tix report
tix query full | python3 -c "
import sys, json
d = json.load(sys.stdin)
for t in d.get('tombstones', {}).get('rejected', []):
    print(f\"{t['id']}: {t.get('reason', '?')[:80]}\")
"

# Check git diff for what was actually produced
git diff ralph-experiment-refactor-spec..HEAD --stat
git log --oneline ralph-experiment-refactor-spec..HEAD

# Read stage logs
ls -lt /tmp/ralph-logs/ralph-*-build.log | head -5
```

## Expected Timeline

| Phase | Duration | Notes |
|-------|----------|-------|
| Setup (worktrees + plan) | ~20 min | One-time, manual |
| hybrid run | ~1-2 hr | Can overlap with devstral |
| devstral run | ~1-2 hr | Local only, can overlap |
| opus run | ~1-2 hr | Cloud only, sequential |
| sonnet run | ~1-2 hr | Cloud only, sequential |
| opus-sonnet run | ~1-2 hr | Cloud only, sequential |
| sonnet-hybrid run | ~1-2 hr | Cloud + local |
| Analysis | ~5 min | Automated |
| **Total** | **~8-12 hr** | Overnight unattended |

## Cleanup

After analysis:

```bash
# Remove worktrees (keeps branches for re-inspection)
for profile in hybrid opus sonnet opus-sonnet sonnet-hybrid devstral; do
  git -C ~/src/valkyria worktree remove \
    "$HOME/src/valkyria-experiments/${profile}-run1" --force 2>/dev/null
done

# Delete experiment branches (when fully done)
for profile in hybrid opus sonnet opus-sonnet sonnet-hybrid devstral; do
  git -C ~/src/valkyria branch -D \
    "exp/001-profile-showdown/${profile}" 2>/dev/null
done
```

## Follow-Up Experiments

Based on the winner from this experiment:

| Experiment | What to Vary | Goal |
|------------|-------------|------|
| 002-timeout-tuning | `stage_timeout_ms` (5/10/15 min) | Find optimal timeout |
| 003-context-pressure | `context_compact_pct` (70/80/90%) | Find compaction sweet spot |
| 004-batch-sizes | `verify_batch_size`, `investigate_batch_size` | Throughput tuning |
| 005-decompose-depth | `max_decompose_depth` (2/3/4) | Recovery vs waste tradeoff |
| 006-cross-machine | Same profile on obelisk (3080Ti) vs redbox (5090) | Hardware scaling |
| 007-spec-complexity | Same profile on simpler spec (deprecate-atoms.md) | Does optimal profile depend on spec? |
| 008-haiku-build | Add haiku-4 as BUILD model | Cheapest cloud BUILD |
