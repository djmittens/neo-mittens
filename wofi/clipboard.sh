#!/usr/bin/env bash
set -euo pipefail
trap 'exit 0' INT

have() { command -v "$1" >/dev/null 2>&1; }

if ! have cliphist; then
  notify-send -u low "wofi-clipboard" "cliphist not found" >/dev/null 2>&1 || true
  exit 1
fi

entry=$(cliphist list | wofi --dmenu --prompt "Clipboard" --insensitive --width 800) || exit 0
[ -z "${entry:-}" ] && exit 0

id="${entry%%$'\t'*}"
if [ -z "$id" ]; then exit 0; fi

if have wl-copy; then
  printf '%s' "$id" | cliphist decode | wl-copy
elif have xclip; then
  printf '%s' "$id" | cliphist decode | xclip -selection clipboard
fi
