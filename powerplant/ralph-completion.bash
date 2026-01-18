# Bash completion for ralph
# Source this file or add to ~/.bashrc:
#   source /path/to/ralph-completion.bash

_ralph_completions() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local prev="${COMP_WORDS[COMP_CWORD-1]}"
  local commands="init plan build status watch log help"
  
  case ${COMP_CWORD} in
    1)
      # First arg: command or number
      COMPREPLY=($(compgen -W "$commands 1 5 10 20" -- "$cur"))
      ;;
    2)
      # Second arg: number for plan/build
      case "$prev" in
        plan|build)
          COMPREPLY=($(compgen -W "1 5 10 20 50" -- "$cur"))
          ;;
      esac
      ;;
  esac
}

complete -F _ralph_completions ralph
