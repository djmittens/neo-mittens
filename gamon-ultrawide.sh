#!/bin/bash

# Disable compositor
pkill -9 picom

# Disable composition pipeline and enable G-sync/Freesync
nvidia-settings --assign CurrentMetaMode="DP-4: 5120x1440_240 +5120+0 {ForceCompositionPipeline=Off, AllowGSYNCCompatible=On}, HDMI-0: nvidia-auto-select +0+0 {ForceCompositionPipeline=Off}"

#Disable 2º screen
xrandr --output HDMI-0 --off
