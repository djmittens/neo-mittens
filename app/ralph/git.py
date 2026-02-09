"""Git operations for Ralph.

Provides functions for syncing with remote, pushing with retry,
checking uncommitted changes, getting commit information, and
building descriptive commit messages from iteration results.
"""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Timeouts for git subprocess calls (seconds).
# Local operations (rev-parse, status, diff, add, commit) are fast.
# Network operations (fetch, push) need more headroom.
_GIT_LOCAL_TIMEOUT = 30
_GIT_NETWORK_TIMEOUT = 120


def get_current_commit(cwd: Optional[Path] = None) -> str:
    """Get current HEAD commit hash (short).

    Args:
        cwd: Working directory for git command. Defaults to current directory.

    Returns:
        Short commit hash or "unknown" on failure.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=cwd,
            timeout=_GIT_LOCAL_TIMEOUT,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except subprocess.TimeoutExpired:
        return "unknown"


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
            timeout=_GIT_LOCAL_TIMEOUT,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
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

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", str(plan_file)],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=_GIT_LOCAL_TIMEOUT,
        )
        return bool(result.stdout.strip())
    except subprocess.TimeoutExpired:
        return False


def has_uncommitted_tix(
    plan_file: Path,
    cwd: Optional[Path] = None,
) -> bool:
    """Check if tix plan.jsonl has uncommitted changes.

    Ralph orchestration state is ephemeral (in /tmp) and is not
    tracked by git, so only plan.jsonl is checked.

    Args:
        plan_file: Path to the tix plan.jsonl file.
        cwd: Working directory for git command.

    Returns:
        True if plan.jsonl has uncommitted changes.
    """
    return has_uncommitted_plan(plan_file, cwd)


def _commit_plan_if_modified(plan_file: Optional[Path], cwd: Optional[Path]) -> None:
    """Commit plan file changes if file has uncommitted modifications.

    Args:
        plan_file: Path to plan.jsonl (tix or legacy)
        cwd: Working directory for git commands
    """
    if plan_file and has_uncommitted_plan(plan_file, cwd):
        subprocess.run(
            ["git", "add", str(plan_file)],
            cwd=cwd, capture_output=True, timeout=_GIT_LOCAL_TIMEOUT,
        )
        subprocess.run(
            ["git", "commit", "-m", "ralph: save state before sync"],
            cwd=cwd, capture_output=True, timeout=_GIT_LOCAL_TIMEOUT,
        )


def _fetch_remote(branch: str, cwd: Optional[Path]) -> bool:
    """Fetch changes from the remote for a specific branch.

    Args:
        branch: Branch name to fetch
        cwd: Working directory for git commands

    Returns:
        True if fetch succeeded, False otherwise
    """
    try:
        fetch_result = subprocess.run(
            ["git", "fetch", "origin", branch],
            capture_output=True, text=True, cwd=cwd,
            timeout=_GIT_NETWORK_TIMEOUT,
        )
        return fetch_result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def _is_branch_behind(cwd: Optional[Path]) -> bool:
    """Check if current branch is behind or has diverged.

    Args:
        cwd: Working directory for git commands

    Returns:
        True if branch is behind or has diverged, False if up to date
    """
    try:
        status_result = subprocess.run(
            ["git", "status", "-uno"],
            capture_output=True, text=True, cwd=cwd,
            timeout=_GIT_LOCAL_TIMEOUT,
        )
        return (
            "Your branch is behind" in status_result.stdout
            or "have diverged" in status_result.stdout
        )
    except subprocess.TimeoutExpired:
        return False


def _rebase_onto_remote(branch: str, cwd: Optional[Path]) -> str:
    """Attempt to rebase current branch onto remote branch.

    Args:
        branch: Branch name
        cwd: Working directory for git commands

    Returns:
        "updated" on success, "conflict" on merge conflict, "error" otherwise
    """
    try:
        rebase_result = subprocess.run(
            ["git", "rebase", f"origin/{branch}"],
            capture_output=True, text=True, cwd=cwd,
            timeout=_GIT_LOCAL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        subprocess.run(
            ["git", "rebase", "--abort"],
            capture_output=True, cwd=cwd,
            timeout=_GIT_LOCAL_TIMEOUT,
        )
        return "error"

    if rebase_result.returncode != 0:
        # Abort rebase to restore clean state
        subprocess.run(
            ["git", "rebase", "--abort"],
            capture_output=True, cwd=cwd,
            timeout=_GIT_LOCAL_TIMEOUT,
        )
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
        try:
            push_result = subprocess.run(
                ["git", "push", "origin", branch],
                capture_output=True, text=True, cwd=cwd,
                timeout=_GIT_NETWORK_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return False

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


# =============================================================================
# Iteration commit support
# =============================================================================


@dataclass
class TaskVerdict:
    """A single task accept/reject verdict for commit messages."""

    task_id: str
    name: str
    accepted: bool
    reason: str = ""


@dataclass
class IterationCommitInfo:
    """Accumulated info for building a descriptive commit message.

    Populated across BUILD and VERIFY stages within one logical
    iteration. Reset after each commit.
    """

    iteration: int = 0
    spec: str = ""
    stages_run: list[str] = field(default_factory=list)
    verdicts: list[TaskVerdict] = field(default_factory=list)
    tasks_added: list[str] = field(default_factory=list)
    issues_added: list[str] = field(default_factory=list)
    issues_investigated: int = 0

    @property
    def has_verdicts(self) -> bool:
        """True if any tasks were accepted or rejected."""
        return len(self.verdicts) > 0

    @property
    def accepted(self) -> list[TaskVerdict]:
        """Verdicts where the task was accepted."""
        return [v for v in self.verdicts if v.accepted]

    @property
    def rejected(self) -> list[TaskVerdict]:
        """Verdicts where the task was rejected."""
        return [v for v in self.verdicts if not v.accepted]

    def reset(self, iteration: int = 0) -> None:
        """Clear accumulated state for the next commit cycle."""
        self.iteration = iteration
        self.stages_run.clear()
        self.verdicts.clear()
        self.tasks_added.clear()
        self.issues_added.clear()
        self.issues_investigated = 0


def has_uncommitted_changes(cwd: Optional[Path] = None) -> bool:
    """Check if the working tree has any uncommitted changes.

    Includes both staged and unstaged modifications, additions,
    and deletions across all tracked and untracked files.

    Args:
        cwd: Working directory for git command.

    Returns:
        True if there are any uncommitted changes.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=_GIT_LOCAL_TIMEOUT,
        )
        return bool(result.stdout.strip())
    except subprocess.TimeoutExpired:
        return False


