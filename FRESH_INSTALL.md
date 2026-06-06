# Fresh Install — Arch + Hyprland (RedBox)

End-to-end procedure for rebuilding the gaming desktop from scratch.
Time estimate: ~45 minutes start to working desktop, mostly waiting on
package downloads.

## Hardware target (this machine specifically)

- **CPU**: AMD Ryzen 9 9900X (Zen 5, 12c/24t, 2 CCDs)
- **GPU**: NVIDIA RTX 5090 (Blackwell, GB202)
- **RAM**: 64 GB DDR5
- **Storage**: NVMe (btrfs root + EFI ESP)
- **Monitor**: Samsung Odyssey G95NC, 7680x2160 @ 240 Hz over DP
- **Compositor**: Hyprland on Wayland

If you're rebuilding on different hardware, the NVIDIA-specific tuning
and CCD0 detection won't apply verbatim. The dotfiles (Neovim, Hyprland,
etc.) are portable; the gaming-specific Ansible roles are RedBox-tuned.

## Architecture

| Tool | Purpose | Where it runs |
|---|---|---|
| `bootstrap.sh` (bash) | Portable dotfiles, neovim, tmux, opencode, brew/pacman dep hints | All 4 hosts (RedBox, server, both Macs) |
| `install-gaming.sh` (thin wrapper) | Sanity check + runs bootstrap + delegates to Ansible | RedBox only |
| `ansible/site.yml` (playbook) | Gaming-desktop system config (kernel cmdline, NVIDIA, gamemode, gamewatcher, bnetswitch) | RedBox only |

## Step 1: Base Arch install (manual)

Boot the Arch ISO, run `archinstall`. Pick:

- **Disk layout**: btrfs with subvolumes (matches current setup)
- **Bootloader**: **systemd-boot** (the Ansible role targets `/etc/kernel/cmdline`)
- **Profile**: minimal (we install everything we want explicitly later)
- **Audio**: pipewire
- **Kernel**: `linux` (mainline, current stable)
- **Network**: NetworkManager
- **Hostname**: `RedBox`
- **Users**: create your normal user, add to `wheel` for sudo

Reboot into the fresh install. Log in as your normal user. Verify
networking with `ping archlinux.org`.

## Step 2: Get neo-mittens

```bash
sudo pacman -S --needed git
mkdir -p ~/src
git clone <your neo-mittens git url> ~/src/neo-mittens
cd ~/src/neo-mittens
```

## Step 3: Run install-gaming.sh

```bash
./install-gaming.sh
```

The wrapper:

1. Sanity-checks (Linux, Arch, non-root user).
2. Asks for confirmation.
3. Installs `ansible` via pacman if missing.
4. Installs the `community.general` ansible collection.
5. Runs `bootstrap.sh` (portable: dotfiles, neovim, tmux, etc.).
6. `exec`s `ansible-playbook site.yml --ask-become-pass --diff`.

