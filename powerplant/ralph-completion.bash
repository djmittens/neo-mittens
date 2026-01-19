# Bash completion for ralph
# Source this file or add to ~/.bashrc:
#   source /path/to/ralph-completion.bash

_ralph_get_issues() {
  # Extract ISSUE-N from ralph/IMPLEMENTATION_PLAN.md or count bullets in Discovered Issues
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

_ralph_completions() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local prev="${COMP_WORDS[COMP_CWORD-1]}"
  local commands="init plan build status watch stream investigate metrics help"
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
      COMPREPLY=($(compgen -W "DONE COMPLETE FINISHED" -- "$cur"))
      return
      ;;
    investigate)
      # Complete with issue IDs from implementation plan
      local issues=$(_ralph_get_issues)
      COMPREPLY=($(compgen -W "$issues" -- "$cur"))
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
      investigate)
        local issues=$(_ralph_get_issues)
        COMPREPLY=($(compgen -W "$issues" -- "$cur"))
        ;;
    esac
  fi
}

complete -F _ralph_completions ralph
