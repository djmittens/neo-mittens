#!/bin/bash
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Disable compositor
pkill -9 picom

# Disable composition pipeline and enable G-sync/Freesync
nvidia-settings --assign CurrentMetaMode="DP-4: nvidia-auto-select {ForceCompositionPipeline=Off, AllowGSYNCCompatible=On}, HDMI-0: 2560x1440_120 +0+0 {ForceCompositionPipeline=Off, AllowGSYNCCompatible=On}"

$SCRIPT_DIR/workspace-switcher.py none
#Disable 2º screen
xrandr --output DP-4 --off
