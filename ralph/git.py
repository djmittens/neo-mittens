"""Git operations for Ralph.

Provides functions for syncing with remote, pushing with retry,
checking for uncommitted changes, and getting commit information.
"""

import subprocess
from pathlib import Path
from typing import Literal, Optional


SyncResult = Literal["updated", "current", "conflict", "error"]


def get_current_commit(repo_root: Path) -> str:
    """Get current HEAD commit hash (short).

    Args:
        repo_root: The repository root directory.

    Returns:
        The short commit hash, or "unknown" if git command fails.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def has_uncommitted_plan(repo_root: Path, plan_file: Path) -> bool:
    """Check if plan.jsonl has uncommitted changes (staged or unstaged).

    Args:
        repo_root: The repository root directory.
        plan_file: Path to the plan.jsonl file.

    Returns:
        True if there are uncommitted changes to plan_file, False otherwise.
    """
    if not plan_file.exists():
        return False

    result = subprocess.run(
        ["git", "status", "--porcelain", str(plan_file)],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    return bool(result.stdout.strip())


def _commit_plan_if_needed(repo_root: Path, plan_file: Path) -> None:
    """Commit plan file if it has uncommitted changes.

    Args:
        repo_root: The repository root directory.
        plan_file: Path to the plan.jsonl file.
    """
    if has_uncommitted_plan(repo_root, plan_file):
        subprocess.run(
            ["git", "add", str(plan_file)],
            cwd=repo_root,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "ralph: save state before sync"],
            cwd=repo_root,
            capture_output=True,
        )


def sync_with_remote(
    repo_root: Path,
    branch: str,
    plan_file: Optional[Path] = None,
    quiet: bool = False,
) -> SyncResult:
    """Sync local branch with remote, pulling any new changes.

    This allows multiple Ralph instances to collaborate on the same branch.
    Uses rebase to keep history clean.

    Args:
        repo_root: The repository root directory.
        branch: The branch name to sync.
        plan_file: Optional path to plan.jsonl to commit before sync.
        quiet: If True, suppress output messages.

    Returns:
        "updated" - Successfully pulled new changes.
        "current" - Already up to date.
        "conflict" - Merge conflict detected (needs manual resolution).
        "error" - Other error (logged but not fatal).
    """
    from ralph.utils import Colors

    if plan_file:
        _commit_plan_if_needed(repo_root, plan_file)

    fetch_result = subprocess.run(
        ["git", "fetch", "origin", branch],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if fetch_result.returncode != 0:
        return "error"

    status_result = subprocess.run(
        ["git", "status", "-uno"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )

    if (
        "Your branch is behind" not in status_result.stdout
        and "have diverged" not in status_result.stdout
    ):
        return "current"

    if not quiet:
        print(f"{Colors.CYAN}Remote has new changes - rebasing...{Colors.NC}")

    rebase_result = subprocess.run(
        ["git", "rebase", f"origin/{branch}"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )

    if rebase_result.returncode != 0:
        if (
            "CONFLICT" in rebase_result.stdout
            or "conflict" in rebase_result.stderr.lower()
        ):
            subprocess.run(
                ["git", "rebase", "--abort"],
                capture_output=True,
                cwd=repo_root,
            )
            return "conflict"
        else:
            subprocess.run(
                ["git", "rebase", "--abort"],
                capture_output=True,
                cwd=repo_root,
            )
            if not quiet:
                print(
                    f"{Colors.YELLOW}Rebase failed: {rebase_result.stderr}{Colors.NC}"
                )
            return "error"

    if not quiet:
        print(f"{Colors.GREEN}Successfully synced with remote{Colors.NC}")
    return "updated"


def push_with_retry(
    repo_root: Path,
    branch: str,
    plan_file: Optional[Path] = None,
    max_retries: int = 3,
    quiet: bool = False,
) -> bool:
    """Push to remote, handling upstream changes by pulling and retrying.

    Args:
        repo_root: The repository root directory.
        branch: The branch name to push.
        plan_file: Optional path to plan.jsonl for sync_with_remote.
        max_retries: Maximum number of push attempts.
        quiet: If True, suppress output messages.

    Returns:
        True if push succeeded, False if unrecoverable conflict.
    """
    from ralph.utils import Colors

    for attempt in range(max_retries):
        push_result = subprocess.run(
            ["git", "push", "origin", branch],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )

        if push_result.returncode == 0:
            return True

        if "rejected" in push_result.stderr or "non-fast-forward" in push_result.stderr:
            if not quiet:
                print(
                    f"{Colors.YELLOW}Push rejected - syncing with remote "
                    f"(attempt {attempt + 1}/{max_retries}){Colors.NC}"
                )

            sync_result = sync_with_remote(repo_root, branch, plan_file, quiet)
            if sync_result == "conflict":
                if not quiet:
                    print(f"{Colors.RED}Conflict during sync - cannot push{Colors.NC}")
                return False
            elif sync_result == "error":
                return False
            continue
        else:
            if not quiet:
                print(f"{Colors.RED}Push failed: {push_result.stderr}{Colors.NC}")
            return False

    if not quiet:
        print(f"{Colors.RED}Push failed after {max_retries} retries{Colors.NC}")
    return False


def get_current_branch(repo_root: Path) -> Optional[str]:
    """Get the current git branch name.

    Args:
        repo_root: The repository root directory.

    Returns:
        The current branch name, or None if not in a git repository.
    """
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def git_add(repo_root: Path, *paths: Path) -> bool:
    """Stage files for commit.

    Args:
        repo_root: The repository root directory.
        *paths: Paths to files to stage.

    Returns:
        True if staging succeeded, False otherwise.
    """
    if not paths:
        return True
    result = subprocess.run(
        ["git", "add"] + [str(p) for p in paths],
        capture_output=True,
        cwd=repo_root,
    )
    return result.returncode == 0


def git_commit(repo_root: Path, message: str) -> bool:
    """Create a commit with the given message.

    Args:
        repo_root: The repository root directory.
        message: The commit message.

    Returns:
        True if commit succeeded, False otherwise.
    """
    result = subprocess.run(
        ["git", "commit", "-m", message],
        capture_output=True,
        cwd=repo_root,
    )
    return result.returncode == 0
