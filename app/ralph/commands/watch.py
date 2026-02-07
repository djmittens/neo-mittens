"""Ralph watch command.

Live progress dashboard for monitoring construct mode.
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from ralph.state import load_state
from ralph.tix import Tix
from ralph.tui.fallback import FallbackDashboard
from ralph.utils import Colors

__all__ = ["cmd_watch"]


def _get_current_branch() -> str:
    """Get current git branch name."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


def _count_running_processes_in_cwd() -> int:
    """Count opencode processes running in the current directory."""
    cwd = str(Path.cwd())
    try:
        result = subprocess.run(
            ["pgrep", "-x", "opencode"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return 0

        count = 0
        pids = result.stdout.strip().split("\n")
        for pid in pids:
            try:
                proc_cwd = Path(f"/proc/{pid}/cwd").resolve()
                if str(proc_cwd) == cwd:
                    count += 1
            except (OSError, PermissionError):
                continue
        return count
    except Exception:
        return 0


def cmd_watch(config: dict) -> int:
    """Live progress dashboard.

    Args:
        config: Ralph configuration dict with plan_file, repo_root, etc.

    Returns:
        Exit code (0 for success).
    """
    plan_file = config.get("plan_file")
    if not plan_file or not plan_file.exists():
        print(f"{Colors.RED}No plan file found. Run 'ralph init' first.{Colors.NC}")
        return 1

    repo_root = config.get("repo_root", Path.cwd())
    tix: Optional[Tix] = None
    try:
        tix = Tix(repo_root)
        if not tix.is_available():
            tix = None
    except Exception:
        tix = None

    dashboard = FallbackDashboard(config, tix=tix)
    dashboard.branch = _get_current_branch()

    last_mtime: Optional[float] = None

    def poll_data():
        """Poll for state changes."""
        nonlocal last_mtime

        try:
            current_mtime = plan_file.stat().st_mtime
        except OSError:
            return []

        if last_mtime is None or current_mtime != last_mtime:
            last_mtime = current_mtime
            dashboard.ralph_state = load_state(plan_file)
            dashboard.is_running = _count_running_processes_in_cwd() > 0
            dashboard.running_count = _count_running_processes_in_cwd()
            return [f"State refreshed at {time.strftime('%H:%M:%S')}"]

        dashboard.is_running = _count_running_processes_in_cwd() > 0
        dashboard.running_count = _count_running_processes_in_cwd()
        return []

    def on_quit():
        """Handle quit."""
        print(f"\n{Colors.GREEN}Watch mode exited.{Colors.NC}")
        return 0

    try:
        return dashboard.run_loop(poll_data, on_quit=on_quit) or 0
    except KeyboardInterrupt:
        print(f"\n{Colors.GREEN}Watch mode exited.{Colors.NC}")
        return 0
