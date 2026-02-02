# Tmux theme: Obelisk (volcanic/crimson server theme)
# Applied when SSH'd into obelisk server

# Pane styling - volcanic orange/red borders
set-option -g pane-border-style 'fg=#3D2B2B'
set-option -g pane-active-border-style 'fg=#D64933,bold'

# Status bar colors - dark obsidian with ember accents
set-option -g status-style 'bg=#0D0A0B,fg=#E8D4C4'

# Window status - warm/volcanic colors
set-option -g window-status-style 'fg=#A68B7C,bg=#0D0A0B'
set-option -g window-status-current-style 'fg=#0D0A0B,bg=#D64933,bold'

# Message styling
set-option -g message-style 'bg=#FF6B35,fg=#0D0A0B'
set-option -g message-command-style 'bg=#D64933,fg=#0D0A0B'

# Mode styling (copy mode, etc.)
set-option -g mode-style 'bg=#D64933,fg=#E8D4C4'

# Clock mode
set-option -g clock-mode-colour '#FF6B35'
