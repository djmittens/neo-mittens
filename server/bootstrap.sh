#!/usr/bin/env bash
#
# Bootstrap script to set up all server services
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "================================================"
echo "  Server Bootstrap"
echo "================================================"
echo ""
echo "This will set up all services on this machine:"
echo "  - OpenCode WebUI (remote coding)"
echo "  - Backup server (TODO)"
echo "  - CI server (TODO)"
echo "  - AI/LLM server (TODO)"
echo "  - ClawdBot (TODO)"
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "================================================"
echo "  Prerequisites"
echo "================================================"
echo ""

# Check for Tailscale
if ! command -v tailscale &> /dev/null; then
    echo "Warning: Tailscale not found."
    echo "Install with: curl -fsSL https://tailscale.com/install.sh | sh"
    echo ""
    read -p "Continue without Tailscale? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✓ Tailscale installed"
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "not connected")
    echo "  IP: ${TAILSCALE_IP}"
fi

echo ""
echo "================================================"
echo "  Installing Services"
echo "================================================"
echo ""

# OpenCode
if [ -f "${SCRIPT_DIR}/opencode/install.sh" ]; then
    echo "--- Installing OpenCode WebUI ---"
    "${SCRIPT_DIR}/opencode/install.sh"
    echo ""
fi

# Backup (TODO)
echo "--- Backup Server ---"
echo "TODO: Not yet implemented"
echo ""

# CI (TODO)
echo "--- CI Server ---"
echo "TODO: Not yet implemented"
echo ""

# AI/LLM (TODO)
echo "--- AI/LLM Server ---"
echo "TODO: Not yet implemented"
echo ""

# ClawdBot (TODO)
echo "--- ClawdBot ---"
echo "TODO: Not yet implemented"
echo ""

echo "================================================"
echo "  Bootstrap Complete!"
echo "================================================"
echo ""
echo "Check service status:"
echo "  systemctl --user status opencode-webui"
echo ""
echo "View logs:"
echo "  journalctl --user -u opencode-webui -f"
echo ""
if command -v tailscale &> /dev/null; then
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "")
    if [ -n "${TAILSCALE_IP}" ]; then
        echo "Access from any device via Tailscale:"
        echo "  http://${TAILSCALE_IP}:4096"
        echo ""
    fi
fi