def lookup_task_names(
    plan_file: Path, task_ids: list[str]
) -> dict[str, str]:
    """Look up task names from plan.jsonl by task ID.

    Scans accept and task entries in the plan file to find the
    human-readable name for each task ID.

    Args:
        plan_file: Path to .tix/plan.jsonl.
        task_ids: List of task IDs to look up.

    Returns:
        Dict mapping task_id -> task_name. Missing IDs are omitted.
    """
    if not plan_file.exists() or not task_ids:
        return {}

    wanted = set(task_ids)
    names: dict[str, str] = {}

    try:
        for line in plan_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry_id = entry.get("id", "")
            if entry_id in wanted and "name" in entry:
                names[entry_id] = entry["name"]
    except OSError:
        pass

    return names


def build_commit_message(info: IterationCommitInfo) -> str:
    """Build a descriptive commit message from iteration results.

    Format:
        Subject: ralph: <action summary>
        Body: task details, rejection reasons, metadata

    Args:
        info: Accumulated iteration commit info.

    Returns:
        Multi-line commit message string.
    """
    accepted = info.accepted
    rejected = info.rejected

    # Build subject line
    subject = _build_subject(info, accepted, rejected)

    # Build body
    body_parts: list[str] = []

    if accepted:
        body_parts.append("Accepted:")
        for v in accepted:
            body_parts.append(f"  {v.task_id} {v.name}")

    if rejected:
        body_parts.append("Rejected:")
        for v in rejected:
            body_parts.append(f"  {v.task_id} {v.name}")
            if v.reason:
                # Truncate long reasons to keep commit readable
                reason = v.reason if len(v.reason) <= 200 else (
                    v.reason[:197] + "..."
                )
                body_parts.append(f"    reason: {reason}")

    if info.tasks_added:
        count = len(info.tasks_added)
        body_parts.append(f"Tasks created: {count}")

    if info.issues_investigated:
        body_parts.append(
            f"Issues investigated: {info.issues_investigated}"
        )

    # Footer
    footer_parts = []
    if info.spec:
        footer_parts.append(f"Spec: {info.spec}")
    if info.stages_run:
        footer_parts.append(
            f"Stages: {' -> '.join(info.stages_run)}"
        )
    footer_parts.append(f"Iteration: {info.iteration}")

    if footer_parts:
        body_parts.append("")
        body_parts.extend(footer_parts)

    if body_parts:
        return subject + "\n\n" + "\n".join(body_parts)
    return subject


