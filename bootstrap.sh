#! /usr/bin/env bash

set -euxo pipefail
mkdir -p $HOME/.config/nvim/lua
ln -s $PWD/lua $HOME/.config/nvim/lua/neo-mittens
ln -s $PWD/after $HOME/.config/nvim/after
printf '\nrequire("neo-mittens")' >> $HOME/.config/nvim/init.lua
