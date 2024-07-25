#!/usr/bin/env bash

# Prompt the user to enter a name for the new workspace

# Create a new workspace with the specified name
# i3-msg "workspace \"$WORKSPACE_NAME\""


function gen_workspaces()
{
  # i3-msg -t get_workspaces | tr ',' '\n' | grep "name" | sed 's/"name":"\(.*\)"/\1/g' | sort -n
  i3-msg -t get_workspaces | jq -r '.[] | "\(.focused) \(.name)"' | sort -r | awk '{print $2,"\0icon\x1fwindows95\x1finfo\x1f", $2}'
}

# echo -en "aap\0icon\x1ffolder\n"
if [ ! -z "$ROFI_INFO" ]; then
    coproc( i3-msg workspace "$ROFI_INFO" > /dev/null 2>&1)
    exit 0
fi

# Change prompt
if [ ! -z "$@" ]; then

  if [[ "$@" == "New Workspace"* ]]; then
    echo "Code"
    echo "Notes"
    echo "Movies"
    echo "Porn"
    echo "Youtube"
    echo "Docs"

    # echo -en "\0message\x1ffuck:\n"
    exit 0
  else
    coproc( i3-msg workspace "$@" > /dev/null 2>&1)
    exit 0
  fi
fi


gen_workspaces

echo -e "New Workspace" "\0icon\x1fuos-windesk"