def _build_subject(
    info: IterationCommitInfo,
    accepted: list[TaskVerdict],
    rejected: list[TaskVerdict],
) -> str:
    """Build the commit subject line.

    Prioritizes the most significant action: accept > reject > build.
    """
    if accepted and not rejected:
        if len(accepted) == 1:
            return f"ralph: accept {accepted[0].task_id} {accepted[0].name}"
        return f"ralph: accept {len(accepted)} tasks"
    if rejected and not accepted:
        if len(rejected) == 1:
            return f"ralph: reject {rejected[0].task_id} {rejected[0].name}"
        return f"ralph: reject {len(rejected)} tasks"
    if accepted and rejected:
        return (
            f"ralph: accept {len(accepted)}, "
            f"reject {len(rejected)} tasks"
        )
    if info.tasks_added:
        return f"ralph: create {len(info.tasks_added)} tasks"
    if info.issues_investigated:
        return (
            f"ralph: investigate {info.issues_investigated} issues"
        )
    if "BUILD" in info.stages_run:
        return f"ralph: build iteration {info.iteration}"
    return f"ralph: iteration {info.iteration}"


def get_uncommitted_diff(
    cwd: Optional[Path] = None,
    max_bytes: int = 200_000,
) -> str:
    """Get the diff of all uncommitted changes (staged + unstaged).

    Combines ``git diff HEAD`` to capture everything not yet committed.
    A ``--stat`` summary is always prepended so VERIFY sees the full
    file list even when the detailed diff is truncated.

    The result is truncated to *max_bytes* to avoid blowing up the
    VERIFY prompt context window.

    Args:
        cwd: Working directory for git command.
        max_bytes: Maximum bytes of diff output to return.

    Returns:
        Unified diff string (with stat header), or empty string if no changes.
    """
    diff = _get_raw_diff(cwd)
    if not diff:
        return ""

    stat = _get_diff_stat(cwd)
    return _assemble_diff(stat, diff, max_bytes)


def _get_raw_diff(cwd: Optional[Path] = None) -> str:
    """Run git diff HEAD, falling back to --cached."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True, text=True, cwd=cwd,
            timeout=_GIT_LOCAL_TIMEOUT,
        )
        diff = result.stdout if result.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        diff = ""
    if not diff:
        try:
            result = subprocess.run(
                ["git", "diff", "--cached"],
                capture_output=True, text=True, cwd=cwd,
                timeout=_GIT_LOCAL_TIMEOUT,
            )
            diff = result.stdout if result.returncode == 0 else ""
        except subprocess.TimeoutExpired:
            diff = ""
    return diff


def _get_diff_stat(cwd: Optional[Path] = None) -> str:
    """Run git diff HEAD --stat for a file-level summary."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--stat"],
            capture_output=True, text=True, cwd=cwd,
            timeout=_GIT_LOCAL_TIMEOUT,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        return ""


def _assemble_diff(stat: str, diff: str, max_bytes: int) -> str:
    """Combine stat header and diff body, truncating if needed."""
    header = f"--- DIFF STAT ---\n{stat}\n\n--- FULL DIFF ---\n" if stat else ""
    budget = max_bytes - len(header.encode("utf-8", errors="replace"))
    if budget < 0:
        budget = 0
    if len(diff) > budget:
        limit_kb = max_bytes // 1024
        diff = diff[:budget] + f"\n\n... (diff truncated at {limit_kb}KB) ..."
    return header + diff


def commit_iteration(
    info: IterationCommitInfo,
    cwd: Optional[Path] = None,
) -> bool:
    """Stage all changes and commit with a descriptive message.

    Runs ``git add -A`` to stage everything (code + tix state),
    then commits with a message built from the iteration info.

    Args:
        info: Accumulated iteration results.
        cwd: Working directory for git commands.

    Returns:
        True if a commit was created, False otherwise.
    """
    if not has_uncommitted_changes(cwd):
        return False

    try:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=cwd, capture_output=True,
            timeout=_GIT_LOCAL_TIMEOUT,
        )

        message = build_commit_message(info)
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=cwd, capture_output=True,
            timeout=_GIT_LOCAL_TIMEOUT,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
