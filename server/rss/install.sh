#!/usr/bin/env bash
#
# Install yarr RSS Reader service
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="yarr"
SERVICE_FILE="${SCRIPT_DIR}/${SERVICE_NAME}.service"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
BIN_DIR="${HOME}/.local/bin"
BIN_PATH="${BIN_DIR}/yarr"
# DB lives under $HOME (bind-mounted onto the /data partition on obelisk) - user-owned, no sudo
DATA_DIR="${HOME}/.local/share/yarr"
PORT="7070"

echo "Installing yarr RSS Reader service..."

# Download the stock yarr binary if it isn't already present.
if ! command -v yarr &> /dev/null && [ ! -x "${BIN_PATH}" ]; then
    echo "yarr binary not found. Downloading latest release..."

    case "$(uname -m)" in
        x86_64)  ARCH="amd64" ;;
        aarch64) ARCH="arm64" ;;
        armv7l)  ARCH="armv7" ;;
        *) echo "Error: unsupported architecture $(uname -m)"; exit 1 ;;
    esac

    for cmd in curl unzip; do
        if ! command -v "${cmd}" &> /dev/null; then
            echo "Error: ${cmd} is required to download yarr. Install it and re-run."
            exit 1
        fi
    done

    ASSET="yarr_linux_${ARCH}.zip"
    URL="https://github.com/nkanaev/yarr/releases/latest/download/${ASSET}"
    TMP="$(mktemp -d)"
    echo "  Fetching ${URL}"
    curl -fsSL "${URL}" -o "${TMP}/${ASSET}"
    unzip -o -q "${TMP}/${ASSET}" -d "${TMP}"
    mkdir -p "${BIN_DIR}"
    install -m 0755 "${TMP}/yarr" "${BIN_PATH}"
    rm -rf "${TMP}"
    echo "✓ yarr installed to ${BIN_PATH}"
else
    echo "✓ yarr binary already present"
fi

# Create the data directory (embedded SQLite db lives here)
mkdir -p "${DATA_DIR}"
echo "✓ Data dir: ${DATA_DIR}"

# Create systemd user directory
mkdir -p "${SYSTEMD_USER_DIR}"

# Copy service file
cp "${SERVICE_FILE}" "${SYSTEMD_USER_DIR}/"
echo "✓ Service file installed to ${SYSTEMD_USER_DIR}/${SERVICE_NAME}.service"

# Reload systemd
systemctl --user daemon-reload
echo "✓ Systemd reloaded"

# Note: no authentication is configured (YARR_AUTH unset).
echo ""
echo "Note: yarr is running WITHOUT authentication."
echo "      It is reachable by anything on your LAN/Tailscale at port ${PORT}."
echo "      To enable a login later, add this under [Service] via"
echo "      'systemctl --user edit --full ${SERVICE_NAME}':"
echo '        Environment="YARR_AUTH=username:password"'

# Enable and start
echo ""
read -p "Enable and start the service now? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    systemctl --user enable "${SERVICE_NAME}.service"
    loginctl enable-linger "${USER}"
    echo "✓ Service enabled"

    systemctl --user start "${SERVICE_NAME}.service"

    if systemctl --user is-active --quiet "${SERVICE_NAME}.service"; then
        echo "✓ Service started successfully"

        # Expose to the tailnet via `tailscale serve` (HTTPS, tailnet-only).
        # yarr binds loopback only; this proxy is the sole network entry point,
        # so it is NOT reachable from the wifi/LAN.
        if command -v tailscale &> /dev/null; then
            echo ""
            echo "Setting up Tailscale serve (HTTPS, tailnet-only)..."
            if tailscale serve --bg --https="${PORT}" "http://127.0.0.1:${PORT}"; then
                echo "✓ Tailscale serve configured"
            else
                echo "⚠ Could not configure tailscale serve automatically. Run manually:"
                echo "    tailscale serve --bg --https=${PORT} http://127.0.0.1:${PORT}"
            fi
            TS_HOST=$(tailscale status --json 2>/dev/null | grep -o '"DNSName": *"[^"]*"' | head -1 | sed 's/.*"DNSName": *"//; s/"$//; s/\.$//' || true)
        fi

        echo ""
        echo "Access URLs:"
        echo "  Local (this host): http://localhost:${PORT}"
        if [ -n "${TS_HOST:-}" ]; then
            echo "  Tailnet (HTTPS):   https://${TS_HOST}:${PORT}"
            echo "  Fever (phone apps): https://${TS_HOST}:${PORT}/fever"
        fi
        echo ""
        echo "Import your feeds from server/rss/feeds.opml via Settings > Import."
    else
        echo "✗ Failed to start service"
        echo "Check logs: journalctl --user -u ${SERVICE_NAME}"
        exit 1
    fi
fi

echo ""
echo "Installation complete!"
