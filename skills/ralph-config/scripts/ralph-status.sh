#!/usr/bin/env bash
# ralph-status.sh -- Show Ralph status for the current repository.
# Reports: initialization state, spec count, task counts, latest log.
#
# Usage: bash ralph-status.sh
# Output: JSON on stdout, diagnostics on stderr.

set -euo pipefail

json_error() {
    echo "{\"error\": \"$1\"}"
    exit 1
}

RALPH_DIR="ralph"
SPECS_DIR="$RALPH_DIR/specs"
STATE_FILE=".tix/ralph-state.json"
LOGS_DIR="build/ralph-logs"

# Check if initialized
if [ ! -d "$RALPH_DIR" ]; then
    json_error "Ralph not initialized. Run ralph init first."
fi

# Count specs
spec_count=0
if [ -d "$SPECS_DIR" ]; then
    spec_count=$(find "$SPECS_DIR" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
fi

# Read orchestration state
stage="PLAN"
spec="null"
if [ -f "$STATE_FILE" ]; then
    stage_val=$(python3 -c "import json,sys; d=json.load(open('$STATE_FILE')); print(d.get('stage','PLAN'))" 2>/dev/null || echo "PLAN")
    spec_val=$(python3 -c "import json,sys; d=json.load(open('$STATE_FILE')); print(d.get('spec',''))" 2>/dev/null || echo "")
    stage="$stage_val"
    if [ -n "$spec_val" ]; then
        spec="\"$spec_val\""
    fi
fi

# Get ticket counts from tix CLI
pending=0
done_count=0
issues=0
tix_available=true
if command -v tix &>/dev/null && [ -d ".tix" ]; then
    if query_output=$(tix query 2>/dev/null); then
        pending=$(echo "$query_output" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('tasks',{}).get('pending',[])))" 2>/dev/null || echo 0)
        done_count=$(echo "$query_output" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('tasks',{}).get('done',[])))" 2>/dev/null || echo 0)
        issues=$(echo "$query_output" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('issues',[])))" 2>/dev/null || echo 0)
    else
        tix_available=false
        echo "tix query failed" >&2
    fi
else
    tix_available=false
fi

# Find latest log
latest_log="null"
if [ -d "$LOGS_DIR" ]; then
    log_file=$(ls -t "$LOGS_DIR"/ralph-*.log 2>/dev/null | head -1 || true)
    if [ -n "$log_file" ]; then
        latest_log="\"$log_file\""
    fi
fi

# Output JSON
cat <<EOF
{
  "initialized": true,
  "specs": $spec_count,
  "stage": "$stage",
  "current_spec": $spec,
  "tasks_pending": $pending,
  "tasks_done": $done_count,
  "issues": $issues,
  "tix_available": $tix_available,
  "latest_log": $latest_log
}
EOF
