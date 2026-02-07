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
# - powerplant/ contains ralph and gcai (AI-assisted git commits)

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"

# Resolve the active zshrc path - respects ZDOTDIR if set, otherwise ~/.zshrc
resolve_zshrc_path() {
  # Check ZDOTDIR first (set in ~/.zshenv for XDG-style setups)
  if [ -n "${ZDOTDIR:-}" ] && [ -d "$ZDOTDIR" ]; then
    printf '%s' "$ZDOTDIR/.zshrc"
    return 0
  fi
  
  # Check common XDG locations even if ZDOTDIR isn't set in current env
  # (it might be set in .zshenv which bash doesn't read)
  for xdg_path in "$HOME/.config/zsh" "$HOME/.zsh"; do
    if [ -f "$xdg_path/.zshrc" ]; then
      printf '%s' "$xdg_path/.zshrc"
      return 0
    fi
  done
  
  # Default to standard location
  printf '%s' "$HOME/.zshrc"
}

# Cache the resolved zshrc path for the entire script
ZSHRC_PATH="$(resolve_zshrc_path)"

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

install_pythonpath_block() {
  local profile_file="$1"
  local repo_root="$2"

  ensure_dir "$(dirname -- "$profile_file")"

  local begin='# >>> neo-mittens pythonpath >>>'
  local end='# <<< neo-mittens pythonpath <<<'
  local block
  block="${begin}
if [ -d \"${repo_root}\" ] && [[ :\$PYTHONPATH: != *:${repo_root}:* ]]; then
  export PYTHONPATH=\"${repo_root}\${PYTHONPATH:+:\$PYTHONPATH}\"
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
    echo "UPDATE: Managed PYTHONPATH block in $profile_file"
  else
    # Append new block (file may or may not exist)
    printf "\n%s\n" "$block" >>"$profile_file"
    echo "ADD: Managed PYTHONPATH block to $profile_file"
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
  
  # Skip if TPM is already configured (with or without our managed block)
  if [ -f "$conf" ] && grep -q "run.*tpm/tpm" "$conf" && ! grep -Fq "# >>> neo-mittens tpm >>>" "$conf"; then
    echo "OK: TPM already configured in $conf"
    return 0
  fi

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
  local zshrc_file="$ZSHRC_PATH"
  
  if [ ! -f "$zshrc_file" ]; then
    echo "SKIP: $zshrc_file not found, cannot disable ohmyzsh auto-title"
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
  local zshrc_file="$ZSHRC_PATH"
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

install_ssh_themed_alias() {
  local zshrc_file="$ZSHRC_PATH"
  local ssh_themed="$SCRIPT_DIR/powerplant/ssh-themed"

  ensure_dir "$(dirname -- "$zshrc_file")"

  local begin='# >>> neo-mittens ssh-themed >>>'
  local end='# <<< neo-mittens ssh-themed <<<'
  local block
  block="${begin}
# Use ssh-themed wrapper for automatic per-host terminal theming
if [ -x \"${ssh_themed}\" ]; then
  alias ssh='${ssh_themed}'
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
    cat "$tmp" > "$zshrc_file"
    echo "UPDATE: Managed ssh-themed alias in $zshrc_file"
  else
    printf "\n%s\n" "$block" >>"$zshrc_file"
    echo "ADD: Managed ssh-themed alias to $zshrc_file"
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
install_path_block "$ZSHRC_PATH" "$SCRIPT_DIR/powerplant"

# 4b) Add repo root and app/ to PYTHONPATH for ralph package imports
install_pythonpath_block "$HOME/.profile" "$SCRIPT_DIR"
install_pythonpath_block "$ZSHRC_PATH" "$SCRIPT_DIR"
install_pythonpath_block "$HOME/.profile" "$SCRIPT_DIR/app"
install_pythonpath_block "$ZSHRC_PATH" "$SCRIPT_DIR/app"

# 5) Disable ohmyzsh auto-title to allow custom tmux pane titles
disable_omz_auto_title

# 6) Add tmux pane title block to ~/.zshrc
install_zsh_pane_title_block

# 6b) Add ssh-themed alias for automatic terminal theming on SSH
install_ssh_themed_alias

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

# 10b) Link kitty config (if present in repo)
link_symlink "$SCRIPT_DIR/kitty" "$HOME/.config/kitty"

# 11) Ensure TPM + plugins (Catppuccin via TPM in tmux.conf)
ensure_tpm
ensure_tmux_tpm_block
install_tmux_plugins_if_possible

# 12) Link gdbinit and add auto-load safe path
link_symlink "$SCRIPT_DIR/gdbinit" "$HOME/.gdbinit"

# 13) Setup global gitignore for common build artifacts
GLOBAL_GITIGNORE="$HOME/.gitignore_global"
git config --global core.excludesfile "$GLOBAL_GITIGNORE"
# Add common patterns if not present
for pattern in "target/" ".bsp/" ".metals/" ".bloop/" "*.class" "*.jar"; do
  if ! grep -qF "$pattern" "$GLOBAL_GITIGNORE" 2>/dev/null; then
    echo "$pattern" >> "$GLOBAL_GITIGNORE"
  fi
done

# 14) bin/ PATH block removed - gcai moved to powerplant/ which is already in PATH

# 15) Install global Claude commands (ralph alias)
CLAUDE_COMMANDS_DIR="$HOME/.claude/commands"
ensure_dir "$CLAUDE_COMMANDS_DIR"
for cmd in "$SCRIPT_DIR/.claude/commands"/ralph-*.md; do
  if [ -f "$cmd" ]; then
    link_symlink "$cmd" "$CLAUDE_COMMANDS_DIR/$(basename "$cmd")"
  fi
done

# 16) Install ralph shell completions
install_ralph_completion_bash() {
  local bashrc="$HOME/.bashrc"
  local completion_file="$SCRIPT_DIR/powerplant/ralph-completion.bash"
  
  if [ ! -f "$completion_file" ]; then
    echo "SKIP: ralph bash completion not found"
    return 0
  fi
  
  local begin='# >>> neo-mittens ralph completion >>>'
  local end='# <<< neo-mittens ralph completion <<<'
  local block
  block="${begin}
[ -f \"${completion_file}\" ] && source \"${completion_file}\"
${end}"

  if [ -f "$bashrc" ] && grep -Fq "$begin" "$bashrc"; then
    tmp="$(mktemp)"
    awk -v b="$begin" -v e="$end" '
      BEGIN{inb=0}
      $0==b {inb=1; next}
      $0==e {inb=0; next}
      inb==0 {print}
    ' "$bashrc" >"$tmp"
    printf "\n%s\n" "$block" >>"$tmp"
    cat "$tmp" > "$bashrc"
    echo "UPDATE: ralph bash completion in $bashrc"
  else
    printf "\n%s\n" "$block" >>"$bashrc"
    echo "ADD: ralph bash completion to $bashrc"
  fi
}

install_ralph_completion_zsh() {
  local zshrc="$ZSHRC_PATH"
  local completion_file="$SCRIPT_DIR/powerplant/ralph-completion.zsh"
  
  if [ ! -f "$completion_file" ]; then
    echo "SKIP: ralph zsh completion not found"
    return 0
  fi
  
  local begin='# >>> neo-mittens ralph completion >>>'
  local end='# <<< neo-mittens ralph completion <<<'
  local block
  block="${begin}
[ -f \"${completion_file}\" ] && source \"${completion_file}\"
${end}"

  if [ -f "$zshrc" ] && grep -Fq "$begin" "$zshrc"; then
    tmp="$(mktemp)"
    awk -v b="$begin" -v e="$end" '
      BEGIN{inb=0}
      $0==b {inb=1; next}
      $0==e {inb=0; next}
      inb==0 {print}
    ' "$zshrc" >"$tmp"
    printf "\n%s\n" "$block" >>"$tmp"
    cat "$tmp" > "$zshrc"
    echo "UPDATE: ralph zsh completion in $zshrc"
  else
    printf "\n%s\n" "$block" >>"$zshrc"
    echo "ADD: ralph zsh completion to $zshrc"
  fi
}

install_ralph_completion_bash
install_ralph_completion_zsh

# 17) Install textual for ralph TUI (optional, best-effort)
install_ralph_textual() {
  # Check if textual is already available
  if python3 -c "import textual" 2>/dev/null; then
    echo "OK: textual already installed"
    return 0
  fi

  # Try various pip methods
  local pip_cmd=""
  if command -v pip3 >/dev/null 2>&1; then
    pip_cmd="pip3"
  elif command -v pip >/dev/null 2>&1; then
    pip_cmd="pip"
  elif python3 -m pip --version >/dev/null 2>&1; then
    pip_cmd="python3 -m pip"
  fi

  if [ -n "$pip_cmd" ]; then
    echo "Installing textual for ralph TUI..."
    $pip_cmd install --user textual 2>/dev/null && echo "OK: textual installed" || echo "SKIP: textual install failed (ralph will use fallback TUI)"
  else
    # Try system package managers
    if command -v pacman >/dev/null 2>&1; then
      echo "HINT: Install textual with: sudo pacman -S python-textual"
    elif command -v apt >/dev/null 2>&1; then
      echo "HINT: Install textual with: pip3 install --user textual"
    elif command -v brew >/dev/null 2>&1; then
      echo "HINT: Install textual with: pip3 install textual"
    else
      echo "SKIP: No pip found, ralph will use fallback TUI (install textual for smoother experience)"
    fi
  fi
}

install_ralph_textual

# 17b) Install mypy for type checking (optional, best-effort)
install_mypy() {
  # Check if mypy is already available (either as module or binary)
  if command -v mypy >/dev/null 2>&1; then
    echo "OK: mypy already installed"
    return 0
  fi

  # On macOS, prefer brew to avoid externally-managed-environment issues
  if command -v brew >/dev/null 2>&1; then
    echo "Installing mypy via brew..."
    brew install mypy 2>/dev/null && echo "OK: mypy installed via brew" && return 0
  fi

  # Try various pip methods
  local pip_cmd=""
  if command -v pip3 >/dev/null 2>&1; then
    pip_cmd="pip3"
  elif command -v pip >/dev/null 2>&1; then
    pip_cmd="pip"
  elif python3 -m pip --version >/dev/null 2>&1; then
    pip_cmd="python3 -m pip"
  fi

  if [ -n "$pip_cmd" ]; then
    echo "Installing mypy for type checking..."
    $pip_cmd install --user mypy 2>/dev/null && echo "OK: mypy installed" || echo "SKIP: mypy install failed"
  else
    echo "SKIP: No pip/brew found, install mypy manually with: brew install mypy"
  fi
}

install_mypy

# 17c) Install tree-sitter-cli for nvim-treesitter (required for new API)
install_tree_sitter_cli() {
  if command -v tree-sitter >/dev/null 2>&1; then
    echo "OK: tree-sitter-cli already installed"
    return 0
  fi

  # Try package managers (failures are non-fatal)
  if command -v brew >/dev/null 2>&1; then
    echo "Installing tree-sitter via brew..."
    if brew install tree-sitter 2>/dev/null; then
      echo "OK: tree-sitter installed via brew"
      return 0
    fi
  fi

  if command -v pacman >/dev/null 2>&1; then
    echo "Installing tree-sitter-cli via pacman..."
    if sudo pacman -S tree-sitter-cli; then
      echo "OK: tree-sitter installed via pacman"
      return 0
    fi
  fi

  # Fallback hints (not an error, just guidance)
  echo "HINT: Install tree-sitter-cli for nvim-treesitter parser compilation:"
  if command -v pacman >/dev/null 2>&1; then
    echo "  sudo pacman -S tree-sitter-cli"
  elif command -v brew >/dev/null 2>&1; then
    echo "  brew install tree-sitter"
  elif command -v cargo >/dev/null 2>&1; then
    echo "  cargo install tree-sitter-cli"
  elif command -v npm >/dev/null 2>&1; then
    echo "  npm install -g tree-sitter-cli"
  fi
  return 0  # Always succeed - this is optional
}

install_tree_sitter_cli

# 18) Install global OpenCode tools (to ~/.config/opencode/tools/)
OPENCODE_CONFIG_DIR="$HOME/.config/opencode"
OPENCODE_TOOLS_DIR="$OPENCODE_CONFIG_DIR/tools"
ensure_dir "$OPENCODE_TOOLS_DIR"

# Link tool files from .opencode/tools/ to ~/.config/opencode/tools/
for tool_file in "$SCRIPT_DIR/.opencode/tools"/*.ts; do
  if [ -f "$tool_file" ]; then
    link_symlink "$tool_file" "$OPENCODE_TOOLS_DIR/$(basename "$tool_file")"
  fi
done

# Copy package.json and install deps if bun is available
if [ -f "$SCRIPT_DIR/.opencode/package.json" ]; then
  cp "$SCRIPT_DIR/.opencode/package.json" "$OPENCODE_CONFIG_DIR/package.json"
  if command -v bun >/dev/null 2>&1; then
    echo "Installing OpenCode tool dependencies..."
    (cd "$OPENCODE_CONFIG_DIR" && bun install --silent) || echo "WARN: bun install failed"
  else
    echo "SKIP: bun not found, run 'cd ~/.config/opencode && bun install' manually"
  fi
fi

# 19) Install global OpenCode skills (to ~/.config/opencode/skills/)
OPENCODE_SKILLS_DIR="$OPENCODE_CONFIG_DIR/skills"
ensure_dir "$OPENCODE_SKILLS_DIR"

# Link skill directories from .opencode/skills/ to ~/.config/opencode/skills/
for skill_dir in "$SCRIPT_DIR/.opencode/skills"/*/; do
  if [ -d "$skill_dir" ]; then
    skill_name="$(basename "$skill_dir")"
    link_symlink "$skill_dir" "$OPENCODE_SKILLS_DIR/$skill_name"
  fi
done

echo "Done. You may need to restart your shell (or source ~/.profile) and restart Neovim."
