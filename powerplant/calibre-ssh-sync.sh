#!/usr/bin/env bash
set -euo pipefail

# calibre-ssh-sync.sh
#
# Run this on the macOS laptop. It performs a safe, two-way sync with a Linux desktop
# over SSH by exchanging export bundles and letting Calibre merge duplicates.
#
# Order of operations (avoids echo loops):
# - Laptop exports local changes since last send → pushes bundle to desktop.
# - Desktop first exports its own changes since last send (BEFORE importing laptop bundle),
#   updates its send watermark, then imports the incoming laptop bundle.
# - Laptop pulls desktop export bundle and imports it locally.
#
# Requirements:
# - Close Calibre GUI on both machines during sync.
# - Set Calibre Preferences → Adding books → If a duplicate is found → "Merge into existing book record".
# - Custom columns should be identical on both machines.
# - calibredb must be available on both machines (set paths below if needed).

########################################
# EDIT THESE VARIABLES PER YOUR SETUP  #
########################################

# SSH remote in the form user@host
REMOTE_SSH="user@desktop-host"

# Paths to calibredb binaries (override if not in PATH)
CALIBREDB_LOCAL_BIN="${CALIBREDB_LOCAL_BIN:-/Applications/calibre.app/Contents/MacOS/calibredb}"
CALIBREDB_REMOTE_BIN="${CALIBREDB_REMOTE_BIN:-/usr/bin/calibredb}"

# Calibre library folders (contain metadata.db)
# Defaults to the common Calibre location on Linux/macOS; override if different.
LIBRARY_LOCAL="${LIBRARY_LOCAL:-/path/to/Laptop Calibre Library}"
LIBRARY_REMOTE="${LIBRARY_REMOTE:-$HOME/Calibre Library}"

# Bundle roots (where temporary export/import run directories live)
LOCAL_BUNDLES_ROOT="${LOCAL_BUNDLES_ROOT:-$HOME/CalibreSync}"
REMOTE_BUNDLES_ROOT="${REMOTE_BUNDLES_ROOT:-$HOME/CalibreSync}"

# Identifiers for stamp files (use hostnames or labels; no spaces)
PEER_LABEL_REMOTE="${PEER_LABEL_REMOTE:-desktop}"
PEER_LABEL_LOCAL="${PEER_LABEL_LOCAL:-laptop}"

########################################
# Internals (normally no need to edit)  #
########################################

iso_now() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

timestamp_tag() { date -u +"%Y%m%d-%H%M%S"; }

# Reads a stamp value or prints a default fallback (N days ago)
read_or_default_stamp() {
  local file="$1"; shift
  local days_back="${1:-90}"
  if [[ -f "$file" ]]; then
    cat "$file"
  else
    # Portable days-ago date in UTC (YYYY-MM-DD). Avoids GNU date dependency on macOS.
    if date -u -v-"${days_back}"d +"%Y-%m-%d" >/dev/null 2>&1; then
      date -u -v-"${days_back}"d +"%Y-%m-%d"
    else
      # Fallback: today; worst case initial export is empty
      date -u +"%Y-%m-%d"
    fi
  fi
}

write_stamp() {
  local file="$1"; shift
  local value="$1"; shift
  printf '%s' "$value" >"$file"
}

ensure_dir() { mkdir -p "$1"; }

rsync_up() { rsync -a "$1" "$2"; }

rsync_down() { rsync -a "$1" "$2"; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}

check_calibredb() {
  "$1" --version >/dev/null 2>&1 || { echo "Cannot run calibredb at $1" >&2; exit 1; }
}

echo "[calibre-ssh-sync] Starting two-way sync (laptop ↔ desktop)"

# Basic checks
require_cmd ssh
require_cmd rsync
check_calibredb "$CALIBREDB_LOCAL_BIN"

# Remote checks (lightweight): ensure calibredb exists and paths are reachable
ssh "$REMOTE_SSH" bash -lc "'${CALIBREDB_REMOTE_BIN}' --version >/dev/null 2>&1" \
  || { echo "Remote calibredb not found or not runnable: $CALIBREDB_REMOTE_BIN" >&2; exit 1; }

# Paths and files
ensure_dir "$LOCAL_BUNDLES_ROOT"
RUN_TAG="$(timestamp_tag)"
LOCAL_OUT_DIR="$LOCAL_BUNDLES_ROOT/to-$PEER_LABEL_REMOTE/run-$RUN_TAG/"
LOCAL_IN_DIR="$LOCAL_BUNDLES_ROOT/from-$PEER_LABEL_REMOTE/"
REMOTE_OUT_DIR="$REMOTE_BUNDLES_ROOT/to-$PEER_LABEL_LOCAL/run-$RUN_TAG/"
REMOTE_IN_DIR="$REMOTE_BUNDLES_ROOT/from-$PEER_LABEL_LOCAL/"

# Directional stamps: maintain independent send watermarks to avoid echo
STAMP_LOCAL_SEND="$LIBRARY_LOCAL/.calibre-sync-sent-$PEER_LABEL_REMOTE"
STAMP_REMOTE_SEND="$LIBRARY_REMOTE/.calibre-sync-sent-$PEER_LABEL_LOCAL"

