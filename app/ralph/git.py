"""Git operations for Ralph.

Provides functions for syncing with remote, pushing with retry,
checking uncommitted changes, and getting commit information.
"""

import subprocess
from pathlib import Path
from typing import Optional


def get_current_commit(cwd: Optional[Path] = None) -> str:
    """Get current HEAD commit hash (short).

    Args:
        cwd: Working directory for git command. Defaults to current directory.

    Returns:
        Short commit hash or "unknown" on failure.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=cwd
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def get_current_branch(cwd: Optional[Path] = None) -> str:
    """Get current git branch name.

    Args:
        cwd: Working directory for git command. Defaults to current directory.

    Returns:
        Branch name or "unknown" on failure.
    """
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


def has_uncommitted_plan(plan_file: Path, cwd: Optional[Path] = None) -> bool:
    """Check if plan.jsonl has uncommitted changes (staged or unstaged).

    Args:
        plan_file: Path to the plan.jsonl file.
        cwd: Working directory for git command. Defaults to current directory.

    Returns:
        True if there are uncommitted changes, False otherwise.
    """
    if not plan_file.exists():
        return False

    result = subprocess.run(
        ["git", "status", "--porcelain", str(plan_file)],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return bool(result.stdout.strip())


def sync_with_remote(
    branch: Optional[str] = None,
    plan_file: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> str:
    """Sync local branch with remote, pulling any new changes.

    Uses rebase to keep history clean. If plan_file has uncommitted changes,
    commits them first to avoid losing work.

    Args:
        branch: Branch to sync. If None, uses current branch.
        plan_file: Path to plan.jsonl for auto-commit before sync.
        cwd: Working directory for git commands.

    Returns:
        "updated" - Successfully pulled new changes
        "current" - Already up to date
        "conflict" - Merge conflict detected (needs manual resolution)
        "error" - Other error
    """
    if branch is None:
        branch = get_current_branch(cwd)
        if branch == "unknown":
            return "error"

    # Commit uncommitted plan changes to avoid losing work
    if plan_file and has_uncommitted_plan(plan_file, cwd):
        subprocess.run(["git", "add", str(plan_file)], cwd=cwd, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "ralph: save state before sync"],
            cwd=cwd,
            capture_output=True,
        )

    # Fetch from remote
    fetch_result = subprocess.run(
        ["git", "fetch", "origin", branch], capture_output=True, text=True, cwd=cwd
    )
    if fetch_result.returncode != 0:
        return "error"

    # Check if we're behind
    status_result = subprocess.run(
        ["git", "status", "-uno"], capture_output=True, text=True, cwd=cwd
    )

    if (
        "Your branch is behind" not in status_result.stdout
        and "have diverged" not in status_result.stdout
    ):
        return "current"

    # Try to rebase
    rebase_result = subprocess.run(
        ["git", "rebase", f"origin/{branch}"], capture_output=True, text=True, cwd=cwd
    )

    if rebase_result.returncode != 0:
        # Abort rebase to restore clean state
        subprocess.run(["git", "rebase", "--abort"], capture_output=True, cwd=cwd)
        if (
            "CONFLICT" in rebase_result.stdout
            or "conflict" in rebase_result.stderr.lower()
        ):
            return "conflict"
        return "error"

    return "updated"


def push_with_retry(
    branch: Optional[str] = None,
    retries: int = 3,
    plan_file: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> bool:
    """Push to remote, handling upstream changes by pulling and retrying.

    Args:
        branch: Branch to push. If None, uses current branch.
        retries: Maximum number of retry attempts.
        plan_file: Path to plan.jsonl for auto-commit during sync.
        cwd: Working directory for git commands.

    Returns:
        True if push succeeded, False on failure.
    """
    if branch is None:
        branch = get_current_branch(cwd)
        if branch == "unknown":
            return False

    for attempt in range(retries):
        push_result = subprocess.run(
            ["git", "push", "origin", branch], capture_output=True, text=True, cwd=cwd
        )

        if push_result.returncode == 0:
            return True

        # Push rejected - need to sync first
        if "rejected" in push_result.stderr or "non-fast-forward" in push_result.stderr:
            sync_result = sync_with_remote(branch, plan_file, cwd)
            if sync_result in ("conflict", "error"):
                return False
            continue
        else:
            return False

    return False
