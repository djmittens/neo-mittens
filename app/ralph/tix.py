"""Tix harness - Python wrapper around the tix CLI binary.

All ticket mutations go through this module. The construct harness calls
these functions instead of the agent calling CLI commands directly.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

__all__ = [
    "TixError",
    "TixResult",
    "TixProtocol",
    "Tix",
]

# Default tix binary location relative to repo root
_DEFAULT_TIX_BIN = "tix"


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


@runtime_checkable
class TixProtocol(Protocol):
    """Structural interface for tix operations.

    Both the real ``Tix`` class and test mocks satisfy this protocol.
    Use this as the type annotation for functions that accept a tix-like
    object (e.g. ``def reconcile(tix: TixProtocol, ...) -> ...``).
    """

    def query_tasks(self) -> list[dict]: ...
    def query_done_tasks(self) -> list[dict]: ...
    def query_issues(self) -> list[dict]: ...
    def query_full(self) -> dict: ...
    def task_add(self, task_json: dict) -> dict: ...
    def task_batch_add(self, tasks: list[dict]) -> list[dict]: ...
    def task_done(self, task_id: str | None = None) -> dict: ...
    def task_accept(self, task_id: str | None = None) -> dict: ...
    def task_reject(self, task_id: str, reason: str) -> dict: ...
    def task_delete(self, task_id: str) -> dict: ...
    def task_update(self, task_id: str, fields: dict) -> dict: ...
    def issue_add(self, desc: str, spec: str = "") -> dict: ...
    def issue_done(self) -> dict: ...
    def issue_done_all(self) -> dict: ...
    def issue_done_ids(self, ids: list[str]) -> dict: ...


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
            self.bin = Path(_DEFAULT_TIX_BIN)
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
        result = self._run("q", "tasks | status=pending")
        if isinstance(result.data, list):
            return result.data
        return []

    def query_done_tasks(self) -> list[dict]:
        """Get all done (awaiting verification) tasks as list of dicts."""
        result = self._run("q", "tasks | status=done")
        if isinstance(result.data, list):
            return result.data
        return []

    def query_issues(self) -> list[dict]:
        """Get all open issues as list of dicts."""
        result = self._run("q", "issues")
        if isinstance(result.data, list):
            return result.data
        return []

    def query_full(self) -> dict:
        """Get full state as dict with tasks grouped by status and issues.

        Returns dict matching the format expected by the state machine:
        {
            "tasks": {"pending": [...], "done": [...], "accepted": [...]},
            "issues": [...]
        }
        """
        out: dict = {"tasks": {}, "issues": []}
        try:
            all_tasks = self._run("q", "tasks all")
            if isinstance(all_tasks.data, list):
                # tix returns numeric status: 0=pending, 1=done, 2=accepted
                _STATUS_MAP = {0: "pending", 1: "done", 2: "accepted"}
                by_status: dict[str, list] = {}
                for t in all_tasks.data:
                    if not isinstance(t, dict):
                        continue
                    raw = t.get("status", 0)
                    s = _STATUS_MAP.get(raw, str(raw)) if isinstance(raw, int) else str(raw)
                    by_status.setdefault(s, []).append(t)
                out["tasks"] = by_status
        except TixError:
            pass
        try:
            issues = self._run("q", "issues")
            if isinstance(issues.data, list):
                out["issues"] = issues.data
        except TixError:
            pass
        return out

    def query_tql(self, tql: str) -> list[dict]:
        """Run a TQL pipeline query and return results as list of dicts.

        TQL is tix's query language supporting filters, aggregation, sorting.
        Examples:
            "tasks | group model | count | sum cost | sort sum_cost desc"
            "tasks all | status=accepted | select id,name,cost,model"
            "tasks | label=stage:build | avg cost"

        Args:
            tql: TQL pipeline string.

        Returns:
            List of result dicts (rows).
        """
        result = self._run("q", tql)
        if isinstance(result.data, list):
            return result.data
        if isinstance(result.data, dict):
            return [result.data]
        return []

    def report(self) -> str:
        """Run tix report and return the human-readable progress output.

        Returns:
            Progress report text (task counts, priorities, blocked).
        """
        result = self._run("report", parse_json=False)
        return result.raw

    def report_models(self) -> list[dict]:
        """Get per-model performance breakdown via TQL.

        Returns list of dicts with model, count, total_cost, avg_cost,
        tokens_in, tokens_out, avg_iterations — suitable for programmatic
        analysis and routing decisions.
        """
        return self.query_tql(
            "tasks all | meta.model!= | group meta.model"
            " | count | sum meta.cost | avg meta.cost"
            " | sum meta.tokens_in | sum meta.tokens_out"
            " | avg meta.iterations | sort sum_meta.cost desc"
        )

    def report_labels(self) -> list[dict]:
        """Get per-label task count and cost breakdown via TQL."""
        return self.query_tql(
            "tasks all | group label"
            " | count | sum meta.cost | avg meta.cost | sort count desc"
        )

    def report_velocity(self) -> list[dict]:
        """Get velocity metrics for completed tasks via TQL.

        Returns a single-row list with aggregated metrics across all
        completed tasks (done + accepted).

        Returns:
            List with one dict containing count, sum_meta.cost, etc.
        """
        return self.query_tql(
            "tasks all | status=done,accepted"
            " | count | sum meta.cost | avg meta.cost"
            " | sum meta.tokens_in | sum meta.tokens_out"
            " | avg meta.iterations"
            " | sum meta.retries | sum meta.kill_count"
        )

    def report_actors(self) -> list[dict]:
        """Get per-author task breakdown via TQL.

        Returns:
            List of dicts with author, count, cost metrics.
        """
        return self.query_tql(
            "tasks all | author!= | group author"
            " | count | sum meta.cost | avg meta.cost"
            " | avg meta.iterations | sort count desc"
        )

    def query_tombstones(self) -> dict:
        """Get accepted and rejected tombstones.

        Uses TQL SQL query against the tombstones table.

        Returns:
            Dict with 'accepted' and 'rejected' lists of dicts.
        """
        try:
            result = self._run(
                "q", "sql",
                "SELECT id, name, reason, is_accept FROM tombstones",
            )
        except TixError:
            return {"accepted": [], "rejected": []}

        raw = result.raw
        rows: list[dict] = []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                rows = parsed
        except (ValueError, TypeError):
            pass

        accepted: list[dict] = []
        rejected: list[dict] = []
        for row in rows:
            if row.get("is_accept"):
                accepted.append(row)
            else:
                rejected.append(row)

        return {"accepted": accepted, "rejected": rejected}

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

    def task_batch_add(self, tasks: list[dict]) -> list[dict]:
        """Add multiple tasks in a single tix call (batch add).

        Uses ``tix batch '[...]'`` which accepts a JSON array of task
        objects.  The batch command returns ``{"success": N, "errors": N}``
        rather than individual IDs, so we return a synthetic list of dicts
        with a ``"batch": True`` marker.

        Args:
            tasks: List of task dicts with name, notes, accept, deps, etc.

        Returns:
            List of dicts, one per successfully added task.
        """
        if not tasks:
            return []
        result = self._run("batch", json.dumps(tasks))
        # Batch returns {"success": N, "errors": N}
        success = result.data.get("success", 0) if isinstance(result.data, dict) else 0
        return [{"id": f"batch-{i}", "batch": True} for i in range(success)]

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

    def task_update(self, task_id: str, fields: dict) -> dict:
        """Update fields on an existing ticket.

        Used to attach telemetry data (cost, tokens, model, etc.) to a
        ticket after the agent stage completes.

        Args:
            task_id: Task ID to update.
            fields: Dict of fields to merge (e.g. cost, tokens_in, model).

        Returns:
            Dict with id and status.
        """
        result = self._run("task", "update", task_id, json.dumps(fields))
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

    def issue_add(self, desc: str, spec: str = "") -> dict:
        """Add a new issue.

        Args:
            desc: Issue description.
            spec: Optional spec name to tag the issue with.

        Returns:
            Dict with id.
        """
        issue_json: dict[str, str] = {"desc": desc}
        if spec:
            issue_json["spec"] = spec
        result = self._run("issue", "add", json.dumps(issue_json))
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

    def plan_file(self) -> Path:
        """Get the path to the tix plan.jsonl file.

        Returns .tix/plan.jsonl if it exists, otherwise falls back to
        ralph/plan.jsonl (legacy). This is the git-tracked source of truth
        for ticket data.

        Returns:
            Path to the plan.jsonl file.
        """
        tix_plan = self.cwd / ".tix" / "plan.jsonl"
        if tix_plan.exists():
            return tix_plan
        legacy = self.cwd / "ralph" / "plan.jsonl"
        if legacy.exists():
            return legacy
        return tix_plan  # Default to .tix/ for new repos

    def is_available(self) -> bool:
        """Check if tix binary is available and working."""
        try:
            self._run("status", parse_json=False)
            return True
        except (TixError, FileNotFoundError, subprocess.TimeoutExpired):
            return False
