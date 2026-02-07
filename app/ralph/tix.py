"""Tix harness - Python wrapper around the tix CLI binary.

All ticket mutations go through this module. The construct harness calls
these functions instead of the agent calling CLI commands directly.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

__all__ = [
    "TixError",
    "TixResult",
    "Tix",
]

# Default tix binary location relative to repo root
_DEFAULT_TIX_BIN = "powerplant/tix"


class TixError(Exception):
    """Error from tix CLI invocation."""

    def __init__(self, message: str, returncode: int = 1, stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


@dataclass
class TixResult:
    """Result from a tix CLI call."""

    ok: bool
    data: dict[str, Any]
    raw: str = ""


class Tix:
    """Wrapper around the tix CLI binary.

    All methods call the tix binary as a subprocess and parse JSON output.
    This is the single point of contact between Ralph's harness and the
    ticket system.
    """

    def __init__(self, repo_root: Path, tix_bin: Optional[str] = None):
        """Initialize tix wrapper.

        Args:
            repo_root: Path to the git repository root.
            tix_bin: Path to tix binary. Defaults to powerplant/tix in repo.
        """
        if tix_bin:
            self.bin = Path(tix_bin)
        else:
            self.bin = repo_root / _DEFAULT_TIX_BIN
        self.cwd = repo_root

    def _run(self, *args: str, parse_json: bool = True) -> TixResult:
        """Run a tix command and return parsed result.

        Args:
            *args: Command arguments (e.g. "task", "add", '{"name": "..."}')
            parse_json: If True, parse stdout as JSON.

        Returns:
            TixResult with parsed data.

        Raises:
            TixError: If tix exits with non-zero code.
        """
        cmd = [str(self.bin)] + list(args)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self.cwd,
            timeout=30,
        )

        if result.returncode != 0:
            raise TixError(
                message=result.stderr.strip() or f"tix exited with code {result.returncode}",
                returncode=result.returncode,
                stderr=result.stderr,
            )

        stdout = result.stdout.strip()
        if not parse_json or not stdout:
            return TixResult(ok=True, data={}, raw=stdout)

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return TixResult(ok=True, data={}, raw=stdout)

        return TixResult(ok=True, data=data, raw=stdout)

    # =========================================================================
    # Query operations (read-only)
    # =========================================================================

    def query_tasks(self) -> list[dict]:
        """Get all pending tasks as list of dicts."""
        result = self._run("query", "tasks")
        if isinstance(result.data, list):
            return result.data
        return []

    def query_done_tasks(self) -> list[dict]:
        """Get all done (awaiting verification) tasks as list of dicts."""
        result = self._run("query", "tasks", "--done")
        if isinstance(result.data, list):
            return result.data
        return []

    def query_issues(self) -> list[dict]:
        """Get all open issues as list of dicts."""
        result = self._run("query", "issues")
        if isinstance(result.data, list):
            return result.data
        return []

    def query_full(self) -> dict:
        """Get full state as dict."""
        result = self._run("query")
        return result.data if isinstance(result.data, dict) else {}

    def status(self) -> str:
        """Get human-readable status string."""
        result = self._run("status", parse_json=False)
        return result.raw

    # =========================================================================
    # Task mutations
    # =========================================================================

    def task_add(self, task_json: dict) -> dict:
        """Add a new task.

        Args:
            task_json: Task dict with name, notes, accept, deps, etc.

        Returns:
            Dict with id and name of created task.
        """
        result = self._run("task", "add", json.dumps(task_json))
        return result.data

    def task_done(self, task_id: Optional[str] = None) -> dict:
        """Mark a task as done.

        Args:
            task_id: Task ID. If None, marks next pending task.

        Returns:
            Dict with id, status, done_at.
        """
        args = ["task", "done"]
        if task_id:
            args.append(task_id)
        result = self._run(*args)
        return result.data

    def task_accept(self, task_id: Optional[str] = None) -> dict:
        """Accept a done task (creates tombstone, removes task).

        Args:
            task_id: Task ID. If None, accepts first done task.

        Returns:
            Dict with id and status.
        """
        args = ["task", "accept"]
        if task_id:
            args.append(task_id)
        result = self._run(*args)
        return result.data

    def task_reject(self, task_id: str, reason: str) -> dict:
        """Reject a done task (resets to pending with reason).

        Args:
            task_id: Task ID to reject.
            reason: Rejection reason.

        Returns:
            Dict with id and status.
        """
        result = self._run("task", "reject", task_id, reason)
        return result.data

    def task_delete(self, task_id: str) -> dict:
        """Delete a task.

        Args:
            task_id: Task ID to delete.

        Returns:
            Dict with id and status.
        """
        result = self._run("task", "delete", task_id)
        return result.data

    def task_prioritize(self, task_id: str, priority: str) -> dict:
        """Change task priority.

        Args:
            task_id: Task ID.
            priority: Priority level (high, medium, low).

        Returns:
            Dict with id and priority.
        """
        result = self._run("task", "prioritize", task_id, priority)
        return result.data

    # =========================================================================
    # Issue mutations
    # =========================================================================

    def issue_add(self, desc: str) -> dict:
        """Add a new issue.

        Args:
            desc: Issue description.

        Returns:
            Dict with id.
        """
        result = self._run("issue", "add", desc)
        return result.data

    def issue_done(self) -> dict:
        """Resolve the first issue.

        Returns:
            Dict with id.
        """
        result = self._run("issue", "done")
        return result.data

    def issue_done_all(self) -> dict:
        """Resolve all issues.

        Returns:
            Dict with count.
        """
        result = self._run("issue", "done-all")
        return result.data

    def issue_done_ids(self, ids: list[str]) -> dict:
        """Resolve specific issues by ID.

        Args:
            ids: List of issue IDs to resolve.

        Returns:
            Dict with count.
        """
        result = self._run("issue", "done-ids", *ids)
        return result.data

    # =========================================================================
    # Utility
    # =========================================================================

    def validate(self) -> TixResult:
        """Run validation checks.

        Returns:
            TixResult (ok=True if valid).
        """
        return self._run("validate")

    def init(self) -> TixResult:
        """Initialize tix in the repo.

        Returns:
            TixResult.
        """
        return self._run("init", parse_json=False)

    def is_available(self) -> bool:
        """Check if tix binary is available and working."""
        try:
            self._run("status", parse_json=False)
            return True
        except (TixError, FileNotFoundError, subprocess.TimeoutExpired):
            return False
