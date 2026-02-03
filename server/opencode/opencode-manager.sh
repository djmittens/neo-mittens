#!/usr/bin/env bash
#
# OpenCode WebUI Manager
# Manages OpenCode WebUI as a systemd user service with Tailscale access
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="opencode-webui"
SERVICE_FILE="${SCRIPT_DIR}/${SERVICE_NAME}.service"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

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
    
    if ! command -v opencode &> /dev/null; then
        missing+=("opencode")
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
    print_info "Setting up OpenCode WebUI service..."
    
    # Create systemd user directory if it doesn't exist
    mkdir -p "${SYSTEMD_USER_DIR}"
    
    # Copy service file
    cp "${SERVICE_FILE}" "${SYSTEMD_USER_DIR}/"
    print_success "Service file copied to ${SYSTEMD_USER_DIR}/${SERVICE_NAME}.service"
    
    # Reload systemd
    systemctl --user daemon-reload
    print_success "Systemd daemon reloaded"
    
    # Prompt for password
    print_warning "IMPORTANT: You need to set a secure password for OpenCode WebUI"
    print_info "Edit the service file to set OPENCODE_SERVER_PASSWORD:"
    echo -e "  ${BLUE}systemctl --user edit ${SERVICE_NAME}${NC}"
    echo ""
    print_info "Add these lines under [Service]:"
    echo "  Environment=\"OPENCODE_SERVER_PASSWORD=your-secure-password\""
    echo ""
}

enable_service() {
    print_info "Enabling OpenCode WebUI service to start on boot..."
    systemctl --user enable "${SERVICE_NAME}.service"
    
    # Enable lingering so service runs even when not logged in
    loginctl enable-linger "${USER}"
    print_success "Service enabled and lingering activated"
}

disable_service() {
    print_info "Disabling OpenCode WebUI service..."
    systemctl --user disable "${SERVICE_NAME}.service"
    print_success "Service disabled"
}

start_service() {
    print_info "Starting OpenCode WebUI service..."
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
    print_info "Stopping OpenCode WebUI service..."
    systemctl --user stop "${SERVICE_NAME}.service"
    print_success "Service stopped"
}

restart_service() {
    print_info "Restarting OpenCode WebUI service..."
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
    echo "  OpenCode WebUI Access Information"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    
    # Local access
    print_info "Local access:"
    echo "  http://localhost:4096"
    echo ""
    
    # Tailscale access
    if command -v tailscale &> /dev/null; then
        TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "not connected")
        if [ "${TAILSCALE_IP}" != "not connected" ]; then
            print_info "Tailscale access (from any device on your tailnet):"
            echo "  http://${TAILSCALE_IP}:4096"
            echo ""
            print_info "Or use the MagicDNS hostname:"
            HOSTNAME=$(tailscale status --json 2>/dev/null | grep -o '"HostName":"[^"]*' | cut -d'"' -f4 || hostname)
            echo "  http://${HOSTNAME}:4096"
        else
            print_warning "Tailscale not connected"
        fi
    fi
    
    echo ""
    print_info "Username: opencode"
    print_warning "Password: (set in service file)"
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
}

show_help() {
    cat << EOF
OpenCode WebUI Manager

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
    $(basename "$0") setup
    $(basename "$0") enable
    $(basename "$0") start

    # Daily usage
    $(basename "$0") status
    $(basename "$0") logs
    $(basename "$0") restart

    # Get access URLs
    $(basename "$0") access

Note: OpenCode web server supports multiple projects through sessions.
      You can work on different projects by creating separate sessions
      in the web interface.
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
