#!/usr/bin/env bash
set -euo pipefail
trap 'exit 0' INT

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"

choices=(
  " Lock"
  "⏼ Suspend"
  " Reboot"
  "⏻ Poweroff"
  " Logout"
)

menu() {
  printf '%s\n' "${choices[@]}" | wofi \
    --dmenu \
    --prompt "Power" \
    --orientation horizontal \
    --location bottom \
    --width 100% \
    --height 72 \
    --lines 1 \
    --insensitive \
    --style "$SCRIPT_DIR/powerbar.css"
}

handle() {
  case "$1" in
    *Lock*)      "$SCRIPT_DIR/powermenu.sh" Lock ;;
    *Suspend*)   "$SCRIPT_DIR/powermenu.sh" Suspend ;;
    *Reboot*)    "$SCRIPT_DIR/powermenu.sh" Reboot ;;
    *Poweroff*)  "$SCRIPT_DIR/powermenu.sh" Poweroff ;;
    *Logout*)    "$SCRIPT_DIR/powermenu.sh" Logout ;;
  esac
}

sel=$(menu || true)
[ -z "${sel:-}" ] && exit 0
handle "$sel"
