#! /usr/bin/env bash

set -euo pipefail

# Idempotent bootstrap for neo-mittens
# - Symlinks this repo's Neovim config into ~/.config/nvim
# - Ensures require("neo-mittens") is present in ~/.config/nvim/init.lua
# - Adds this repo's powerplant dir to PATH via a managed block in ~/.profile
# - Disables ohmyzsh auto-title and sets up custom tmux pane titles
# - Symlinks Hyprland config to ~/.config/hypr and Rofi config to ~/.config/rofi
# - Symlinks tmux config (both XDG ~/.config/tmux and ~/.tmux.conf)
# - Ensures TPM exists and installs plugins (Catppuccin via TPM)

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"

NVIM_DIR="$HOME/.config/nvim"
NVIM_LUA_DIR="$NVIM_DIR/lua"

ensure_dir() {
  mkdir -p "$1"
}

link_symlink() {
  local src="$1"
  local dest="$2"

  # If source does not exist, skip linking
  if [ ! -e "$src" ]; then
    echo "SKIP: source missing $src"
    return 0
  fi

  # If dest is already a symlink to src, do nothing
  if [ -L "$dest" ] && [ "$(readlink -f -- "$dest")" = "$(readlink -f -- "$src")" ]; then
    echo "OK: $dest already links to $src"
    return 0
  fi

  # If dest exists but is not a symlink, skip for safety
  if [ -e "$dest" ] && [ ! -L "$dest" ]; then
    echo "SKIP: $dest exists and is not a symlink"
    return 0
  fi

  # Create/replace symlink
  rm -f -- "$dest"
  ln -s -- "$src" "$dest"
  echo "LINK: $dest -> $src"
}

append_require_if_missing() {
  local init_lua="$1"
  local req='require("neo-mittens")'

  # Create file if missing
  if [ ! -f "$init_lua" ]; then
    printf "%s\n" "$req" >"$init_lua"
    echo "WRITE: $init_lua (created with neo-mittens require)"
    return 0
  fi

  # Only append if not present
  if ! grep -Fq "$req" "$init_lua"; then
    printf "\n%s\n" "$req" >>"$init_lua"
    echo "APPEND: $req to $init_lua"
  else
    echo "OK: $req already present in $init_lua"
  fi
}

install_path_block() {
  local profile_file="$1"
  local pp_dir="$2"

  ensure_dir "$(dirname -- "$profile_file")"

  local begin='# >>> neo-mittens powerplant >>>'
  local end='# <<< neo-mittens powerplant <<<'
  local block
  block="${begin}
if [ -d \"${pp_dir}\" ] && [[ :\$PATH: != *:${pp_dir}:* ]]; then
  export PATH=\"\$PATH:${pp_dir}\"
fi
${end}"

  if [ -f "$profile_file" ] && grep -Fq "$begin" "$profile_file"; then
    # Replace existing managed block
    tmp="$(mktemp)"
    awk -v b="$begin" -v e="$end" '
      BEGIN{inb=0}
      $0==b {inb=1; next}
      $0==e {inb=0; next}
      inb==0 {print}
    ' "$profile_file" >"$tmp"
    printf "\n%s\n" "$block" >>"$tmp"
    # Use copy-overwrite to avoid cross-device mv issues
    cat "$tmp" > "$profile_file"
    echo "UPDATE: Managed PATH block in $profile_file"
  else
    # Append new block (file may or may not exist)
    printf "\n%s\n" "$block" >>"$profile_file"
    echo "ADD: Managed PATH block to $profile_file"
  fi
}

# tmux helpers
ensure_tpm() {
  local tpm_dir="$HOME/.tmux/plugins/tpm"
  if [ -d "$tpm_dir" ]; then
    echo "OK: TPM already installed at $tpm_dir"
    return 0
  fi

  if command -v git >/dev/null 2>&1; then
    echo "Installing TPM to $tpm_dir"
    git clone https://github.com/tmux-plugins/tpm "$tpm_dir" || {
      echo "WARN: Failed to clone TPM (check network)."; return 0; }
  else
    echo "SKIP: git not found; cannot install TPM automatically."
  fi
}

