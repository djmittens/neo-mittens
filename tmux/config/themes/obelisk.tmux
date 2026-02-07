# Tmux theme: Obelisk (volcanic/crimson server theme)
# Applied automatically when running on obelisk server
# Visually distinct from local Catppuccin - you know you're on the server

# Status bar - deep obsidian with ember accents
set-option -g status-style 'bg=#1A1415,fg=#E8D4C4'
set-option -g status-left-length 30
set-option -g status-right-length 60

# Left: session name with ember background
set-option -g status-left '#[bg=#D64933,fg=#0D0A0B,bold] #S #[bg=#1A1415,fg=#D64933]'

# Right: hostname prominent + time
set-option -g status-right '#[fg=#4A3C3C]#[bg=#4A3C3C,fg=#E8D4C4] %H:%M #[fg=#D64933]#[bg=#D64933,fg=#0D0A0B,bold] #H '

# Window status - pane title (#T) set by shell hook
set-option -g window-status-format '#[fg=#6B5555] #I:#T '
set-option -g window-status-current-format '#[fg=#1A1415,bg=#D64933]#[bg=#D64933,fg=#0D0A0B,bold] #I:#T #[fg=#D64933,bg=#1A1415]'

# Pane borders - ember accent
set-option -g pane-border-style 'fg=#3D2B2B'
set-option -g pane-active-border-style 'fg=#D64933'

# Message styling
set-option -g message-style 'bg=#D64933,fg=#0D0A0B,bold'
set-option -g message-command-style 'bg=#FF6B35,fg=#0D0A0B'

# Mode styling (copy mode, etc.)
set-option -g mode-style 'bg=#D64933,fg=#E8D4C4'

# Clock
set-option -g clock-mode-colour '#FF6B35'
