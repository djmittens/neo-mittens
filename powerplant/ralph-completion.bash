# Bash completion for ralph
# Source this file or add to ~/.bashrc:
#   source /path/to/ralph-completion.bash

_ralph_completions() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local prev="${COMP_WORDS[COMP_CWORD-1]}"
  local commands="init plan build status watch stream metrics help"
  local options="--max-cost --max-failures --completion-promise"
  
  case "$prev" in
    --max-cost)
      COMPREPLY=($(compgen -W "5 10 25 50 100" -- "$cur"))
      return
      ;;
    --max-failures)
      COMPREPLY=($(compgen -W "1 3 5 10" -- "$cur"))
      return
      ;;
    --completion-promise)
      COMPREPLY=($(compgen -W "DONE COMPLETE FINISHED" -- "$cur"))
      return
      ;;
  esac
  
  if [[ "$cur" == -* ]]; then
    COMPREPLY=($(compgen -W "$options" -- "$cur"))
  elif [[ ${COMP_CWORD} -eq 1 ]]; then
    COMPREPLY=($(compgen -W "$commands 1 5 10 20 50" -- "$cur"))
  else
    case "${COMP_WORDS[1]}" in
      plan|build|"")
        COMPREPLY=($(compgen -W "1 5 10 20 50 100 $options" -- "$cur"))
        ;;
    esac
  fi
}

complete -F _ralph_completions ralph
