#!/bin/bash
# collect-report.sh <experiment.conf> <profile>
#
# Gathers all telemetry, correctness checks, and git stats for one run.
# Called automatically by run-experiment.sh, but can be re-run manually.
#
# Outputs to: <results-dir>/<profile>/
#
# Usage:
#   bash bench/scripts/collect-report.sh 001-profile-showdown/experiment.conf hybrid

BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$BENCH_DIR/scripts/common.sh"

if [ $# -lt 2 ]; then
  echo "Usage: $0 <experiment.conf> <profile>"
  exit 1
fi

load_experiment_conf "$1"
PROFILE="$2"
WORKTREE="$(worktree_path "$PROFILE")"
REPORT="$(report_dir "$PROFILE")"

if [ ! -d "$WORKTREE" ]; then
  error "Worktree not found: $WORKTREE"
  exit 1
fi

mkdir -p "$REPORT"

header "Collecting report: $PROFILE"
info "Worktree: $WORKTREE"
info "Report:   $REPORT"
echo ""

# ── 1. Tix state ────────────────────────────────────────────────────
info "[1/7] Tix state..."
(cd "$WORKTREE" && tix report 2>/dev/null) > "$REPORT/tix-report.txt" 2>&1 || echo "UNAVAILABLE" > "$REPORT/tix-report.txt"
(cd "$WORKTREE" && tix query full 2>/dev/null) > "$REPORT/tix-full.json" 2>&1 || echo "{}" > "$REPORT/tix-full.json"

# ── 2. Git stats ────────────────────────────────────────────────────
info "[2/7] Git stats..."
(cd "$WORKTREE" && git log --oneline "$BASE_REF..HEAD" 2>/dev/null) > "$REPORT/git-log.txt" || true
(cd "$WORKTREE" && git diff --stat "$BASE_REF..HEAD" 2>/dev/null) > "$REPORT/git-diffstat.txt" || true
(cd "$WORKTREE" && git diff "$BASE_REF..HEAD" --shortstat 2>/dev/null) > "$REPORT/git-shortstat.txt" || true
COMMITS=$(wc -l < "$REPORT/git-log.txt" 2>/dev/null || echo 0)
info "  Commits since $BASE_REF: $COMMITS"

# ── 3. Build ────────────────────────────────────────────────────────
info "[3/7] Build check ($BUILD_CMD)..."
BUILD_EXIT=0
(cd "$WORKTREE" && eval "$BUILD_CMD" 2>&1) > "$REPORT/build.log" || BUILD_EXIT=$?
echo "$BUILD_EXIT" > "$REPORT/build-exit.txt"
[ "$BUILD_EXIT" = "0" ] && success "  Build: PASS" || warn "  Build: FAIL (exit $BUILD_EXIT)"

# ── 4. Tests ────────────────────────────────────────────────────────
info "[4/7] Test check ($TEST_CMD, ${TEST_TIMEOUT}s timeout)..."
TEST_EXIT=0
(cd "$WORKTREE" && timeout "$TEST_TIMEOUT" bash -c "$TEST_CMD" 2>&1) > "$REPORT/test.log" || TEST_EXIT=$?
echo "$TEST_EXIT" > "$REPORT/test-exit.txt"
[ "$TEST_EXIT" = "0" ] && success "  Tests: PASS" || warn "  Tests: FAIL (exit $TEST_EXIT)"

# ── 5. Custom gate checks ──────────────────────────────────────────
info "[5/7] Gate checks..."
if [ -n "$GATE_CHECKS" ]; then
  IFS='|' read -r gate_label gate_cmd <<< "$GATE_CHECKS"
  GATE_EXIT=0
  (cd "$WORKTREE" && eval "$gate_cmd" 2>&1) > "$REPORT/gate-${gate_label}.log" || GATE_EXIT=$?
  echo "$GATE_EXIT" > "$REPORT/gate-${gate_label}-exit.txt"
  [ "$GATE_EXIT" = "0" ] && success "  $gate_label: PASS" || warn "  $gate_label: FAIL (exit $GATE_EXIT)"
else
  info "  No custom gate checks configured."
fi

# ── 6. Ralph session summaries ──────────────────────────────────────
info "[6/7] Session summaries..."
if ls "$RALPH_LOG_DIR"/session_*.json >/dev/null 2>&1; then
  cp "$RALPH_LOG_DIR"/session_*.json "$REPORT/" 2>/dev/null
  success "  Copied session summaries"
else
  info "  No session summaries found in $RALPH_LOG_DIR"
fi

# ── 7. Ralph orchestrator state ─────────────────────────────────────
info "[7/7] Ralph state..."
(cd "$WORKTREE" && cat .tix/ralph-state.json 2>/dev/null) > "$REPORT/ralph-state.json" || echo "{}" > "$REPORT/ralph-state.json"

# ── 8. Copy ledger snapshot ────────────────────────────────────────
info "Snapshotting ledger..."
mkdir -p "$RESULTS_DIR/_ledger"
cp "$RALPH_LOG_DIR/runs.jsonl" "$RESULTS_DIR/_ledger/" 2>/dev/null || true
cp "$RALPH_LOG_DIR/iterations.jsonl" "$RESULTS_DIR/_ledger/" 2>/dev/null || true

echo ""
success "Report saved to $REPORT"