The playbook then runs five roles (you'll be prompted once for sudo):

| Role | Tag | What it does |
|---|---|---|
| `system_packages` | `packages` | `pacman -Syu` ~228 native packages + bootstrap yay + AUR install |
| `gaming_kernel` | `kernel` | Detect bootloader, write `/etc/kernel/cmdline`, render NVIDIA modprobe.d, regen initramfs |
| `gamemode` | `gamemode` | Install gamemode pkgs, deploy `/etc/gamemode.ini`, render polkit rule with templated user, restart polkit, add user to gamemode group |
| `gamewatcher` | `gamewatcher` | Symlink scripts to `~/.local/bin`, render systemd unit, enable + start service |
| `bnetswitch` | `bnetswitch` | Build with cargo, symlink binary into `powerplant/` |

## Step 4: Reboot

When the playbook finishes, reboot. Cmdline + NVIDIA modprobe + group
membership all need a fresh boot to take effect.

## Step 5: Post-reboot verification

```bash
# Group membership applied
groups | tr ' ' '\n' | grep gamemode

# Kernel cmdline
cat /proc/cmdline | tr ' ' '\n' | grep -E 'mitigations|tsc|nowatchdog'

# NVIDIA tuning live
cat /proc/driver/nvidia/params | grep -E 'PageAttribute|PreserveVideoMemory'

# gamewatcher running
systemctl --user status gamewatcher

# polkit allows governor change without prompt
pkexec /usr/lib/gamemode/cpugovctl get   # prints 'powersave', no password

# gamemoded clean (only harmless ioprio/SCHED_ISO errors expected)
journalctl --user -u gamemoded -b
```

## Step 6: Application data not in dotfiles

Things the playbook does NOT restore (you do these by hand):

- **Browser profiles** (Firefox / Chrome bookmarks, sessions, extensions).
  Sync via Firefox Sync / Chrome Sync, or restore `~/.mozilla` /
  `~/.config/google-chrome` from a backup.
- **Battle.net account state**. Install Battle.net through Lutris first,
  log in to each account once to populate `Battle.net.config`. Then
  `bnetswitch import-tcno <path>` to import BattleTags.
- **SSH keys** in `~/.ssh`. Restore from secure backup; never commit.
- **GPG keys** in `~/.gnupg`. Same.
- **OpenCode auth** in `~/.config/opencode`. Re-login.
- **1Password local vault**. Re-login.
- **Game saves** for non-cloud games. Restore from backup.

Anything that's a "secret" or "user data" lives outside this repo.

## Server / Mac install

Server (Arch headless) and the two Macs run JUST `bootstrap.sh`, never
`install-gaming.sh`:

```bash
git clone <your neo-mittens git url> ~/src/neo-mittens
cd ~/src/neo-mittens
./bootstrap.sh
```

The portable bootstrap handles dotfiles, neovim, tmux, opencode tools,
and per-platform package hints (`brew install` on macOS, `pacman -S` on
Arch). Anything gaming-related is skipped because `install-gaming.sh` is
only invoked on RedBox.

## Working with the Ansible playbook

### Dry-run (see what would change)

```bash
./install-gaming.sh --check
```

### Run only one role

```bash
./install-gaming.sh --tags packages
./install-gaming.sh --tags gamemode,gamewatcher
```

### Skip slow roles

```bash
./install-gaming.sh --skip-tags packages   # if packages are already installed
```

### Update package list after installing new things

```bash
cd ~/src/neo-mittens

pacman -Qqen \
  | grep -vE '^(mhwd|manjaro-|linux[0-9]+(-headers|-rt|-r8168|-nvidia-open|-zen)?$)' \
  > ansible/roles/system_packages/files/packages-gaming.txt

pacman -Qqem > ansible/roles/system_packages/files/packages-aur.txt

git add ansible/roles/system_packages/files/
git commit -m "Refresh package snapshot"
```

### Add a kernel cmdline token

Edit `ansible/group_vars/gaming_desktops.yml`, append to the
`kernel_cmdline_tokens` list, re-run with `--tags kernel`. Reboot.

### Edit the polkit rule

Edit `ansible/roles/gamemode/templates/49-gamemode-polkit.rules.j2`.
Re-run with `--tags gamemode`. Handler restarts polkit automatically.

### Add a game to gamewatcher

Edit `gamewatcher-config/games.conf`. No ansible re-run needed (the
config is symlinked, edits propagate live). Reload the service:

```bash
systemctl --user reload gamewatcher
```

## Rollback

Each task that mutates `/etc` uses `backup: true`, so the previous
version is preserved with a timestamp suffix:

```bash
sudo ls /etc/kernel/cmdline.*.bak.*
sudo ls /etc/gamemode.ini.*.bak.*
sudo ls /etc/modprobe.d/nvidia-perf.conf.*.bak.*
sudo ls /etc/polkit-1/rules.d/49-gamemode-polkit.rules.*.bak.*

# Revert one file
sudo cp /etc/gamemode.ini.<timestamp>.bak /etc/gamemode.ini

# Revert kernel cmdline (most invasive change)
sudoedit /etc/kernel/cmdline   # remove mitigations=off etc.
# systemd-boot picks up the new cmdline on next reboot automatically
sudo reboot
```
