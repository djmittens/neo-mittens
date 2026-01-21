# Zsh completion for ralph
# Source this file from ~/.zshrc

_ralph_get_specs() {
  local repo_root
  repo_root=$(git rev-parse --show-toplevel 2>/dev/null)
  if [[ -n "$repo_root" && -d "$repo_root/ralph/specs" ]]; then
    ls "$repo_root/ralph/specs/"*.md 2>/dev/null | xargs -n1 basename 2>/dev/null
  fi
}

_ralph() {
  local -a subcommands
  subcommands=(
    'init:Initialize ralph in current repo'
    'plan:Run planning mode for a spec file'
    'construct:Run construct mode (implement from plan)'
    'config:Show or modify configuration'
    'status:Show current status'
    'watch:Live dashboard with metrics'
    'stream:Pretty-print opencode JSON stream'
    'query:Query current state (stage, tasks, issues, iteration)'
    'task:Task mutations (done, add, accept, reject, delete, prioritize)'
    'issue:Issue mutations (done, done-all, done-ids, add)'
    'set-spec:Set current spec file'
    'help:Show help'
  )

  local -a iterations
  iterations=(1 5 10 20 50 100)
  
  local -a cost_values
  cost_values=(5 10 25 50 100)
  
  local -a failure_values
  failure_values=(1 3 5 10)

  local -a profile_values
  profile_values=(budget balanced hybrid cost_smart)

  local -a query_subcommands
  query_subcommands=(stage tasks issues iteration)

  local -a task_subcommands
  task_subcommands=(done add accept reject delete prioritize)

  local -a issue_subcommands
  issue_subcommands=(done done-all done-ids add)

  _arguments -C \
    '1: :->cmd' \
    '*: :->args' \
    '--max-cost[Stop when cost exceeds N dollars]:cost:($cost_values)' \
    '--max-failures[Circuit breaker - stop after N consecutive failures]:failures:($failure_values)' \
    '--completion-promise[Stop when output contains this text]:promise:(DONE COMPLETE FINISHED SPEC_COMPLETE)' \
    '--timeout[Kill stage after N milliseconds]:timeout:' \
    '--context-limit[Context window size in tokens]:limit:' \
    '--no-ui[Disable interactive dashboard]' \
    '--profile[Cost profile]:profile:($profile_values)' \
    '-p[Cost profile]:profile:($profile_values)' \
    '--version[Show version]' \
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
        construct|"")
          _describe -t iterations 'iterations' iterations
          _arguments \
            '--max-cost[Stop when cost exceeds N dollars]:cost:($cost_values)' \
            '--max-failures[Circuit breaker]:failures:($failure_values)' \
            '--completion-promise[Stop on text]:promise:(DONE COMPLETE FINISHED SPEC_COMPLETE)' \
            '--timeout[Kill stage after N milliseconds]:timeout:' \
            '--context-limit[Context window size in tokens]:limit:' \
            '--no-ui[Disable interactive dashboard]' \
            '--profile[Cost profile]:profile:($profile_values)'
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
      esac
      ;;
  esac
}

compdef _ralph ralph
