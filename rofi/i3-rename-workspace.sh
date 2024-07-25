#!/bin/bash

# Get the current workspace
current_workspace=$(i3-msg -t get_workspaces | jq -r '.[] | select(.focused) | .name')

# Prompt for the new name using rofi
new_name=$(echo "" | rofi -dmenu -p "Rename workspace:"  )

# Check if a new name was entered
if [ -n "$new_name" ]; then
  # Rename the workspace
  i3-msg rename workspace "$current_workspace" to "$new_name"
else
  echo "No new name entered."
fi
