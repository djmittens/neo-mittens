# Neo-Mittens Dependencies

This document lists the hard dependencies required for neo-mittens to function properly.

## Core Dependencies

| Dependency | Required | Purpose | Install |
|------------|----------|---------|---------|
| **zsh** | Yes | Shell configuration, completions, tmux pane titles | Pre-installed on macOS, `pacman -S zsh` on Arch |
| **neovim** | Yes | Editor with neo-mittens Lua config | `brew install neovim` / `pacman -S neovim` |
| **git** | Yes | Version control, TPM installation | Pre-installed on most systems |
| **python3** | Yes | Ralph TUI, textual library | Pre-installed on most systems |

## OpenCode Integration

| Dependency | Required | Purpose | Install |
|------------|----------|---------|---------|
| **opencode** | Yes | AI coding assistant | See [opencode.ai](https://opencode.ai) |
| **bun** | Yes | Runtime for OpenCode custom tools (.ts files) | `curl -fsSL https://bun.sh/install \| bash` |
| **@opencode-ai/plugin** | Yes | OpenCode tool SDK (installed via bun) | `cd ~/.config/opencode && bun install` |

## Optional Dependencies

| Dependency | Required | Purpose | Install |
|------------|----------|---------|---------|
| **tmux** | Optional | Terminal multiplexer with TPM plugins | `brew install tmux` / `pacman -S tmux` |
| **gcloud** | Optional | Google Cloud SDK for custom tools | [cloud.google.com/sdk](https://cloud.google.com/sdk) |
| **textual** | Optional | Enhanced TUI for ralph | `pip3 install --user textual` |

## Development Dependencies

| Dependency | Required | Purpose | Install |
|------------|----------|---------|---------|
| **mypy** | Optional | Static type checking for Python | `brew install mypy` / `pip3 install --user mypy` |

## Platform-Specific (Linux/Hyprland)

| Dependency | Required | Purpose | Install |
|------------|----------|---------|---------|
| **hyprland** | Optional | Wayland compositor (Linux) | `pacman -S hyprland` |
| **waybar** | Optional | Status bar for Hyprland | `pacman -S waybar` |
| **wofi** | Optional | Application launcher | `pacman -S wofi` |
| **rofi** | Optional | Alternative launcher (X11) | `pacman -S rofi` |

## Verification

Run these commands to verify dependencies are installed:

```bash
# Core
zsh --version
nvim --version
git --version
python3 --version

# OpenCode
opencode --version
bun --version

# Optional
tmux -V
gcloud --version
```

## Post-Install

After installing dependencies, run the bootstrap script:

```bash
cd ~/src/neo-mittens
./bootstrap.sh
```

Then for OpenCode tools:

```bash
cd ~/.config/opencode
bun install
```
