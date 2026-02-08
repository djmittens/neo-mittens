#!/bin/bash
# common.sh - Shared functions for the ralph experiment framework.
#
# Sourced by other scripts. Do not run directly.
# Usage in scripts:
#   BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
#   source "$BENCH_DIR/scripts/common.sh"

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────
# Colors (disabled if not a tty)
# ─────────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
  BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
  RED=''; GREEN=''; YELLOW=''; BLUE=''; CYAN=''; BOLD=''; NC=''
fi

# ─────────────────────────────────────────────────────────────────────
# load_experiment_conf <path-to-experiment.conf>
#
# Sources the conf, computes defaults, validates required fields.
# Sets all the EXP_* variables that other functions use.
# ─────────────────────────────────────────────────────────────────────
load_experiment_conf() {
  local conf_path="$1"

  if [ ! -f "$conf_path" ]; then
    echo -e "${RED}ERROR: experiment.conf not found: $conf_path${NC}" >&2
    exit 1
  fi

  # Resolve experiment directory (where the .conf lives)
  EXP_DIR="$(cd "$(dirname "$conf_path")" && pwd)"
  EXP_CONF="$(cd "$(dirname "$conf_path")" && pwd)/$(basename "$conf_path")"

  # Source the config
  # shellcheck disable=SC1090
  source "$conf_path"

  # Validate required fields
  for var in TARGET_REPO BASE_REF SPEC PROFILES; do
    if [ -z "${!var:-}" ]; then
      echo -e "${RED}ERROR: $var is required in $conf_path${NC}" >&2
      exit 1
    fi
  done

  if [ ! -d "$TARGET_REPO" ]; then
    echo -e "${RED}ERROR: TARGET_REPO does not exist: $TARGET_REPO${NC}" >&2
    exit 1
  fi

  # Compute defaults
  local repo_name
  repo_name="$(basename "$TARGET_REPO")"

  WORKTREE_BASE="${WORKTREE_BASE:-$HOME/src/${repo_name}-experiments}"
  RALPH_LOG_DIR="${RALPH_LOG_DIR:-/tmp/ralph-logs}"
  RESULTS_DIR="${RESULTS_DIR:-$EXP_DIR/results}"
  MAX_ITERATIONS="${MAX_ITERATIONS:-25}"
  MAX_WALL_TIME="${MAX_WALL_TIME:-7200}"
  MAX_FAILURES="${MAX_FAILURES:-3}"
  BUILD_CMD="${BUILD_CMD:-make build}"
  TEST_CMD="${TEST_CMD:-make test}"
  TEST_TIMEOUT="${TEST_TIMEOUT:-300}"
  GATE_CHECKS="${GATE_CHECKS:-}"

  # Export for child processes
  export TARGET_REPO BASE_REF SPEC PROFILES
  export WORKTREE_BASE RALPH_LOG_DIR RESULTS_DIR
  export MAX_ITERATIONS MAX_WALL_TIME MAX_FAILURES
  export BUILD_CMD TEST_CMD TEST_TIMEOUT GATE_CHECKS
  export EXP_DIR EXP_CONF
}

# ─────────────────────────────────────────────────────────────────────
# worktree_path <profile>
# Returns the worktree directory path for a given profile.
# ─────────────────────────────────────────────────────────────────────
worktree_path() {
  echo "${WORKTREE_BASE}/${1}-run1"
}

# ─────────────────────────────────────────────────────────────────────
# branch_name <profile>
# Returns the experiment branch name for a given profile.
# ─────────────────────────────────────────────────────────────────────
branch_name() {
  local exp_name
  exp_name="$(basename "$EXP_DIR")"
  echo "exp/${exp_name}/${1}"
}

# ─────────────────────────────────────────────────────────────────────
# report_dir <profile>
# Returns the report output directory for a given profile.
# ─────────────────────────────────────────────────────────────────────
report_dir() {
  echo "${RESULTS_DIR}/${1}"
}

# ─────────────────────────────────────────────────────────────────────
# header / separator / info / warn / error / success
# ─────────────────────────────────────────────────────────────────────
header()    { echo -e "\n${BOLD}${BLUE}$*${NC}"; }
separator() { echo -e "${BLUE}$(printf '%.0s━' {1..70})${NC}"; }
info()      { echo -e "  ${CYAN}$*${NC}"; }
warn()      { echo -e "  ${YELLOW}WARN: $*${NC}"; }
error()     { echo -e "  ${RED}ERROR: $*${NC}" >&2; }
success()   { echo -e "  ${GREEN}$*${NC}"; }

# ─────────────────────────────────────────────────────────────────────
# profiles_array
# Splits PROFILES string into a bash array.
# ─────────────────────────────────────────────────────────────────────
profiles_array() {
  # shellcheck disable=SC2206
  local arr=($PROFILES)
  echo "${arr[@]}"
}
