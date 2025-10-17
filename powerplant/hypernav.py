#!/usr/bin/env python3

import subprocess
import sys
import json
import os
from datetime import datetime

# Direction mapping
# NOTE: Updated to use hyprctl's accepted shorthand (l/r/u/d)
dir_map = {
    'h': {'hypr': 'l', 'tmux': ['L', 'pane_at_left' ]},
    'j': {'hypr': 'd', 'tmux': ['D', 'pane_at_bottom']},
    'k': {'hypr': 'u', 'tmux': ['U', 'pane_at_top']},
    'l': {'hypr': 'r', 'tmux': ['R', 'pane_at_right']},
}

logfile = os.path.expanduser("~/.cache/hypernav.log")

def log(msg):
    if 0:
        with open(logfile, "a") as f:
            f.write(f"[{datetime.now()}] {msg}\n")

dir_key = sys.argv[1] if len(sys.argv) > 1 else None
if dir_key not in dir_map:
    log("Invalid direction")
    print("Usage: nav.py [h|j|k|l]")
    sys.exit(1)

hypr_dir = dir_map[dir_key]['hypr']
tmux_dir = dir_map[dir_key]['tmux'][0]
tmux_border = dir_map[dir_key]['tmux'][1]

# Run a shell command and return stdout
def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout.strip()

# Get active window info from hyprctl
try:
    active = json.loads(run(["hyprctl", "activewindow", "-j"]))
    win_class = active.get("class", "")
    pid = active.get("pid", 0)
except Exception:
    log("Failed to get Hyprland active window")
    subprocess.run(["hyprctl", "dispatch", "movefocus", hypr_dir])
    sys.exit(0)

if win_class not in [ "com.mitchellh.ghostty", "Alacritty" ]:
    log(f"Window class is not Alacritty: {win_class}")
    subprocess.run(["hyprctl", "dispatch", "movefocus", hypr_dir])
    sys.exit(0)

# Walk process tree to find tmux and nvim
in_tmux = False
in_nvim = False

def walk_process_tree(pid):
    to_check = [pid]
    while to_check:
        current = to_check.pop()
        try:
            cmdline = run(["ps", "-p", str(current), "-o", "comm="])
            log(f"Checking cmdline: {cmdline}")
            if cmdline.startswith("tmux"):
                global in_tmux
                in_tmux = True
            elif cmdline in ("nvim", "vim"):
                global in_nvim
                in_nvim = True

            children = run(["pgrep", "-P", str(current)])
            if children:
                to_check.extend(map(int, children.strip().split()))
        except Exception:
            continue

walk_process_tree(pid)

# if we are in neovim, then lets hope i have a script that does the switch in there natively
if in_nvim:
    log("Nvim detected, letting it handle the motion")
    # requires `wtype` tool to perform the keypress again in wayland, as this
    # script already consumed it
    subprocess.run(["wtype", "-M", "win", "-k", dir_key, "-m", "win"], capture_output=True, text=True)
    sys.exit(0)

# Fallback to tmux if possible
if in_tmux:
    log(f"Checking  if tmux has nvim")
    result = subprocess.run(["tmux", "display", "-p", '#{pane_current_command}'], capture_output=True, text=True)

    if result.stdout.strip() == 'nvim':
        # requires `wtype` tool to perform the keypress again in wayland, as this
        # script already consumed it
        log("Nvim inside Tmux detected, letting it handle the motion")

        try:
            res = subprocess.run(["wtype", "-M", "alt", "-k", dir_key], capture_output=True, text=True)
            log(f"Sending key to nvim {res}")

        except subprocess.CalledProcessError as e:
            log(f"❌ Failed to run wtype: {e}")
        except FileNotFoundError:
            log("❌ wtype is not installed or not in PATH")

        sys.exit(0)

    log(f"Checking  if tmux can move: {tmux_border}")
    result = subprocess.run(["tmux", "display", "-p", f"#{{{tmux_border}}}"],
                            capture_output=True, text=True)

    log(f"The result is : {result.stdout.strip()}")
    if result.stdout.strip() == '0':
        log(f"Switching to pane in direction: {tmux_dir}")
        subprocess.run(["tmux", f"select-pane", f"-{tmux_dir}"], stderr=subprocess.DEVNULL)
        sys.exit(0)

# Fallback to Hyprland
log(f"Fallback to Hyprland movefocus {hypr_dir}")
subprocess.run(["hyprctl", "dispatch", "movefocus", hypr_dir])
