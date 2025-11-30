#!/usr/bin/env bash
set -euo pipefail

# Simple clipboard manager for Wayland using cliphist + wl-clipboard.
# Requires: cliphist, wl-copy/wl-paste (or xclip fallback on X11).

have() { command -v "$1" >/dev/null 2>&1; }

copy() {
  if have wl-copy; then
    wl-copy --foreground --type text/plain
  elif have xclip; then
    xclip -selection clipboard
  else
    cat >/dev/null
  fi
}

if ! have cliphist; then
  echo "cliphist not found" | rofi -e "Install cliphist for clipboard history" || true
  exit 1
fi

# Format: id<TAB>content-preview
sel=$(cliphist list | rofi -dmenu -i -p "Clipboard" -format s) || exit 0

if [ -z "$sel" ]; then exit 0; fi

# cliphist expects the ID on stdin, outputs data to stdout
printf '%s' "$sel" | cliphist decode | copy
