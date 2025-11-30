#!/usr/bin/env bash
set -euo pipefail
trap 'exit 0' INT

have() { command -v "$1" >/dev/null 2>&1; }

calc() {
  local expr="$1" result
  if have qalc; then
    result=$(qalc -t -- "$expr" 2>/dev/null || true)
  else
    result=$(echo "$expr" | bc -l 2>/dev/null || true)
  fi
  echo "$result"
}

copy_clipboard() {
  if have wl-copy; then
    wl-copy
  elif have xclip; then
    xclip -selection clipboard
  else
    cat >/dev/null
  fi
}

main() {
  local expr result choice
  while true; do
    expr=$(printf '' | wofi --dmenu --prompt "Calc" --insensitive --width 640) || exit 0
    [ -z "${expr:-}" ] && exit 0
    result=$(calc "$expr")
    choice=$(printf '%s\nCopy\nNew\nQuit' "$result" | wofi --dmenu --prompt "Result" --insensitive --width 480) || exit 0
    case "$choice" in
      Copy)
        printf '%s' "$result" | copy_clipboard ;;
      New)
        continue ;;
      Quit|*)
        exit 0 ;;
    esac
  done
}

main "$@"
