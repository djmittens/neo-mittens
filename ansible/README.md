# neo-mittens ansible

Gaming-desktop configuration as an Ansible playbook. Migrated from
`install-gaming.sh` (bash) on 2026-04-30.

## Layout

```
ansible/
├── ansible.cfg               # local-execution defaults
├── inventory.yml             # localhost-only inventory
├── site.yml                  # entry-point playbook
├── group_vars/
│   ├── all.yml               # target_user, target_home, repo path
│   └── gaming_desktops.yml   # kernel cmdline, NVIDIA opts, polkit rules
└── roles/
    ├── system_packages/      # pacman + AUR
    ├── gaming_kernel/        # /etc/kernel/cmdline + nvidia-perf.conf
    ├── gamemode/             # gamemode.ini + polkit rule + group
    ├── gamewatcher/          # user service + scripts
    └── bnetswitch/           # cargo build + symlink
```

## Run

Via wrapper (recommended — handles ansible install, bootstrap.sh, etc.):

```bash
cd ~/src/neo-mittens
./install-gaming.sh
```

Direct (assumes ansible already installed):

```bash
cd ~/src/neo-mittens/ansible
ansible-playbook site.yml --ask-become-pass --diff
```

## Useful ansible flags

```bash
# Dry-run: show what would change without changing it
./install-gaming.sh --check

# Run only one role
./install-gaming.sh --tags gamemode
./install-gaming.sh --tags packages

# Skip a role (e.g. skip the long pacman install)
./install-gaming.sh --skip-tags packages

# Verbose (show task details)
./install-gaming.sh -v        # info
./install-gaming.sh -vv       # debug
./install-gaming.sh -vvv      # connection-level

# Step through one task at a time
./install-gaming.sh --step

# Start at a specific task
./install-gaming.sh --start-at-task="Install /etc/gamemode.ini"
```

## Tags reference

| Tag | What runs |
|---|---|
| `packages` | pacman + AUR install |
| `kernel` | cmdline + nvidia modprobe + initramfs regen |
| `system` | kernel + gamemode (root-side stuff) |
| `gamemode` | gamemode.ini + polkit + group |
| `gamewatcher` | user service + scripts |
| `bnetswitch` | cargo build + symlink |
| `user` | gamewatcher + bnetswitch (user-side stuff) |

## Adding a game to gamewatcher

Edit `~/src/neo-mittens/gamewatcher-config/games.conf`, append a regex
on a new line. No ansible re-run needed (config is symlinked):

```bash
echo '/MyNewGame\.exe(\b|$)' >> ~/src/neo-mittens/gamewatcher-config/games.conf
systemctl --user reload gamewatcher
```

## Adding a package to packages-gaming.txt

Edit `ansible/roles/system_packages/files/packages-gaming.txt`, append
the package name on its own line, then re-run with the packages tag:

```bash
./install-gaming.sh --tags packages
```

## Adding a kernel cmdline token

Edit `ansible/group_vars/gaming_desktops.yml`, append to the
`kernel_cmdline_tokens` list. Re-run; cmdline is rebuilt and initramfs
is regenerated. Reboot to activate.

## Editing the polkit rule

Edit `ansible/roles/gamemode/templates/49-gamemode-polkit.rules.j2`
(jinja2 template). Re-run with the gamemode tag; the handler restarts
polkit automatically.

## Rollback

Each task that mutates `/etc` uses `backup: true`, so the previous
version is preserved with a timestamp suffix:

```bash
sudo ls /etc/kernel/cmdline.*.bak.*
sudo ls /etc/gamemode.ini.*.bak.*
sudo ls /etc/modprobe.d/nvidia-perf.conf.*.bak.*

# To revert one file:
sudo cp /etc/gamemode.ini.<timestamp>.bak /etc/gamemode.ini
```