FROM_LOCAL_SEND="$(read_or_default_stamp "$STAMP_LOCAL_SEND" 90)"
SEND_MARK_LOCAL_NOW="$(iso_now)"

echo "[laptop] Exporting changes since $FROM_LOCAL_SEND"

# Collect IDs changed since last local send
mapfile -t IDS_LOCAL < <("$CALIBREDB_LOCAL_BIN" --with-library "$LIBRARY_LOCAL" list \
  --fields id --search "last_modified:>$FROM_LOCAL_SEND" | awk 'NR>1 {print $1}' | sed -e '/^$/d')

if ((${#IDS_LOCAL[@]})); then
  ensure_dir "$LOCAL_OUT_DIR"
  "$CALIBREDB_LOCAL_BIN" --with-library "$LIBRARY_LOCAL" export --to-dir "$LOCAL_OUT_DIR" "${IDS_LOCAL[@]}"
  echo "[laptop] Exported ${#IDS_LOCAL[@]} book(s) → $LOCAL_OUT_DIR"
else
  echo "[laptop] No local changes to export"
fi

# Defer advancing local send watermark until after remote import succeeds

# Ensure remote bundle dirs exist
ssh "$REMOTE_SSH" bash -lc "mkdir -p '$REMOTE_BUNDLES_ROOT/from-$PEER_LABEL_LOCAL' '$REMOTE_BUNDLES_ROOT/to-$PEER_LABEL_LOCAL'"

# Push laptop bundle (if any) to remote incoming
if [[ -d "$LOCAL_OUT_DIR" ]]; then
  echo "[laptop→desktop] Uploading bundle"
  rsync_up "$LOCAL_OUT_DIR" "$REMOTE_SSH:$REMOTE_IN_DIR"
fi

echo "[desktop] Exporting its changes (pre-import) and updating watermark"
# Compute remote FROM_DATE and send timestamp
REMOTE_FROM_DATE=$(ssh "$REMOTE_SSH" bash -lc "if [ -f '$STAMP_REMOTE_SEND' ]; then cat '$STAMP_REMOTE_SEND'; else date -u +%Y-%m-%d; fi")
REMOTE_SEND_MARK_NOW=$(ssh "$REMOTE_SSH" bash -lc "date -u +%Y-%m-%dT%H:%M:%SZ")

# Remote export
ssh "$REMOTE_SSH" bash -lc "\
  set -euo pipefail; \
  CALIBREDB=\"$CALIBREDB_REMOTE_BIN\"; \
  LIB=\"$LIBRARY_REMOTE\"; \
  OUT=\"$REMOTE_OUT_DIR\"; \
  FROM=\"$REMOTE_FROM_DATE\"; \
  mkdir -p \"$REMOTE_BUNDLES_ROOT/to-$PEER_LABEL_LOCAL\"; \
  mapfile -t IDS < <(\"$CALIBREDB\" --with-library \"$LIB\" list --fields id --search \"last_modified:>$REMOTE_FROM_DATE\" | awk 'NR>1 {print $1}' | sed -e '/^$/d'); \
  if (( \${#IDS[@]} )); then \
    mkdir -p \"$OUT\"; \
    \"$CALIBREDB\" --with-library \"$LIB\" export --to-dir \"$OUT\" \"${IDS[@]}\"; \
    echo \"[desktop] Exported \${#IDS[@]} book(s) → $OUT\"; \
  else \
    echo \"[desktop] No changes to export\"; \
  fi; \
  printf '%s' \"$REMOTE_SEND_MARK_NOW\" > \"$STAMP_REMOTE_SEND\"; \
"

# Remote import of our uploaded bundle
ssh "$REMOTE_SSH" bash -lc "\
  set -euo pipefail; \
  CALIBREDB=\"$CALIBREDB_REMOTE_BIN\"; \
  LIB=\"$LIBRARY_REMOTE\"; \
  IN_ROOT=\"$REMOTE_IN_DIR\"; \
  shopt -s nullglob; \
  for b in \"$IN_ROOT\"/run-*; do \
    [ -d \"$b\" ] || continue; \
    echo \"[desktop] Importing bundle: $b\"; \
    \"$CALIBREDB_REMOTE_BIN\" --with-library \"$LIB\" add --recurse \"$b\"; \
    mv \"$b\" \"$b.imported.$(date -u +%Y%m%d-%H%M%S)\"; \
  done; \
"

# Now that the remote import succeeded, advance local send watermark
write_stamp "$STAMP_LOCAL_SEND" "$SEND_MARK_LOCAL_NOW"

# Pull desktop export bundle
echo "[laptop←desktop] Downloading desktop bundle(s)"
ensure_dir "$LOCAL_IN_DIR"
rsync_down "$REMOTE_SSH:$REMOTE_BUNDLES_ROOT/to-$PEER_LABEL_LOCAL/" "$LOCAL_IN_DIR/" || true

# Import any bundles from desktop
shopt -s nullglob
for bundle in "$LOCAL_IN_DIR"/run-*; do
  [[ -d "$bundle" ]] || continue
  echo "[laptop] Importing bundle: $bundle"
  "$CALIBREDB_LOCAL_BIN" --with-library "$LIBRARY_LOCAL" add --recurse "$bundle"
  mv "$bundle" "$bundle.imported.$(timestamp_tag)"
done

echo "[calibre-ssh-sync] Done"
