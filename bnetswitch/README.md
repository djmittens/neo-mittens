# bnetswitch

A fast, lightweight Battle.net account switcher for Linux. Written in Rust with a terminal UI (TUI).

Designed for Overwatch players with multiple accounts running Battle.net through Wine/Lutris.

## How It Works

Battle.net stores a list of remembered account emails in `Battle.net.config`. The first email in the list is the one that auto-logs in. This tool:

1. Kills Battle.net processes
2. Reorders the email list so your chosen account is first
3. Restarts Battle.net

No passwords or tokens are stored by this tool. Battle.net handles credential storage internally -- you just need to have logged in once with "Remember Password" checked for each account.

## Features

- TUI with arrow key navigation (handles 10+ accounts easily)
- Per-account nicknames (so you can tell "Main", "DPS Alt", "Tank Smurf" apart)
- Auto-detects Wine prefix locations (Lutris, plain Wine, custom)
- Backs up `Battle.net.config` before every switch
- Auto-launches Battle.net after switching (configurable)
- Single static binary, no runtime dependencies

## Installation

### Build from source

```bash
cargo build --release
cp target/release/bnetswitch ~/.local/bin/
```

### Run

```bash
bnetswitch
```

## TUI Controls

| Key     | Action                          |
|---------|---------------------------------|
| Up/k    | Move selection up               |
| Down/j  | Move selection down             |
| Enter   | Switch to selected account      |
| n       | Set nickname for selected account |
| l       | Toggle auto-launch on/off       |
| r       | Reload accounts from config     |
| q/Esc   | Quit                            |

The active account (first in the list) is shown in green with a `*` marker.

## Configuration

bnetswitch stores its own config at `~/.config/bnetswitch/config.toml`:

```toml
# Path to Wine prefix (auto-detected if not set)
# wine_prefix = "/home/user/Games/battlenet"

# Launch Battle.net after switching (default: true)
auto_launch = true

# Launch via Lutris instead of direct Wine (default: true)
use_lutris = true

# Account nicknames
[accounts."you@example.com"]
nickname = "Main"

[accounts."alt@example.com"]
nickname = "DPS Alt"
```

## Auto-Detection

bnetswitch searches these locations for a Wine prefix containing `Battle.net.config`:

- `~/Games/battlenet/`
- `~/Games/battle-net/`
- `~/Games/Battle.net/`
- `~/Games/*/` (any subdirectory)
- `~/.wine/`
- `~/.local/share/lutris/runners/wine/*/`

If your prefix is elsewhere, set `wine_prefix` in the config file.

---

## Setting Up Battle.net on Linux (Lutris)

If you don't have Battle.net installed yet, here's how to set it up:

### Prerequisites

1. **Install Lutris:**
   ```bash
   # Arch/Manjaro
   sudo pacman -S lutris

   # Ubuntu/Debian
   sudo apt install lutris

   # Fedora
   sudo dnf install lutris
   ```

2. **Install Wine dependencies:**
   ```bash
   # Arch
   sudo pacman -S wine wine-mono wine-gecko

   # Ubuntu (enable 32-bit)
   sudo dpkg --add-architecture i386
   sudo apt update
   sudo apt install wine64 wine32 libwine libwine:i386
   ```

3. **Install Vulkan drivers** (required for DXVK/Overwatch):
   ```bash
   # Arch - NVIDIA
   sudo pacman -S nvidia-utils lib32-nvidia-utils vulkan-icd-loader lib32-vulkan-icd-loader

   # Arch - AMD
   sudo pacman -S vulkan-radeon lib32-vulkan-radeon vulkan-icd-loader lib32-vulkan-icd-loader

   # Ubuntu - NVIDIA
   sudo apt install nvidia-driver-XXX libvulkan1 libvulkan1:i386

   # Ubuntu - AMD
   sudo apt install mesa-vulkan-drivers mesa-vulkan-drivers:i386
   ```

### Install Battle.net

1. Open Lutris
2. Click the `+` button or go to lutris.net/games/battlenet
3. Click "Install" on the Wine Standard installer
4. **Important:** Install to an ext4 partition (NOT NTFS)
5. Follow the prompts to install Battle.net

### First-Time Account Setup

For each account you want to switch between:

1. Launch Battle.net through Lutris
2. Log in with the account email/password
3. **Check "Remember Password"** -- this is critical
4. Log out (click your profile icon -> Log Out)
5. Repeat for each account

After logging into all accounts, they'll all appear in `Battle.net.config` and bnetswitch will be able to switch between them.

### Common Issues

- **Battle.net is slow/spinning:** Edit `/etc/hosts`, make sure your hostname resolves to `127.0.0.1`
- **Black screen:** Disable streaming in Battle.net settings
- **DLL errors with DXVK:** Make sure 32-bit Vulkan packages are installed
- **Agent sleeping:** Delete `drive_c/ProgramData/Battle.net` in your prefix, relaunch

## License

MIT
