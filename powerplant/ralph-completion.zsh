# Zsh completion for ralph
# Source this file from ~/.zshrc

_ralph() {
  local -a subcommands
  subcommands=(
    'init:Initialize ralph in current repo'
    'plan:Run planning mode (generate implementation plan)'
    'build:Run build mode (implement from plan)'
    'status:Show current status and metrics'
    'watch:Live dashboard with metrics'
    'log:Tail the current log'
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
            '--completion-promise[Stop on text]:promise:(DONE COMPLETE FINISHED)'
          ;;
      esac
      ;;
  esac
}

compdef _ralph ralph
