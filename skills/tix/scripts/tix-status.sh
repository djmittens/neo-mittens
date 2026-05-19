#!/usr/bin/env bash
# tix-status.sh -- Show tix status for the current repository.
# Reports: task counts, pending tasks, open issues, current branch.
#
# Usage: bash tix-status.sh
# Output: JSON on stdout, diagnostics on stderr.

set -euo pipefail

json_error() {
    echo "{\"error\": \"$1\"}"
    exit 1
}

# Check if tix is available
if ! command -v tix &>/dev/null; then
    json_error "tix not found in PATH. Run bootstrap.sh or: cd app/tix && make build"
fi

# Check if initialized
if [ ! -d ".tix" ]; then
    json_error "tix not initialized. Run tix init first."
fi

# Run tix query for full state
query_output=$(tix query 2>/dev/null) || json_error "tix query failed"

# Extract fields via python (portable JSON parsing)
extract() {
    echo "$query_output" | python3 -c "
import json, sys
d = json.load(sys.stdin)
$1
" 2>/dev/null
}

branch=$(extract "print(d.get('meta',{}).get('branch','unknown'))")
commit=$(extract "print(d.get('meta',{}).get('commit','unknown'))")
pending_count=$(extract "print(len(d.get('tasks',{}).get('pending',[])))")
done_count=$(extract "print(len(d.get('tasks',{}).get('done',[])))")
issue_count=$(extract "print(len(d.get('issues',[])))")
note_count=$(extract "print(len(d.get('notes',[])))")

# Get pending tasks (up to 10)
pending_tasks=$(extract "
import json as j
tasks = d.get('tasks',{}).get('pending',[])[:10]
out = []
for t in tasks:
    out.append({'id': t.get('id',''), 'name': t.get('name',''), 'priority': t.get('priority','none')})
print(j.dumps(out))
")

# Get open issues (up to 5)
open_issues=$(extract "
import json as j
issues = d.get('issues',[])[:5]
out = []
for i in issues:
    out.append({'id': i.get('id',''), 'name': i.get('name','')})
print(j.dumps(out))
")

cat <<EOF
{
  "branch": "$branch",
  "commit": "$commit",
  "tasks_pending": $pending_count,
  "tasks_done": $done_count,
  "issues": $issue_count,
  "notes": $note_count,
  "pending_tasks": $pending_tasks,
  "open_issues": $open_issues
}
EOF
