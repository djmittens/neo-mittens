#!/bin/bash
# setup-worktrees.sh <experiment.conf>
#
# Creates one isolated git worktree per profile, all branched from BASE_REF
# (a tag, branch, or commit). Safe to re-run: skips worktrees that already exist.
#
# Usage:
#   bash bench/scripts/setup-worktrees.sh 001-profile-showdown/experiment.conf

BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$BENCH_DIR/scripts/common.sh"

if [ $# -lt 1 ]; then
  echo "Usage: $0 <experiment.conf>"
  echo "Example: $0 001-profile-showdown/experiment.conf"
  exit 1
fi

load_experiment_conf "$1"

separator
header "SETUP WORKTREES"
separator
info "Target repo:  $TARGET_REPO"
info "Base ref:     $BASE_REF"
info "Spec:         $SPEC"
info "Worktree dir: $WORKTREE_BASE"
info "Profiles:     $PROFILES"
echo ""

mkdir -p "$WORKTREE_BASE"

# Verify base ref exists in target repo
if ! git -C "$TARGET_REPO" rev-parse --verify "$BASE_REF" >/dev/null 2>&1; then
  error "BASE_REF '$BASE_REF' does not exist in $TARGET_REPO"
  exit 1
fi

# Verify spec exists
if [ ! -f "$TARGET_REPO/ralph/specs/$SPEC" ]; then
  warn "Spec file not found at $TARGET_REPO/ralph/specs/$SPEC"
  warn "Ralph may fail to find the spec. Proceeding anyway."
fi

created=0
skipped=0

for profile in $PROFILES; do
  branch="$(branch_name "$profile")"
  worktree="$(worktree_path "$profile")"

  if [ -d "$worktree" ]; then
    info "SKIP  $profile (already exists: $worktree)"
    skipped=$((skipped + 1))
    continue
  fi

  git -C "$TARGET_REPO" worktree add -b "$branch" "$worktree" "$BASE_REF" 2>&1
  success "OK    $profile -> $worktree (branch: $branch)"
  created=$((created + 1))
done

echo ""
separator
header "WORKTREE SUMMARY"
separator
info "Created: $created"
info "Skipped: $skipped"
echo ""
git -C "$TARGET_REPO" worktree list
echo ""

header "NEXT STEPS"
info "1. Generate the plan (once, from any worktree):"
info "     cd $(worktree_path "$(echo $PROFILES | awk '{print $1}')")"
info "     RALPH_PROFILE=opus ralph2 plan $SPEC"
info "     git add .tix/ ralph/ && git commit -m 'ralph: plan for experiment'"
info ""
info "2. Cherry-pick the plan commit into each other worktree:"
info "     for p in $PROFILES; do"
info "       (cd \$(worktree_path \$p) && git cherry-pick <plan-commit-sha>)"
info "     done"
info ""
info "3. Run experiments:"
info "     bash $BENCH_DIR/scripts/run-experiment.sh $EXP_CONF <profile>"
