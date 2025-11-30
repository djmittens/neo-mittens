#!/bin/bash

set_tmux_pane_title() {
    if command -v tmux &> /dev/null && [ -n "$TMUX" ]; then
        local title=""
        local git_root=$(git -C "$(pwd)" rev-parse --show-toplevel 2>/dev/null)

        if [ -n "$git_root" ]; then
            title=$(basename "$git_root")
        else
            title=$(basename "$(pwd)")
        fi
        tmux select-pane -T "$title"
    fi
}
