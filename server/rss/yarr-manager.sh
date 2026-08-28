#!/usr/bin/env bash
#
# yarr RSS Reader Manager
# Manages yarr as a systemd user service with Tailscale access
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="yarr"
SERVICE_FILE="${SCRIPT_DIR}/${SERVICE_NAME}.service"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
PORT="7070"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${BLUE}ℹ${NC} $*"
}

print_success() {
    echo -e "${GREEN}✓${NC} $*"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $*"
}

print_error() {
    echo -e "${RED}✗${NC} $*"
}

check_requirements() {
    local missing=()

    if ! command -v yarr &> /dev/null && [ ! -x "${HOME}/.local/bin/yarr" ]; then
        missing+=("yarr (run ./install.sh to download it)")
    fi

    if ! command -v systemctl &> /dev/null; then
        missing+=("systemctl")
    fi

    if ! command -v tailscale &> /dev/null; then
        print_warning "tailscale not found - you won't be able to get Tailscale access info"
    fi

    if [ ${#missing[@]} -ne 0 ]; then
        print_error "Missing required commands: ${missing[*]}"
        return 1
    fi

    return 0
}

setup_service() {
    print_info "Setting up yarr service..."

    # Create systemd user directory if it doesn't exist
    mkdir -p "${SYSTEMD_USER_DIR}"

    # Copy service file
    cp "${SERVICE_FILE}" "${SYSTEMD_USER_DIR}/"
    print_success "Service file copied to ${SYSTEMD_USER_DIR}/${SERVICE_NAME}.service"

    # Reload systemd
    systemctl --user daemon-reload
    print_success "Systemd daemon reloaded"

    # No authentication configured
    print_warning "yarr runs WITHOUT authentication (open on LAN/Tailscale at port ${PORT})"
    print_info "To enable a login later, add this under [Service] via 'edit --full ${SERVICE_NAME}':"
    echo "  Environment=\"YARR_AUTH=username:password\""
    echo ""
}

enable_service() {
    print_info "Enabling yarr service to start on boot..."
    systemctl --user enable "${SERVICE_NAME}.service"

    # Enable lingering so service runs even when not logged in
    loginctl enable-linger "${USER}"
    print_success "Service enabled and lingering activated"
}

disable_service() {
    print_info "Disabling yarr service..."
    systemctl --user disable "${SERVICE_NAME}.service"
    print_success "Service disabled"
}

start_service() {
    print_info "Starting yarr service..."
    systemctl --user start "${SERVICE_NAME}.service"
    sleep 2

    if systemctl --user is-active --quiet "${SERVICE_NAME}.service"; then
        print_success "Service started successfully"
        show_access_info
    else
        print_error "Service failed to start"
        print_info "Check logs with: journalctl --user -u ${SERVICE_NAME} -f"
        return 1
    fi
}

stop_service() {
    print_info "Stopping yarr service..."
    systemctl --user stop "${SERVICE_NAME}.service"
    print_success "Service stopped"
}

restart_service() {
    print_info "Restarting yarr service..."
    systemctl --user restart "${SERVICE_NAME}.service"
    sleep 2

    if systemctl --user is-active --quiet "${SERVICE_NAME}.service"; then
        print_success "Service restarted successfully"
        show_access_info
    else
        print_error "Service failed to restart"
        return 1
    fi
}

show_status() {
    echo ""
    systemctl --user status "${SERVICE_NAME}.service"
}

show_logs() {
    print_info "Showing logs (Ctrl+C to exit)..."
    journalctl --user -u "${SERVICE_NAME}" -f
}

show_access_info() {
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  yarr RSS Reader Access Information"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""

    # Local access (loopback on this host only)
    print_info "Local access (this host only):"
    echo "  http://localhost:${PORT}"
    echo ""

    # Tailnet access via `tailscale serve` (HTTPS, tailnet-only)
    if command -v tailscale &> /dev/null; then
        TS_HOST=$(tailscale status --json 2>/dev/null | grep -o '"DNSName": *"[^"]*"' | head -1 | sed 's/.*"DNSName": *"//; s/"$//; s/\.$//' || true)
        if [ -n "${TS_HOST}" ]; then
            print_info "Tailnet access (HTTPS, from any device on your tailnet):"
            echo "  https://${TS_HOST}:${PORT}"
            echo ""
            print_info "Fever API endpoint (native phone apps):"
            echo "  https://${TS_HOST}:${PORT}/fever"
        else
            print_warning "Tailscale not connected"
        fi
        echo ""
        if ! tailscale serve status 2>/dev/null | grep -q ":${PORT} "; then
            print_warning "tailscale serve proxy for :${PORT} not found. Set it up with:"
            echo "    tailscale serve --bg --https=${PORT} http://127.0.0.1:${PORT}"
        fi
    fi

    echo ""
    print_info "yarr binds 127.0.0.1 only; tailnet exposure is via tailscale serve."
    print_warning "No authentication (YARR_AUTH unset) - safe because LAN cannot reach loopback."
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
}

show_help() {
    cat << EOF
yarr RSS Reader Manager

Usage: $(basename "$0") <command>

Commands:
    setup       Install and configure the systemd service
    enable      Enable service to start on boot
    disable     Disable service autostart
    start       Start the service
    stop        Stop the service
    restart     Restart the service
    status      Show service status
    logs        Show and follow service logs
    access      Show access information (URLs)
    help        Show this help message

Examples:
    # Initial setup
    ./install.sh            # downloads binary + installs unit
    $(basename "$0") enable
    $(basename "$0") start

    # Daily usage
    $(basename "$0") status
    $(basename "$0") logs
    $(basename "$0") restart

    # Get access URLs
    $(basename "$0") access

Note: yarr stores all data in a single SQLite file at ~/.local/share/yarr/storage.db
      (physically on the 1.7TB /data partition via the /home bind mount).
      Back up that one file to preserve feeds and read state.
EOF
}

main() {
    if [ $# -eq 0 ]; then
        show_help
        exit 0
    fi

    case "$1" in
        setup)
            check_requirements
            setup_service
            ;;
        enable)
            enable_service
            ;;
        disable)
            disable_service
            ;;
        start)
            start_service
            ;;
        stop)
            stop_service
            ;;
        restart)
            restart_service
            ;;
        status)
            show_status
            ;;
        logs)
            show_logs
            ;;
        access)
            show_access_info
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "Unknown command: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

main "$@"