# Resolve which tmux.conf to use and ensure it exists
resolve_tmux_conf_path() {
  if [ -f "$HOME/.tmux.conf" ]; then
    printf '%s' "$HOME/.tmux.conf"
    return 0
  fi
  if [ -f "$HOME/.config/tmux/tmux.conf" ]; then
    printf '%s' "$HOME/.config/tmux/tmux.conf"
    return 0
  fi
  ensure_dir "$HOME/.config/tmux"
  if [ -f "$SCRIPT_DIR/tmux/config/tmux.conf" ]; then
    cp -a "$SCRIPT_DIR/tmux/config/tmux.conf" "$HOME/.config/tmux/tmux.conf"
    echo "WRITE: Seeded ~/.config/tmux/tmux.conf from repo"
  else
    : > "$HOME/.config/tmux/tmux.conf"
    echo "WRITE: Created empty ~/.config/tmux/tmux.conf"
  fi
  printf '%s' "$HOME/.config/tmux/tmux.conf"
}

# Ensure a managed TPM block exists in the chosen tmux.conf
ensure_tmux_tpm_block() {
  local conf
  conf="$(resolve_tmux_conf_path)"
  local begin='# >>> neo-mittens tpm >>>'
  local end='# <<< neo-mittens tpm <<<'
  local block
  block="${begin}
set-environment -g TMUX_PLUGIN_MANAGER_PATH '~/.tmux/plugins'
set -g @plugin 'tmux-plugins/tpm'
set -g @plugin 'catppuccin/tmux'
run -b '~/.tmux/plugins/tpm/tpm'
${end}"

  if [ -f "$conf" ] && grep -Fq "$begin" "$conf"; then
    tmp="$(mktemp)"
    awk -v b="$begin" -v e="$end" '
      BEGIN{inb=0}
      $0==b {inb=1; next}
      $0==e {inb=0; next}
      inb==0 {print}
    ' "$conf" >"$tmp"
    printf "\n%s\n" "$block" >>"$tmp"
    mv -- "$tmp" "$conf"
    echo "UPDATE: Managed TPM block in $conf"
  else
    printf "\n%s\n" "$block" >>"$conf"
    echo "ADD: Managed TPM block to $conf"
  fi

  # Ensure ~/.tmux.conf sources XDG if main conf is XDG path and no ~/.tmux.conf
  if [ "$conf" = "$HOME/.config/tmux/tmux.conf" ] && [ ! -f "$HOME/.tmux.conf" ]; then
    {
      echo "# >>> neo-mittens tmux entrypoint >>>"
      echo "source-file -q ~/.config/tmux/tmux.conf"
      echo "# <<< neo-mittens tmux entrypoint <<<"
    } > "$HOME/.tmux.conf"
    echo "WRITE: Created ~/.tmux.conf to source XDG config"
  fi
}

install_tmux_plugins_if_possible() {
  local tpm_dir="$HOME/.tmux/plugins/tpm"
  local conf
  conf="$(resolve_tmux_conf_path)"
  # Only try if tmux and TPM exist
  if ! command -v tmux >/dev/null 2>&1; then
    echo "SKIP: tmux not found; cannot auto-install plugins."
    return 0
  fi
  if [ ! -d "$tpm_dir" ]; then
    echo "SKIP: TPM not found; cannot auto-install plugins."
    return 0
  fi

  # Prefer bin helper, fallback to scripts path
  local installer=""
  if [ -x "$tpm_dir/bin/install_plugins" ]; then
    installer="$tpm_dir/bin/install_plugins"
  elif [ -x "$tpm_dir/scripts/install_plugins.sh" ]; then
    installer="$tpm_dir/scripts/install_plugins.sh"
  fi

  if [ -n "$installer" ]; then
    echo "Installing tmux plugins via TPM (using $conf)"
    # Start server with our conf and set the env var in tmux itself
    tmux -f "$conf" start-server >/dev/null 2>&1 || true
    tmux -f "$conf" set-environment -g TMUX_PLUGIN_MANAGER_PATH "$HOME/.tmux/plugins" >/dev/null 2>&1 || true
    tmux -f "$conf" new-session -d -s _tpm_bootstrap 'sleep 0.2' >/dev/null 2>&1 || true
    "$installer" || echo "WARN: Plugin install script returned non-zero."
    tmux kill-session -t _tpm_bootstrap >/dev/null 2>&1 || true
  else
    echo "SKIP: TPM installer script not found."
  fi
}

