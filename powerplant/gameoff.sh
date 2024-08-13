#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
# Re-enable 2º screen
xrandr --output HDMI-0 --auto
xrandr --output DP-4 --auto

# Re-enable composition pipeline
nvidia-settings --assign CurrentMetaMode="DP-4: 7680x2160_60 +0+0 {ForceCompositionPipeline=On, AllowGSYNCCompatible=On}, HDMI-0: nvidia-auto-select +7680+0 {ForceCompositionPipeline=On}"

# Re-enable your compositor
# picom -f --config ~/.config/picom/picom.conf --experimental-backends &
#
$SCRIPT_DIR/workspace-switcher.py stardeck
