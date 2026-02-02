# Tmux theme: Local (Catppuccin Mocha)
# Applied when on local machine or after SSH disconnect

# Pane styling
set-option -g pane-border-style 'fg=#6C7086'
set-option -g pane-active-border-style 'fg=#B4BEFE'

# Status bar colors - Catppuccin Mocha
set-option -g status-style 'bg=#1E1E2E,fg=#CDD6F4'

# Window status
set-option -g window-status-style 'fg=#6C7086,bg=#1E1E2E'
set-option -g window-status-current-style 'fg=#1E1E2E,bg=#89B4FA,bold'

# Message styling
set-option -g message-style 'bg=#CBA6F7,fg=#1E1E2E'
set-option -g message-command-style 'bg=#F38BA8,fg=#1E1E2E'

# Mode styling (copy mode, etc.)
set-option -g mode-style 'bg=#CBA6F7,fg=#1E1E2E'

# Clock mode
set-option -g clock-mode-colour '#89B4FA'
