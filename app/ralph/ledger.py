"""Run ledger for cross-session performance comparison.

Appends structured JSONL records for each construct invocation
and each iteration within it. Designed for A/B comparison across
branches, worktrees, profiles, and models.

Two files:
  - runs.jsonl:       one record per ``ralph construct`` invocation
  - iterations.jsonl: one record per iteration within a run
"""

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def _generate_run_id() -> str:
    """Generate a unique run ID from timestamp + random suffix.

    Format: YYYYMMDD_HHMMSS_<6-hex-chars>
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = hashlib.md5(f"{time.time()}{os.getpid()}".encode()).hexdigest()[:6]
    return f"{ts}_{suffix}"


def _get_git_sha(cwd: Optional[Path] = None) -> str:
    """Get current HEAD commit hash (short)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=cwd,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _get_worktree_root(cwd: Optional[Path] = None) -> str:
    """Get the worktree root (differs from git common dir in worktrees)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=cwd,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _is_worktree(cwd: Optional[Path] = None) -> bool:
    """Check if the current directory is a git worktree (not main checkout)."""
    try:
        toplevel = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=cwd,
        )
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, cwd=cwd,
        )
        if toplevel.returncode != 0 or common.returncode != 0:
            return False
        top = toplevel.stdout.strip()
        com = common.stdout.strip()
        # In a worktree, common dir is outside the toplevel
        git_dir = os.path.join(top, ".git")
        return os.path.realpath(com) != os.path.realpath(git_dir)
    except Exception:
        return False


@dataclass
class TokenBreakdown:
    """Token counts with cache separation."""

    input: int = 0
    cached: int = 0
    output: int = 0

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {"input": self.input, "cached": self.cached, "output": self.output}


@dataclass
class IterationRecord:
    """One record per iteration within a construct run."""

    run_id: str
    iteration: int
    stage: str
    model: str = ""
    is_local: bool = False
    task_id: str = ""
    cost: float = 0.0
    tokens: TokenBreakdown = field(default_factory=TokenBreakdown)
    duration_s: float = 0.0
    outcome: str = ""
    precheck_accepted: bool = False
    validation_retries: int = 0
    kill_reason: Optional[str] = None
    # Reconciliation outcome counts
    tasks_added: int = 0
    tasks_accepted: int = 0
    tasks_rejected: int = 0
    issues_added: int = 0

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        d: dict[str, Any] = {
            "run_id": self.run_id,
            "iteration": self.iteration,
            "stage": self.stage,
            "model": self.model,
            "is_local": self.is_local,
            "cost": round(self.cost, 6),
            "tokens": self.tokens.to_dict(),
            "duration_s": round(self.duration_s, 1),
            "outcome": self.outcome,
        }
        if self.task_id:
            d["task_id"] = self.task_id
        if self.precheck_accepted:
            d["precheck_accepted"] = True
        if self.validation_retries > 0:
            d["validation_retries"] = self.validation_retries
        if self.kill_reason:
            d["kill_reason"] = self.kill_reason
        # Reconciliation breakdown (only include non-zero)
        reconcile: dict[str, int] = {}
        if self.tasks_added > 0:
            reconcile["added"] = self.tasks_added
        if self.tasks_accepted > 0:
            reconcile["accepted"] = self.tasks_accepted
        if self.tasks_rejected > 0:
            reconcile["rejected"] = self.tasks_rejected
        if self.issues_added > 0:
            reconcile["issues"] = self.issues_added
        if reconcile:
            d["reconcile"] = reconcile
        return d


@dataclass
class StageBreakdown:
    """Per-stage summary within a run."""

    count: int = 0
    cost: float = 0.0
    api_calls_remote: int = 0
    api_calls_local: int = 0

    def to_dict(self) -> dict:
        """Serialize to dict."""
        d: dict[str, Any] = {"count": self.count, "cost": round(self.cost, 6)}
        if self.api_calls_remote > 0:
            d["api_calls_remote"] = self.api_calls_remote
        if self.api_calls_local > 0:
            d["api_calls_local"] = self.api_calls_local
        return d


@dataclass
class RunRecord:
    """One record per ``ralph construct`` invocation."""

    run_id: str
    spec: str = ""
    branch: str = ""
    git_sha_start: str = ""
    git_sha_end: str = ""
    worktree: str = ""
    profile: str = "default"
    config_snapshot: dict = field(default_factory=dict)
    started_at: str = ""
    ended_at: str = ""
    duration_s: float = 0.0
    exit_reason: str = ""
    iterations: int = 0
    tasks_total: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    cost: float = 0.0
    tokens: TokenBreakdown = field(default_factory=TokenBreakdown)
    api_calls_remote: int = 0
    api_calls_local: int = 0
    kills_timeout: int = 0
    kills_context: int = 0
    kills_loop: int = 0
    retries_validation: int = 0
    retries_task: int = 0
    stages: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        return {
            "run_id": self.run_id,
            "spec": self.spec,
            "branch": self.branch,
            "git_sha_start": self.git_sha_start,
            "git_sha_end": self.git_sha_end,
            "worktree": self.worktree,
            "profile": self.profile,
            "config_snapshot": self.config_snapshot,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_s": round(self.duration_s, 1),
            "exit_reason": self.exit_reason,
            "iterations": self.iterations,
            "tasks": {
                "total": self.tasks_total,
                "completed": self.tasks_completed,
                "failed": self.tasks_failed,
            },
            "cost": round(self.cost, 6),
            "tokens": self.tokens.to_dict(),
            "api_calls": {
                "remote": self.api_calls_remote,
                "local": self.api_calls_local,
            },
            "kills": {
                "timeout": self.kills_timeout,
                "context": self.kills_context,
                "loop": self.kills_loop,
            },
            "retries": {
                "validation": self.retries_validation,
                "task": self.retries_task,
            },
            "stages": {
                k: v.to_dict() if isinstance(v, StageBreakdown) else v
                for k, v in self.stages.items()
            },
        }


def _append_jsonl(path: Path, record: dict) -> None:
    """Append a single JSON record to a JSONL file.

    Creates parent directories and the file if they don't exist.
    Uses append mode to be safe for concurrent writers.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


