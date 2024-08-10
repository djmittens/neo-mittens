#!/bin/bash

# Re-enable 2º screen
xrandr --output HDMI-0 --auto

# Re-enable composition pipeline
nvidia-settings --assign CurrentMetaMode="DP-4: 7680x2160_60 -7680+0 {ForceCompositionPipeline=On, AllowGSYNCCompatible=On}, HDMI-0: nvidia-auto-select +0+0 {ForceCompositionPipeline=On}"

# Re-enable your compositor
# picom -f --config ~/.config/picom/picom.conf --experimental-backends &
#
./workspace-switcher.py stardeck
