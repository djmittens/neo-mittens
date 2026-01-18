# Zsh completion for ralph
# Source this file from ~/.zshrc

_ralph() {
  local -a subcommands
  subcommands=(
    'init:Initialize ralph in current repo'
    'plan:Run planning mode (generate implementation plan)'
    'build:Run build mode (implement from plan)'
    'status:Show current status'
    'watch:Live dashboard'
    'log:Tail the current log'
    'help:Show help'
  )

  local -a iterations
  iterations=(1 5 10 20 50)

  _arguments -C \
    '1: :->cmd' \
    '2: :->arg' \
    && return

  case $state in
    cmd)
      _describe -t subcommands 'ralph command' subcommands
      _describe -t iterations 'iterations' iterations
      ;;
    arg)
      case $words[2] in
        plan|build)
          _describe -t iterations 'iterations' iterations
          ;;
      esac
      ;;
  esac
}

compdef _ralph ralph
