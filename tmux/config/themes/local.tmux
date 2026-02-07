# Tmux theme: Local (Catppuccin Mocha)
# Applied on local machines - uses Catppuccin plugin for styling

# Pane styling - Catppuccin Mocha colors
set-option -g pane-border-style 'fg=#6C7086'
set-option -g pane-active-border-style 'fg=#B4BEFE'

# Status bar - let Catppuccin plugin handle most of this
set-option -g status-left '#{E:@catppuccin_status_session}'
set-option -g status-right '#{E:@catppuccin_status_application}'

# Window status formatting for Catppuccin
set-option -g @catppuccin_window_status_base '#[fg=#CDD6F4,bg=#1E1E2E] #T '
set-option -g @catppuccin_window_status_current_format '#[fg=#1E1E2E,bg=#89B4FA,bold]#[fg=#1E1E2E,bg=#89B4FA] #T #[fg=#89B4FA,bg=#1E1E2E,nobold]'

# Message styling
set-option -g message-style 'bg=#CBA6F7,fg=#1E1E2E'
set-option -g message-command-style 'bg=#F38BA8,fg=#1E1E2E'

# Mode styling (copy mode, etc.)
set-option -g mode-style 'bg=#CBA6F7,fg=#1E1E2E'

# Clock mode
set-option -g clock-mode-colour '#89B4FA'
