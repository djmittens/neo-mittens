#!/usr/bin/env bash
#
# Install OpenCode WebUI service
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="opencode-webui"
SERVICE_FILE="${SCRIPT_DIR}/${SERVICE_NAME}.service"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

echo "Installing OpenCode WebUI service..."

# Check if opencode is installed
if ! command -v opencode &> /dev/null; then
    echo "Error: opencode not found. Please install it first:"
    echo "  curl -fsSL https://opencode.ai/install | bash"
    exit 1
fi

# Create systemd user directory
mkdir -p "${SYSTEMD_USER_DIR}"

# Copy service file
cp "${SERVICE_FILE}" "${SYSTEMD_USER_DIR}/"
echo "✓ Service file installed to ${SYSTEMD_USER_DIR}/${SERVICE_NAME}.service"

# Reload systemd
systemctl --user daemon-reload
echo "✓ Systemd reloaded"

# Prompt for password
echo ""
echo "Set your password by editing the service file:"
echo "  systemctl --user edit --full ${SERVICE_NAME}"
echo ""
echo "Find this line:"
echo '  Environment="OPENCODE_SERVER_PASSWORD=change-me-to-secure-password"'
echo ""
echo "And change it to your actual password."
echo ""
read -p "Press Enter to edit the service file now, or Ctrl+C to skip..."

# Try to open editor
if [ -t 0 ]; then
    systemctl --user edit --full "${SERVICE_NAME}" || true
fi

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
        echo ""
        echo "Access URLs:"
        echo "  Local:     http://localhost:4096"
        if command -v tailscale &> /dev/null; then
            TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
            if [ -n "${TAILSCALE_IP}" ]; then
                echo "  Tailscale: http://${TAILSCALE_IP}:4096"
            fi
        fi
        echo ""
        echo "Username: opencode"
        echo "Password: (the one you set)"
    else
        echo "✗ Failed to start service"
        echo "Check logs: journalctl --user -u ${SERVICE_NAME}"
        exit 1
    fi
fi

echo ""
echo "Installation complete!"
