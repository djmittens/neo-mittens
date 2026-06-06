#!/usr/bin/env bash
# install-gaming.sh — thin wrapper that delegates to the Ansible playbook.
#
# This script:
#   1. Sanity-checks the host (Linux + Arch).
#   2. Installs ansible if missing (one-time bootstrap of the bootstrapper).
#   3. Runs the portable bootstrap.sh first (dotfiles, neovim, tmux, etc.).
#   4. Runs the gaming-desktop ansible playbook (system config, gamemode,
#      gamewatcher, bnetswitch).
#
# Why bash for this thin wrapper instead of a longer Ansible playbook:
#   - We need to install ansible itself before we can run a playbook
#     (chicken-and-egg problem).
#   - bootstrap.sh is still bash (portable across macOS + Linux) so we
#     have to shell out to it anyway.
#   - The actual heavy-lifting is done in YAML where it belongs.
#
# DO NOT RUN THIS ON THE SERVER OR MACS. Gaming-desktop only.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"

log()  { printf '\033[1;34m[i]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[+]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[E]\033[0m %s\n' "$*" >&2; exit 1; }

confirm() {
    read -rp "$* [y/N] " ans
    case "$ans" in [yY]|[yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}

# ============================================================================
# Phase 0: sanity
# ============================================================================
[[ "$(uname -s)" == "Linux" ]] || err "Linux only (got $(uname -s))"
[[ -f /etc/arch-release ]]     || err "/etc/arch-release missing — Arch only"
[[ $EUID -ne 0 ]]              || err "Run as your normal user (sudo elevation happens inside ansible)."

cat <<EOF

Gaming-desktop install for hostname '$(hostname)' as user '$USER'.

This will:
  1. Install ansible (if not already present)
  2. Run bootstrap.sh (portable: dotfiles, neovim, tmux, opencode tools)
  3. Run ansible/site.yml (gaming: packages, kernel cmdline, NVIDIA tuning,
     gamemode + polkit, gamewatcher service, bnetswitch build)

EOF
confirm "Proceed?" || { warn "User declined."; exit 0; }

# ============================================================================
# Phase 1: ensure ansible is present
# ============================================================================
if ! command -v ansible-playbook >/dev/null; then
    log "Installing ansible..."
    sudo pacman -S --needed --noconfirm ansible
    ok "ansible installed"
fi

# Required for `community.general.pacman` and other modules used in roles.
if ! ansible-galaxy collection list 2>/dev/null | grep -q '^community\.general'; then
    log "Installing ansible community.general collection..."
    ansible-galaxy collection install community.general
    ok "community.general installed"
fi

# ============================================================================
# Phase 2: portable bootstrap (dotfiles, etc.)
# ============================================================================
if [[ -x "$SCRIPT_DIR/bootstrap.sh" ]]; then
    log "Running portable bootstrap.sh..."
    "$SCRIPT_DIR/bootstrap.sh"
    ok "bootstrap.sh complete"
else
    warn "bootstrap.sh not executable; skipping. Did you forget to chmod +x?"
fi

# ============================================================================
# Phase 3: ansible playbook
# ============================================================================
log "Running ansible playbook..."
log "  Working directory: $SCRIPT_DIR/ansible"
log "  --ask-become-pass: prompts for sudo password once"
log "  --diff: shows file changes as they happen"
log ""

# Preserve cmdline args for partial runs:
#   ./install-gaming.sh --tags packages
#   ./install-gaming.sh --check          # dry-run
#   ./install-gaming.sh --skip-tags bnetswitch
cd "$SCRIPT_DIR/ansible"
exec ansible-playbook site.yml \
    --ask-become-pass \
    --diff \
    "$@"
