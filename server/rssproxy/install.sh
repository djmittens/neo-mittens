#!/usr/bin/env bash
#
# Build and install the rss-proxy service.
#
# Builds the Go binary, installs a systemd user unit, sets RSSPROXY_PUBLIC_BASE to this
# host's Tailscale MagicDNS name, and exposes it via `tailscale serve` (tailnet-only HTTPS).
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="rss-proxy"
SERVICE_FILE="${SCRIPT_DIR}/${SERVICE_NAME}.service"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
BIN_DIR="${HOME}/.local/bin"
BIN_PATH="${BIN_DIR}/rss-proxy"
DATA_DIR="${HOME}/.local/share/rssproxy"
PORT="7071"

echo "Installing rss-proxy..."

for cmd in go gcc git tailscale; do
    if ! command -v "${cmd}" &> /dev/null; then
        echo "Error: '${cmd}' is required. Install it and re-run."
        exit 1
    fi
done

# Build
echo "Building rss-proxy (go build)..."
mkdir -p "${BIN_DIR}"
( cd "${SCRIPT_DIR}" && go build -o "${BIN_PATH}" . )
echo "✓ Built ${BIN_PATH}"

mkdir -p "${DATA_DIR}"
echo "✓ Data dir: ${DATA_DIR}"

# Determine this host's Tailscale MagicDNS name for the public base URL
TS_HOST=$(tailscale status --json 2>/dev/null | grep -o '"DNSName": *"[^"]*"' | head -1 | sed 's/.*"DNSName": *"//; s/"$//; s/\.$//' || true)
if [ -z "${TS_HOST}" ]; then
    echo "Error: could not determine Tailscale MagicDNS name (is tailscale up?)."
    exit 1
fi
PUBLIC_BASE="https://${TS_HOST}:${PORT}"
echo "✓ Public base: ${PUBLIC_BASE}"

# Install unit with the public base substituted in
mkdir -p "${SYSTEMD_USER_DIR}"
sed "s#__PUBLIC_BASE__#${PUBLIC_BASE}#" "${SERVICE_FILE}" > "${SYSTEMD_USER_DIR}/${SERVICE_NAME}.service"
systemctl --user daemon-reload
echo "✓ Service installed"

systemctl --user enable "${SERVICE_NAME}.service"
loginctl enable-linger "${USER}"
systemctl --user restart "${SERVICE_NAME}.service"
sleep 2

if ! systemctl --user is-active --quiet "${SERVICE_NAME}.service"; then
    echo "✗ Service failed to start. Logs:"
    journalctl --user -u "${SERVICE_NAME}" -n 20 --no-pager
    exit 1
fi
echo "✓ Service running"

# Expose on the tailnet via tailscale serve (HTTPS, tailnet-only)
if tailscale serve --bg --https="${PORT}" "http://127.0.0.1:${PORT}"; then
    echo "✓ Tailscale serve configured: ${PUBLIC_BASE}"
else
    echo "⚠ Could not configure tailscale serve. Run manually:"
    echo "    tailscale serve --bg --https=${PORT} http://127.0.0.1:${PORT}"
fi

echo ""
echo "rss-proxy installed."
echo "  Subscribe yarr feeds to: ${PUBLIC_BASE}/feed?url=<URL-ENCODED original feed>"
echo "  Health: curl -s ${PUBLIC_BASE}/healthz"
