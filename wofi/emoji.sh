#!/usr/bin/env bash
set -euo pipefail
trap 'exit 0' INT

# Emoji picker for wofi using a local TSV list (emoji \t description)
# Default: type the emoji (if `wtype` is available), do NOT copy.
# Flags:
#   --type         Type the emoji (default if wtype is present)
#   --copy         Copy the emoji to clipboard (no type)
#   --both         Type and copy
#   --no-type      Do not type (even if wtype exists)

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
LIST_FILE="$SCRIPT_DIR/emojis.tsv"

have() { command -v "$1" >/dev/null 2>&1; }

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
  local do_type=0
  local do_copy=0
  # Default: type if wtype exists; do not copy
  if have wtype; then do_type=1; fi
  case "${1:-}" in
    --type) do_type=1; shift || true ;;
    --copy) do_copy=1; do_type=0; shift || true ;;
    --both) do_copy=1; do_type=1; shift || true ;;
    --no-type) do_type=0; shift || true ;;
  esac

  if [ ! -f "$LIST_FILE" ]; then
    # Try to generate list if updater exists, but avoid hanging: use timeout when available.
    if [ -x "$SCRIPT_DIR/update_emojis.sh" ]; then
      if command -v timeout >/dev/null 2>&1; then
        timeout 25s "$SCRIPT_DIR/update_emojis.sh" || true
      else
        "$SCRIPT_DIR/update_emojis.sh" || true
      fi
    fi
    if [ ! -f "$LIST_FILE" ]; then
      echo "Emoji list not found: $LIST_FILE" >&2
      echo "Run: $SCRIPT_DIR/update_emojis.sh (requires curl)" >&2
      exit 1
    fi
  fi

  local line emoji desc
  line=$(wofi --dmenu --prompt "Emoji" --insensitive --width 800 < "$LIST_FILE") || exit 0
  [ -z "${line:-}" ] && exit 0

  emoji="${line%%$'\t'*}"
  desc="${line#*$'\t'}"

  if [ "$do_type" -eq 1 ] && have wtype; then
    # Small delay to let focus return to previous window after wofi closes
    sleep 0.05
    wtype -- "$emoji"
  fi
  if [ "$do_copy" -eq 1 ]; then
    printf '%s' "$emoji" | copy_clipboard
  fi
}

main "$@"