def write_iteration(log_dir: Path, record: IterationRecord) -> None:
    """Append an iteration record to iterations.jsonl.

    Args:
        log_dir: Directory for ledger files.
        record: Iteration data to append.
    """
    path = log_dir / "iterations.jsonl"
    _append_jsonl(path, record.to_dict())


def write_run(log_dir: Path, record: RunRecord) -> None:
    """Append a run record to runs.jsonl.

    Args:
        log_dir: Directory for ledger files.
        record: Run data to append.
    """
    path = log_dir / "runs.jsonl"
    _append_jsonl(path, record.to_dict())


def load_runs(log_dir: Path) -> list[dict]:
    """Load all run records from runs.jsonl.

    Args:
        log_dir: Directory containing ledger files.

    Returns:
        List of run record dicts, newest last.
    """
    path = log_dir / "runs.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def load_iterations(log_dir: Path, run_id: Optional[str] = None) -> list[dict]:
    """Load iteration records, optionally filtered by run_id.

    Args:
        log_dir: Directory containing ledger files.
        run_id: If provided, only return iterations for this run.

    Returns:
        List of iteration record dicts.
    """
    path = log_dir / "iterations.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            if run_id and record.get("run_id") != run_id:
                continue
            records.append(record)
        except json.JSONDecodeError:
            continue
    return records


def config_snapshot(config) -> dict:
    """Extract a config snapshot for the run record.

    Captures only the fields relevant for comparison.

    Args:
        config: GlobalConfig instance.

    Returns:
        Dict with key config fields.
    """
    fields = [
        "model", "model_build", "model_verify", "model_investigate",
        "model_decompose", "model_plan", "max_iterations",
        "max_failures", "max_decompose_depth", "max_retries_per_task",
        "context_window", "stage_timeout_ms",
        # Guard limits
        "max_tokens", "max_wall_time_s", "max_api_calls",
        # Batch sizes
        "verify_batch_size", "investigate_batch_size",
        # Pressure thresholds
        "context_kill_pct", "context_compact_pct",
        # Stall detection
        "progress_stall_abort_s",
    ]
    snapshot = {}
    for f in fields:
        val = getattr(config, f, None)
        if val is not None and val != "":
            snapshot[f] = val
    return snapshot
