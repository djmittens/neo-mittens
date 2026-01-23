"""Ralph log command.

Shows state change history from plan.jsonl.
"""

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ralph.state import load_state
from ralph.utils import Colors

__all__ = ["cmd_log"]


def _get_git_info(commit: str) -> dict:
    """Get git info for a commit."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%aI|%an <%ae>", commit],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split("|", 1)
            return {"date": parts[0], "author": parts[1] if len(parts) > 1 else ""}
    except Exception:
        pass
    return {"date": "", "author": ""}


def _get_current_branch() -> str:
    """Get current git branch."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "main"
    except Exception:
        return "main"


def _format_task_log_entry(task, branch: str) -> dict:
    """Format a task for log output."""
    entry = {
        "id": task.id,
        "desc": task.name,
        "notes": task.notes or "",
        "accept": task.accept or "",
        "deps": task.deps or [],
        "spec": task.spec or "",
        "branch": branch,
        "status": task.status,
    }

    # Add git info for done_at
    if task.done_at:
        git_info = _get_git_info(task.done_at)
        entry["done"] = {"commit": task.done_at, "date": git_info["date"]}
        entry["author"] = git_info["author"]

    return entry


def _format_tombstone_entry(tombstone, branch: str) -> dict:
    """Format a tombstone for log output."""
    entry = {
        "id": tombstone.id,
        "desc": tombstone.name or "",
        "reason": tombstone.reason or "",
        "branch": branch,
        "status": "accepted" if hasattr(tombstone, "reason") else "rejected",
    }

    if tombstone.done_at:
        git_info = _get_git_info(tombstone.done_at)
        entry["done"] = {"commit": tombstone.done_at, "date": git_info["date"]}
        entry["author"] = git_info["author"]

    if hasattr(tombstone, "timestamp"):
        entry["timestamp"] = tombstone.timestamp

    return entry


def cmd_log(
    config: dict,
    show_all: bool = False,
    spec_filter: Optional[str] = None,
    branch_filter: Optional[str] = None,
    since: Optional[str] = None,
) -> int:
    """Show state change history.

    Args:
        config: Ralph configuration dict.
        show_all: Show all history including accepted/rejected.
        spec_filter: Filter by spec name.
        branch_filter: Filter by branch.
        since: Filter since date or commit.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    plan_file = config.get("plan_file")
    if not plan_file or not plan_file.exists():
        print(
            f"{Colors.YELLOW}Ralph not initialized. Run 'ralph init' first.{Colors.NC}"
        )
        return 1

    state = load_state(plan_file)
    branch = _get_current_branch()

    # Build log entries
    tasks_list: List[Dict[str, Any]] = []
    accepted_list: List[Dict[str, Any]] = []
    rejected_list: List[Dict[str, Any]] = []

    # Add tasks
    for task in state.tasks:
        if spec_filter and task.spec != spec_filter:
            continue
        tasks_list.append(_format_task_log_entry(task, branch))

    # Add tombstones if showing all
    if show_all:
        for tombstone in state.tombstones.get("accepted", []):
            accepted_list.append(_format_tombstone_entry(tombstone, branch))
        for tombstone in state.tombstones.get("rejected", []):
            rejected_list.append(_format_tombstone_entry(tombstone, branch))

    # Build final structure and output as JSON
    entries = {
        "tasks": tasks_list,
        "tombstones": {"accepted": accepted_list, "rejected": rejected_list},
    }
    print(json.dumps(entries, indent=2))
    return 0
