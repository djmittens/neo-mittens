# Bash completion for ralph
# Source this file or add to ~/.bashrc:
#   source /path/to/ralph-completion.bash

_ralph_get_specs() {
  # List spec files in ralph/specs/
  if [[ -d "ralph/specs" ]]; then
    ls ralph/specs/*.md 2>/dev/null | xargs -n1 basename 2>/dev/null
  fi
}

_ralph_completions() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local prev="${COMP_WORDS[COMP_CWORD-1]}"
  local commands="init plan build status watch stream query task issue set-spec log help"
  local options="--max-cost --max-failures --completion-promise --no-ui"
  
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
      COMPREPLY=($(compgen -W "DONE COMPLETE FINISHED SPEC_COMPLETE" -- "$cur"))
      return
      ;;
    plan|set-spec)
      # Complete with spec files
      local specs=$(_ralph_get_specs)
      COMPREPLY=($(compgen -W "$specs" -- "$cur"))
      return
      ;;
    query)
      COMPREPLY=($(compgen -W "stage next tasks issues" -- "$cur"))
      return
      ;;
    task)
      COMPREPLY=($(compgen -W "done add accept" -- "$cur"))
      return
      ;;
    issue)
      COMPREPLY=($(compgen -W "done add" -- "$cur"))
      return
      ;;
    log)
      COMPREPLY=($(compgen -W "--all --spec --branch --since" -- "$cur"))
      return
      ;;
  esac
  
  if [[ "$cur" == -* ]]; then
    COMPREPLY=($(compgen -W "$options" -- "$cur"))
  elif [[ ${COMP_CWORD} -eq 1 ]]; then
    COMPREPLY=($(compgen -W "$commands 1 5 10 20 50" -- "$cur"))
  else
    case "${COMP_WORDS[1]}" in
      plan)
        local specs=$(_ralph_get_specs)
        COMPREPLY=($(compgen -W "$specs" -- "$cur"))
        ;;
      build|"")
        COMPREPLY=($(compgen -W "1 5 10 20 50 100 $options" -- "$cur"))
        ;;
      query)
        COMPREPLY=($(compgen -W "stage next tasks issues" -- "$cur"))
        ;;
      task)
        COMPREPLY=($(compgen -W "done add accept" -- "$cur"))
        ;;
      issue)
        COMPREPLY=($(compgen -W "done add" -- "$cur"))
        ;;
    esac
  fi
}

complete -F _ralph_completions ralph
