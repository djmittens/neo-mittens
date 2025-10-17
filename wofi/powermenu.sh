#!/usr/bin/env bash
set -euo pipefail
trap 'exit 0' INT

choose() {
  printf '%s\n' Lock Suspend Reboot Poweroff Logout | wofi --dmenu --prompt "Power" --insensitive --width 360
}

confirm() {
  local msg="$1"
  printf '%s\n' No Yes | wofi --dmenu --prompt "$msg" --insensitive --width 360
}

lock() {
  if command -v hyprlock >/dev/null 2>&1; then hyprlock
  elif command -v swaylock >/dev/null 2>&1; then swaylock -f -c 000000
  elif command -v loginctl >/dev/null 2>&1; then loginctl lock-session
  fi
}
suspend() { systemctl suspend; }
reboot() { systemctl reboot; }
poweroff() { systemctl poweroff; }
logout() {
  if command -v hyprctl >/dev/null 2>&1; then hyprctl dispatch exit 0
  else loginctl terminate-user "$USER"
  fi
}

main() {
  local arg="${1:-}"
  if [ -n "$arg" ]; then
    case "$arg" in
      lock|Lock) lock ;;
      suspend|Suspend) [ "$(confirm 'Suspend?')" = "Yes" ] && suspend || true ;;
      reboot|Reboot) [ "$(confirm 'Reboot?')" = "Yes" ] && reboot || true ;;
      poweroff|Poweroff|shutdown|Shutdown) [ "$(confirm 'Poweroff?')" = "Yes" ] && poweroff || true ;;
      logout|Logout|exit|Exit) [ "$(confirm 'Logout?')" = "Yes" ] && logout || true ;;
    esac
    exit 0
  fi

  choice=$(choose) || exit 0
  case "$choice" in
    Lock) lock ;;
    Suspend) [ "$(confirm 'Suspend?')" = "Yes" ] && suspend || true ;;
    Reboot) [ "$(confirm 'Reboot?')" = "Yes" ] && reboot || true ;;
    Poweroff) [ "$(confirm 'Poweroff?')" = "Yes" ] && poweroff || true ;;
    Logout) [ "$(confirm 'Logout?')" = "Yes" ] && logout || true ;;
  esac
}

main "$@"
