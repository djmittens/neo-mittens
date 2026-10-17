#!/bin/bash
# Completely remove mt7925e before suspend; reattach after resume
DEVICE="0000:09:00.0"
DRIVER_PATH="/sys/bus/pci/drivers/mt7925e"

case "$1" in
  pre)
    if [ -e "$DRIVER_PATH/unbind" ]; then
      echo "$DEVICE" > "$DRIVER_PATH/unbind"
    fi
    ;;
  post)
    if [ -e "$DRIVER_PATH/bind" ]; then
      echo "$DEVICE" > "$DRIVER_PATH/bind"
    fi
    ;;
esac

exit 0

