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
    """Check if a plan file has uncommitted changes (staged or unstaged).

    Args:
        plan_file: Path to the plan.jsonl file (tix or legacy).
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


def has_uncommitted_tix(
    plan_file: Path,
    state_file: Path,
    cwd: Optional[Path] = None,
) -> bool:
    """Check if tix plan.jsonl or ralph-state.json have uncommitted changes.

    Args:
        plan_file: Path to the tix plan.jsonl file.
        state_file: Path to .tix/ralph-state.json.
        cwd: Working directory for git command.

    Returns:
        True if either file has uncommitted changes.
    """
    files = []
    if plan_file.exists():
        files.append(str(plan_file))
    if state_file.exists():
        files.append(str(state_file))

    if not files:
        return False

    result = subprocess.run(
        ["git", "status", "--porcelain"] + files,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return bool(result.stdout.strip())


def _commit_plan_if_modified(plan_file: Optional[Path], cwd: Optional[Path]) -> None:
    """Commit plan file changes if file has uncommitted modifications.

    Args:
        plan_file: Path to plan.jsonl (tix or legacy)
        cwd: Working directory for git commands
    """
    if plan_file and has_uncommitted_plan(plan_file, cwd):
        subprocess.run(["git", "add", str(plan_file)], cwd=cwd, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "ralph: save state before sync"],
            cwd=cwd,
            capture_output=True,
        )


def _fetch_remote(branch: str, cwd: Optional[Path]) -> bool:
    """Fetch changes from the remote for a specific branch.

    Args:
        branch: Branch name to fetch
        cwd: Working directory for git commands

    Returns:
        True if fetch succeeded, False otherwise
    """
    fetch_result = subprocess.run(
        ["git", "fetch", "origin", branch], capture_output=True, text=True, cwd=cwd
    )
    return fetch_result.returncode == 0


def _is_branch_behind(cwd: Optional[Path]) -> bool:
    """Check if current branch is behind or has diverged.

    Args:
        cwd: Working directory for git commands

    Returns:
        True if branch is behind or has diverged, False if up to date
    """
    status_result = subprocess.run(
        ["git", "status", "-uno"], capture_output=True, text=True, cwd=cwd
    )
    return (
        "Your branch is behind" in status_result.stdout
        or "have diverged" in status_result.stdout
    )


def _rebase_onto_remote(branch: str, cwd: Optional[Path]) -> str:
    """Attempt to rebase current branch onto remote branch.

    Args:
        branch: Branch name
        cwd: Working directory for git commands

    Returns:
        "updated" on success, "conflict" on merge conflict, "error" otherwise
    """
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
    _commit_plan_if_modified(plan_file, cwd)

    # Fetch from remote
    if not _fetch_remote(branch, cwd):
        return "error"

    # Check if we're behind
    if not _is_branch_behind(cwd):
        return "current"

    # Try to rebase
    return _rebase_onto_remote(branch, cwd)


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
