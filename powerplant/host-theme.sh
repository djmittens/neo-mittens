#!/usr/bin/env bash
# host-theme.sh - Source this in your shell rc file
# Automatically applies host-specific themes based on hostname
#
# Add to .zshrc or .bashrc:
#   source /path/to/neo-mittens/powerplant/host-theme.sh

# Host-to-theme mapping (matches ssh-themed)
declare -A HOST_THEMES=(
    ["obelisk"]="obelisk"
    # Add more hosts here
)

LOCAL_HOSTS=("your-laptop" "your-desktop")  # Add your local machine hostnames
DEFAULT_THEME="local"

KITTY_THEMES_DIR="${HOME}/.config/kitty/themes"
TMUX_THEMES_DIR="${HOME}/.config/tmux/themes"

# Get current hostname (short form)
_get_short_hostname() {
    hostname -s 2>/dev/null || hostname | cut -d. -f1
}

# Check if we're on a local machine
_is_local_host() {
    local current_host
    current_host=$(_get_short_hostname)
    for local_host in "${LOCAL_HOSTS[@]}"; do
        [[ "$current_host" == "$local_host" ]] && return 0
    done
    return 1
}

# Get theme for current host
_get_current_host_theme() {
    local current_host
    current_host=$(_get_short_hostname)
    
    # Check explicit mapping
    if [[ -n "${HOST_THEMES[$current_host]:-}" ]]; then
        echo "${HOST_THEMES[$current_host]}"
        return
    fi
    
    # Check if local
    if _is_local_host; then
        echo "$DEFAULT_THEME"
        return
    fi
    
    # Default for unknown remote hosts - use a generic remote theme
    # You could create a "remote" theme as a fallback
    echo "${HOST_THEMES[$current_host]:-$DEFAULT_THEME}"
}

# Apply kitty theme (if in kitty)
_apply_kitty_host_theme() {
    local theme="$1"
    local theme_file="${KITTY_THEMES_DIR}/${theme}.conf"
    
    # Only apply if we're in kitty and theme file exists
    if [[ -n "${KITTY_WINDOW_ID:-}" ]] && [[ -f "$theme_file" ]]; then
        kitty @ set-colors --all "$theme_file" 2>/dev/null || true
    fi
}

# Apply tmux theme (if in tmux)
_apply_tmux_host_theme() {
    local theme="$1"
    local theme_file="${TMUX_THEMES_DIR}/${theme}.tmux"
    
    if [[ -n "${TMUX:-}" ]] && [[ -f "$theme_file" ]]; then
        tmux source-file "$theme_file" 2>/dev/null || true
    fi
}

# Main function to apply host theme
apply_host_theme() {
    local theme
    theme=$(_get_current_host_theme)
    _apply_kitty_host_theme "$theme"
    _apply_tmux_host_theme "$theme"
}

# Export for use in prompts
export NEO_MITTENS_HOST_THEME=$(_get_current_host_theme)

# Auto-apply on shell startup (optional - comment out if you only want ssh-themed wrapper)
# apply_host_theme
