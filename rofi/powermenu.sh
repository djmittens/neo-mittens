#!/usr/bin/env bash
set -euo pipefail

# A simple rofi power menu that works on Hyprland/Wayland and X11.
# Provides: Lock, Suspend, Reboot, Poweroff, Logout.

confirm() {
  local msg="$1"
  echo -e "No\nYes" | rofi -dmenu -i -p "$msg" -theme-str 'window { width: 18em; }' || true
}

lock() {
  if command -v hyprlock >/dev/null 2>&1; then
    hyprlock
  elif command -v swaylock >/dev/null 2>&1; then
    swaylock -f -c 000000
  elif command -v loginctl >/dev/null 2>&1; then
    loginctl lock-session
  fi
}

suspend() {
  systemctl suspend
}

reboot() {
  systemctl reboot
}

poweroff() {
  systemctl poweroff
}

logout() {
  if command -v hyprctl >/dev/null 2>&1; then
    hyprctl dispatch exit 0
  else
    loginctl terminate-user "$USER"
  fi
}

choose() {
  rofi -dmenu -i -p "Power" <<EOF
Lock
Suspend
Reboot
Poweroff
Logout
EOF
}

main() {
  local choice
  choice=$(choose) || exit 0
  case "$choice" in
    Lock) lock ;;
    Suspend)
      [ "$(confirm 'Suspend?')" = "Yes" ] && suspend || true ;;
    Reboot)
      [ "$(confirm 'Reboot?')" = "Yes" ] && reboot || true ;;
    Poweroff)
      [ "$(confirm 'Poweroff?')" = "Yes" ] && poweroff || true ;;
    Logout)
      [ "$(confirm 'Logout?')" = "Yes" ] && logout || true ;;
    *) ;;
  esac
}

main "$@"
