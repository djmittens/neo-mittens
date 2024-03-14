#!/usr/bin/env bash

# Prompt the user to enter a name for the new workspace
 #WORKSPACE_NAME=$(rofi -dmenu -p "✅ New Workspace Name:")

# Create a new workspace with the specified name
# i3-msg "workspace \"$WORKSPACE_NAME\""


function gen_workspaces()
{
    i3-msg -t get_workspaces | tr ',' '\n' | grep "name" | sed 's/"name":"\(.*\)"/\1/g' | sort -n
}

# Change prompt
if [ ! -z "$@" ]; then

  if [[ "$@" == "New Workspace" ]] then
    echo "Code"
    echo "Notes"
    echo "Movies"
    echo "Porn"
    echo "Youtube"
    echo "Docs"

    echo -en "\0message\x1ffuck:\n"
    exit 0
  else
    coproc( i3-msg "workspace \"$@\"" > /dev/null 2>&1)
    exit 0
  fi
fi

echo "New Workspace"

gen_workspaces
