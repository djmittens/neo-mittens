"""Ralph watch command.

Live progress dashboard for monitoring construct mode.
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from ralph.state import load_state
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


def _count_running_processes() -> int:
    """Count running opencode processes."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "opencode"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return len(result.stdout.strip().split("\n"))
    except Exception:
        pass
    return 0


def cmd_watch(config: dict) -> int:
    """Live progress dashboard.

    Monitors the ralph plan file and displays a real-time dashboard
    showing current stage, task progress, and metrics.

    Args:
        config: Ralph configuration dict with plan_file, repo_root, etc.

    Returns:
        Exit code (0 for success).
    """
    plan_file = config.get("plan_file")
    if not plan_file or not plan_file.exists():
        print(f"{Colors.RED}No plan file found. Run 'ralph init' first.{Colors.NC}")
        return 1

    dashboard = FallbackDashboard(config)
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
            dashboard.is_running = _count_running_processes() > 0
            dashboard.running_count = _count_running_processes()
            return [f"State refreshed at {time.strftime('%H:%M:%S')}"]

        dashboard.is_running = _count_running_processes() > 0
        dashboard.running_count = _count_running_processes()
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
