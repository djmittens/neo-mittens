# Zsh completion for ralph
# Source this file from ~/.zshrc

_ralph_get_specs() {
  if [[ -d "ralph/specs" ]]; then
    ls ralph/specs/*.md 2>/dev/null | xargs -n1 basename 2>/dev/null
  fi
}

_ralph() {
  local -a subcommands
  subcommands=(
    'init:Initialize ralph in current repo'
    'plan:Run planning mode for a spec file'
    'build:Run build mode (implement from plan)'
    'status:Show current status'
    'watch:Live dashboard with metrics'
    'stream:Pretty-print opencode JSON stream'
    'query:Query current state (stage, next, tasks, issues)'
    'task:Task mutations (done, add, accept)'
    'issue:Issue mutations (done, add)'
    'set-spec:Set current spec file'
    'log:Query git history for state changes'
    'help:Show help'
  )

  local -a iterations
  iterations=(1 5 10 20 50 100)
  
  local -a cost_values
  cost_values=(5 10 25 50 100)
  
  local -a failure_values
  failure_values=(1 3 5 10)

  local -a query_subcommands
  query_subcommands=(stage next tasks issues)

  local -a task_subcommands
  task_subcommands=(done add accept)

  local -a issue_subcommands
  issue_subcommands=(done add)

  _arguments -C \
    '1: :->cmd' \
    '*: :->args' \
    '--max-cost[Stop when cost exceeds N dollars]:cost:($cost_values)' \
    '--max-failures[Circuit breaker - stop after N consecutive failures]:failures:($failure_values)' \
    '--completion-promise[Stop when output contains this text]:promise:(DONE COMPLETE FINISHED SPEC_COMPLETE)' \
    '--no-ui[Disable interactive dashboard]' \
    && return

  case $state in
    cmd)
      _describe -t subcommands 'ralph command' subcommands
      _describe -t iterations 'iterations' iterations
      ;;
    args)
      case $words[2] in
        plan|set-spec)
          local -a specs
          specs=(${(f)"$(_ralph_get_specs)"})
          _describe -t specs 'spec file' specs
          ;;
        build|"")
          _describe -t iterations 'iterations' iterations
          _arguments \
            '--max-cost[Stop when cost exceeds N dollars]:cost:($cost_values)' \
            '--max-failures[Circuit breaker]:failures:($failure_values)' \
            '--completion-promise[Stop on text]:promise:(DONE COMPLETE FINISHED SPEC_COMPLETE)' \
            '--no-ui[Disable interactive dashboard]'
          ;;
        query)
          _describe -t query_subcommands 'query type' query_subcommands
          ;;
        task)
          _describe -t task_subcommands 'task action' task_subcommands
          ;;
        issue)
          _describe -t issue_subcommands 'issue action' issue_subcommands
          ;;
        log)
          _arguments \
            '--all[Show all tasks from git history]' \
            '--spec[Filter by spec file]:spec:($(_ralph_get_specs))' \
            '--branch[Filter by branch]:branch:' \
            '--since[Changes since date/commit]:date:'
          ;;
      esac
      ;;
  esac
}

compdef _ralph ralph
