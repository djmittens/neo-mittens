#!/usr/bin/env bash
set -euo pipefail

# Generate emojis.tsv from Unicode emoji-test.txt
# Default source is Emoji 15.1. Override with EMOJI_URL if desired.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
OUT_FILE="$SCRIPT_DIR/emojis.tsv"
TMP_FILE="$(mktemp)"

# Preferred sources, in order. Can be overridden with EMOJI_URL.
URLS=(
  "${EMOJI_URL:-}"
  "https://unicode.org/Public/emoji/15.1/emoji-test.txt"
  "https://unicode.org/Public/emoji/15.0/emoji-test.txt"
  "https://unicode.org/Public/emoji/14.0/emoji-test.txt"
)

cleanup() { rm -f "$TMP_FILE" 2>/dev/null || true; }
trap cleanup EXIT

if ! command -v curl >/dev/null 2>&1; then
  echo "curl not found; cannot update emojis list." >&2
  exit 1
fi

fetch_url() {
  local u="$1"
  [ -z "$u" ] && return 1
  echo "Fetching: $u" >&2
  # Try IPv4 first to avoid some IPv6 stalls; set sensible timeouts and retries.
  curl -4 -fL --retry 2 --retry-delay 1 --connect-timeout 5 --max-time 20 \
    --compressed -o "$TMP_FILE" "$u" 2>/dev/null || \
  curl -fL --retry 2 --retry-delay 1 --connect-timeout 5 --max-time 20 \
    --compressed -o "$TMP_FILE" "$u"
}

ok=0
for u in "${URLS[@]}"; do
  if fetch_url "$u"; then ok=1; break; fi
done

if [ "$ok" -ne 1 ]; then
  echo "Failed to download emoji-test.txt from all sources." >&2
  exit 1
fi

# Parse only fully-qualified lines; grab the rendered emoji and the CLDR short name
# Example line:
# 1F3E0                                      ; fully-qualified     # 🏠 E0.6 house
awk '/; fully-qualified/ {
  if (match($0, /# ([^ ]+) E[0-9.]+ (.+)$/, a)) {
    emoji=a[1]; name=a[2];
    print emoji"\t"name;
  }
}' "$TMP_FILE" > "$OUT_FILE"

echo "Wrote: $OUT_FILE" >&2