disable_omz_auto_title() {
  local zshrc_file="$HOME/.zshrc"
  
  if [ ! -f "$zshrc_file" ]; then
    echo "SKIP: ~/.zshrc not found, cannot disable ohmyzsh auto-title"
    return 0
  fi

  # Check if DISABLE_AUTO_TITLE is already set (uncommented)
  if grep -q '^DISABLE_AUTO_TITLE=' "$zshrc_file"; then
    echo "OK: DISABLE_AUTO_TITLE already set in $zshrc_file"
    return 0
  fi

  # Try to uncomment the existing line
  if grep -q '# DISABLE_AUTO_TITLE="true"' "$zshrc_file"; then
    sed -i.bak 's/# DISABLE_AUTO_TITLE="true"/DISABLE_AUTO_TITLE="true"/' "$zshrc_file"
    echo "UPDATE: Uncommented DISABLE_AUTO_TITLE in $zshrc_file"
    return 0
  fi

  # If ohmyzsh is detected but no DISABLE_AUTO_TITLE line exists, add it after ZSH_THEME
  if grep -q 'ZSH_THEME=' "$zshrc_file"; then
    tmp="$(mktemp)"
    awk '/^ZSH_THEME=/ {print; print ""; print "# Disable ohmyzsh auto-title to allow custom tmux pane titles"; print "DISABLE_AUTO_TITLE=\"true\""; next} {print}' "$zshrc_file" > "$tmp"
    cat "$tmp" > "$zshrc_file"
    echo "ADD: DISABLE_AUTO_TITLE after ZSH_THEME in $zshrc_file"
  else
    echo "SKIP: No ohmyzsh detected in $zshrc_file"
  fi
}

install_zsh_pane_title_block() {
  local zshrc_file="$HOME/.zshrc"
  local script_path="$SCRIPT_DIR/powerplant/set_tmux_pane_title.sh"

  ensure_dir "$(dirname -- "$zshrc_file")"

  local begin='# >>> neo-mittens tmux pane title >>>'
  local end='# <<< neo-mittens tmux pane title <<<'
  local block
  block="${begin}
if [ -f \"${script_path}\" ]; then
  source \"${script_path}\"
  precmd_functions+=(set_tmux_pane_title)
fi
${end}"

  if [ -f "$zshrc_file" ] && grep -Fq "$begin" "$zshrc_file"; then
    # Replace existing managed block
    tmp="$(mktemp)"
    awk -v b="$begin" -v e="$end" '
      BEGIN{inb=0}
      $0==b {inb=1; next}
      $0==e {inb=0; next}
      inb==0 {print}
    ' "$zshrc_file" >"$tmp"
    printf "\n%s\n" "$block" >>"$tmp"
    # Use copy-overwrite to avoid cross-device mv issues
    cat "$tmp" > "$zshrc_file"
    echo "UPDATE: Managed tmux pane title block in $zshrc_file"
  else
    # Append new block (file may or may not exist)
    printf "\n%s\n" "$block" >>"$zshrc_file"
    echo "ADD: Managed tmux pane title block to $zshrc_file"
  fi
}

# 1) Ensure config directories exist
ensure_dir "$HOME/.config"
ensure_dir "$NVIM_LUA_DIR"

# 2) Link lua module namespace
link_symlink "$SCRIPT_DIR/lua"   "$NVIM_LUA_DIR/neo-mittens"

# 3) Ensure init.lua requires neo-mittens
append_require_if_missing "$NVIM_DIR/init.lua"

# 4) Add powerplant to PATH via managed block
install_path_block "$HOME/.profile" "$SCRIPT_DIR/powerplant"

# 5) Disable ohmyzsh auto-title to allow custom tmux pane titles
disable_omz_auto_title

# 6) Add tmux pane title block to ~/.zshrc
install_zsh_pane_title_block

# 7) Link Hyprland and Rofi configs
link_symlink "$SCRIPT_DIR/hypr" "$HOME/.config/hypr"
link_symlink "$SCRIPT_DIR/rofi" "$HOME/.config/rofi"
link_symlink "$SCRIPT_DIR/wofi" "$HOME/.config/wofi"

# 8) Install Wofi power .desktop entries into XDG applications
if [ -d "$SCRIPT_DIR/wofi/applications" ]; then
  ensure_dir "$HOME/.local/share/applications"
  link_symlink "$SCRIPT_DIR/wofi/applications" "$HOME/.local/share/applications/wofi-sys"
fi

# 9) Link Waybar config (if present in repo)
link_symlink "$SCRIPT_DIR/waybar" "$HOME/.config/waybar"

# 10) Link tmux configs (if present in repo)
link_symlink "$SCRIPT_DIR/tmux/config" "$HOME/.config/tmux"
link_symlink "$SCRIPT_DIR/tmux/tmux.conf" "$HOME/.tmux.conf"

# 11) Ensure TPM + plugins (Catppuccin via TPM in tmux.conf)
ensure_tpm
ensure_tmux_tpm_block
install_tmux_plugins_if_possible

echo "Done. You may need to restart your shell (or source ~/.profile) and restart Neovim."
