# Zsh completion for ralph
# Source this file from ~/.zshrc

_ralph_get_issues() {
  local plan="ralph/IMPLEMENTATION_PLAN.md"
  if [[ -f "$plan" ]]; then
    # First try explicit ISSUE-N tags
    local explicit=$(grep -oE 'ISSUE-[0-9]+' "$plan" 2>/dev/null | sort -u)
    if [[ -n "$explicit" ]]; then
      echo "$explicit"
    else
      # Count all bullets (including indented) in Discovered Issues section
      local count=$(sed -n '/## Discovered Issues/,/^## /p' "$plan" 2>/dev/null | grep -cE '^\s*- ' || echo 0)
      for i in $(seq 1 $count); do
        echo "ISSUE-$i"
      done
    fi
  fi
}

_ralph() {
  local -a subcommands
  subcommands=(
    'init:Initialize ralph in current repo'
    'plan:Run planning mode (generate implementation plan)'
    'build:Run build mode (implement from plan)'
    'status:Show current status and metrics'
    'watch:Live dashboard with metrics'
    'stream:Pretty-print opencode JSON stream'
    'investigate:Deep-dive on a specific blocker issue'
    'metrics:Show session metrics'
    'help:Show help'
  )

  local -a iterations
  iterations=(1 5 10 20 50 100)
  
  local -a cost_values
  cost_values=(5 10 25 50 100)
  
  local -a failure_values
  failure_values=(1 3 5 10)

  _arguments -C \
    '1: :->cmd' \
    '*: :->args' \
    '--max-cost[Stop when cost exceeds N dollars]:cost:($cost_values)' \
    '--max-failures[Circuit breaker - stop after N consecutive failures]:failures:($failure_values)' \
    '--completion-promise[Stop when output contains this text]:promise:(DONE COMPLETE FINISHED)' \
    '--no-ui[Disable interactive dashboard]' \
    && return

  case $state in
    cmd)
      _describe -t subcommands 'ralph command' subcommands
      _describe -t iterations 'iterations' iterations
      ;;
    args)
      case $words[2] in
        plan|build|"")
          _describe -t iterations 'iterations' iterations
          _arguments \
            '--max-cost[Stop when cost exceeds N dollars]:cost:($cost_values)' \
            '--max-failures[Circuit breaker]:failures:($failure_values)' \
            '--completion-promise[Stop on text]:promise:(DONE COMPLETE FINISHED)' \
            '--no-ui[Disable interactive dashboard]'
          ;;
        investigate)
          local -a issues
          issues=(${(f)"$(_ralph_get_issues)"})
          _describe -t issues 'issue ID' issues
          ;;
      esac
      ;;
  esac
}

compdef _ralph ralph
