#!/bin/bash

# Get short hostname
_neo_mittens_short_hostname() {
    hostname -s 2>/dev/null || hostname | cut -d. -f1
}

# Check if we're on a remote host (via SSH)
_neo_mittens_is_remote() {
    [[ -n "${SSH_CONNECTION:-}" ]] || [[ -n "${SSH_CLIENT:-}" ]] || [[ -n "${SSH_TTY:-}" ]]
}

set_tmux_pane_title() {
    if command -v tmux &> /dev/null && [ -n "$TMUX" ]; then
        local title=""
        local git_root=$(git -C "$(pwd)" rev-parse --show-toplevel 2>/dev/null)
        local hostname_prefix=""

        # Add hostname prefix if we're on a remote host
        if _neo_mittens_is_remote; then
            hostname_prefix="[$(_neo_mittens_short_hostname)] "
        fi

        if [ -n "$git_root" ]; then
            title="${hostname_prefix}$(basename "$git_root")"
        else
            title="${hostname_prefix}$(basename "$(pwd)")"
        fi
        tmux select-pane -T "$title"
    fi
}
