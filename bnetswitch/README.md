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
| b       | Toggle "banned" marker on selected account |
| l       | Toggle auto-launch on/off       |
| r       | Reload accounts from config     |
| R       | Rebuild login list from accounts Battle.net still has credentials for |
| q/Esc   | Quit                            |

The active account (first in the list) is shown in green with a `*` marker.
Accounts marked **banned** are shown in red with strikethrough and a
`(BANNED)` tag; bnetswitch refuses to launch Overwatch for them and asks for
confirmation before switching into one.

## Discord voice companion

With the bnetswitch LFG userscript **v0.13.3+** running in Discord web,
joining an Overwatch Discord voice channel from either Discord or the TUI
automatically splits the bnetswitch view and opens a browser companion sidebar.
The bridge uses your existing Discord web voice session.
Existing participants are hydrated from Discord's loaded voice-state store,
with rendered voice rows as a partial fallback. Gateway events then maintain
membership as people join and leave; scrolling a row away does not remove it.

The roster shows server nicknames, Discord IDs in parentheses, avatars,
observed time in the channel, and green speaking highlights. TUI avatars use
the same Kitty/Sixel/iTerm2 support as rank icons; other terminals show a glyph.
Speaking detection reads Discord's rendered voice indicators: users whose
indicators are not rendered cannot reliably be highlighted.

| TUI (Tab focuses voice sidebar) | Browser | Action |
|---|---|---|
| j/k or arrows | Click a member | Select a member |
| b | Alt+B / Ban selected | Request a VC ban |
| c | Alt+C / Claim VC | Request channel ownership |
| t | Alt+T / Flag troll | Toggle a persistent personal troll marker |
| h | Recent voice history | View recent events |
| Esc / Tab | — | Return focus to the main view |

Ban/claim controls read the server's
[LFG interface](https://discord.com/channels/94882524378968064/1192075868609183754)
and submit its real button/dropdown component interactions in the background,
without navigating your current chat, scrolling, or clicking visible controls.
The bot's dropdown response is read from gateway messages or Discord's cached
messages, including ephemeral responses. Bans select **Discord IDs**, never a
nickname guess; claims select the current VC's ID. Missing session/component
metadata, unmatched dropdown options, rejected requests, or a departed target
produce an error rather than switching the UI to the interface channel.
The existing shortcuts are unchanged. Server permissions and the LFG bot decide
whether the request is accepted; "request sent" still means submitted, not a
confirmed ban/claim. The live background flow needs an authenticated bot check.

Persistent badges distinguish **BANNED BY ME**, **BANNED ME**, **TROLL**, and
**BAN REQUESTED (unconfirmed)**. Bot confirmation is currently recognized from
explicit Owner / Voice Channel embed fields, Banned User / Banned By fields,
or messages of the form `@actor banned @target from #channel` with Discord
mentions. Other bot response formats require adapting the parser to a real
payload. A member CONNECT-deny permission change is logged with an unknown
actor. A disconnect alone is not recorded as a ban, and an owner is not
automatically identified as the banner. **Exact attribution is available only
when Discord/the bot supplies evidence identifying the actor.**

History and avatar snapshots live under
`~/.local/share/bnetswitch/voice/` (or `$XDG_DATA_HOME/bnetswitch/voice/`):

- `history.jsonl`: append-only joins, leaves, observed durations, ownership
  evidence, moderation requests/failures, confirmed bans, and personal flags.
- `history.snapshot.json`: latest periodic roster checkpoint for restart recovery.
- `avatars/*.png`: cached observed avatar versions, retained after users leave.

Durations start when the bridge first observes a member, not necessarily their
actual Discord join time. Outages/restarts create observation-gap records ending
at the last observation, so offline time is not counted. History endpoints show
the latest 200 events; the JSONL file retains the full log. The browser sidebar
stays available after disconnecting so you can inspect evidence immediately.
Only the elected primary browser tab supplies the roster and executes actions.
Live voice updates use a persistent loopback WebSocket to avoid creating a
Tampermonkey request for every speaker transition; browsers that block it fall
back to throttled HTTP updates. `bnetswitchVoiceDiagnose()` in Discord's browser
console reports the roster and visible interface/dropdown IDs for troubleshooting.

Build/restart bnetswitch and let the userscript loader apply the update (or
update the main userscript from `http://127.0.0.1:7172/bnetswitch-lfg.user.js`).
The loader waits until you leave voice before reloading.

Verification:

```bash
cargo test                      # from bnetswitch/
node --test userscripts/bnetswitch-voice.test.cjs  # from repository root
```

## Configuration

### Terminal images (Ghostty + tmux)

Inside tmux, `TERM=tmux-256color` and `TERM_PROGRAM=tmux` are normal.
bnetswitch also recognizes Ghostty through `GHOSTTY_RESOURCES_DIR` or
`GHOSTTY_BIN_DIR`, which the tmux config propagates to new panes. Keep
`set -g allow-passthrough on` enabled so Kitty graphics reach Ghostty.

Run `bnetswitch term-info` in the same pane to inspect detection. Ghostty
inside tmux should report `kitty-graphics, tmux` and `Inline images: enabled`.
Redirected/piped output disables image rendering, as does
`BNETSWITCH_NO_GRAPHICS=1`. Terminal capability queries do not consume stdin.

### Application config

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
