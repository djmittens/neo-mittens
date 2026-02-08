#!/bin/bash
# run-experiment.sh <experiment.conf> <profile>
#
# Runs a single ralph construct session for the given profile.
# Logs output to results/<profile>/console.log.
# Auto-collects telemetry on completion via collect-report.sh.
#
# Usage:
#   bash bench/scripts/run-experiment.sh 001-profile-showdown/experiment.conf hybrid

BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$BENCH_DIR/scripts/common.sh"

if [ $# -lt 2 ]; then
  echo "Usage: $0 <experiment.conf> <profile>"
  echo ""
  echo "Run a single ralph construct experiment."
  echo "The profile must be listed in the experiment.conf PROFILES variable"
  echo "and have a worktree set up via setup-worktrees.sh."
  exit 1
fi

load_experiment_conf "$1"
PROFILE="$2"

# Validate profile is in the experiment
found=false
for p in $PROFILES; do
  [ "$p" = "$PROFILE" ] && found=true
done
if [ "$found" = "false" ]; then
  error "Profile '$PROFILE' is not in PROFILES ($PROFILES)"
  exit 1
fi

WORKTREE="$(worktree_path "$PROFILE")"
REPORT="$(report_dir "$PROFILE")"

if [ ! -d "$WORKTREE" ]; then
  error "Worktree not found: $WORKTREE"
  error "Run setup-worktrees.sh first."
  exit 1
fi

mkdir -p "$REPORT"

separator
header "RALPH EXPERIMENT: $PROFILE"
separator
info "Experiment:     $(basename "$EXP_DIR")"
info "Worktree:       $WORKTREE"
info "Spec:           $SPEC"
info "Max iterations: $MAX_ITERATIONS"
info "Max wall time:  ${MAX_WALL_TIME}s ($((MAX_WALL_TIME / 60))min)"
info "Max failures:   $MAX_FAILURES"
info "Profile:        $PROFILE"
info "Started:        $(date -Iseconds)"
separator
echo ""

# Record experiment metadata
cat > "$REPORT/experiment-meta.json" << METAEOF
{
  "experiment": "$(basename "$EXP_DIR")",
  "profile": "$PROFILE",
  "target_repo": "$TARGET_REPO",
  "base_ref": "$BASE_REF",
  "spec": "$SPEC",
  "max_iterations": $MAX_ITERATIONS,
  "max_wall_time": $MAX_WALL_TIME,
  "max_failures": $MAX_FAILURES,
  "worktree": "$WORKTREE",
  "started_at": "$(date -Iseconds)",
  "hostname": "$(hostname)",
  "cpu": "$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | xargs || echo unknown)",
  "ram_gb": $(free -g 2>/dev/null | awk '/Mem:/{print $2}' || echo 0),
  "gpu": "$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo none)"
}
METAEOF

# Run ralph construct
cd "$WORKTREE"

EXIT_CODE=0
RALPH_PROFILE="$PROFILE" ralph2 construct --spec "$SPEC" \
  --max-iterations "$MAX_ITERATIONS" \
  --max-wall-time "$MAX_WALL_TIME" \
  --max-failures "$MAX_FAILURES" \
  2>&1 | tee "$REPORT/console.log" || EXIT_CODE=${PIPESTATUS[0]}

# Record end time
python3 -c "
import json, datetime
with open('$REPORT/experiment-meta.json') as f:
    meta = json.load(f)
meta['ended_at'] = datetime.datetime.now().isoformat()
meta['exit_code'] = $EXIT_CODE
with open('$REPORT/experiment-meta.json', 'w') as f:
    json.dump(meta, f, indent=2)
"

echo ""
separator
header "EXPERIMENT COMPLETE: $PROFILE"
separator
info "Exit code: $EXIT_CODE"
info "Ended:     $(date -Iseconds)"
separator
echo ""

# Auto-collect report
header "Collecting post-run report..."
bash "$BENCH_DIR/scripts/collect-report.sh" "$EXP_CONF" "$PROFILE"
