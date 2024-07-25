#!/usr/bin/env bash

# Prompt the user to enter a name for the new workspace
# WORKSPACE_NAME=$(rofi -dmenu -p "✅ New Workspace Name:")

# Create a new workspace with the specified name
# i3-msg "workspace \"$WORKSPACE_NAME\""


function gen_workspaces()
{
    i3-msg -t get_workspaces | tr ',' '\n' | grep "name" | sed 's/"name":"\(.*\)"/\1/g' | sort -n
}

# Get the list of workspaces and sort them by the most recently used (by 'focused' property)
workspaces=$(i3-msg -t get_workspaces | jq -r '.[] | "\(.focused) \(.name)"' | sort -r | awk '{print $2}')

# Change prompt
if [ ! -z "$@" ]; then

  if [[ "$@" == "Select Workspace" ]] then
    echo "$workspaces"

    echo -en "\0message\x1ffuck:\n"
    exit 0
  else
    coproc( i3-msg "workspace \"$@\"" > /dev/null 2>&1)
    exit 0
  fi
fi

echo "Select Workspace"


