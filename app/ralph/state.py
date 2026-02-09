"""Ralph orchestration state management.

Manages stage transitions, batch tracking, and spec/config metadata.
All ticket data (tasks, issues, tombstones) is owned by tix.

State is ephemeral — stored under /tmp keyed by a hash of the repo
root path.  If the file is missing or corrupted, Ralph starts fresh
(correct behaviour for runtime orchestration state).  This avoids
polluting the project tree and eliminates corruption risk from
interrupted writes to in-repo files.
"""

import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json


# Subdirectory under /tmp for Ralph state files
_STATE_DIR_PREFIX = "ralph-state"
STATE_FILENAME = "ralph-state.json"


@dataclass
class RalphState:
    """Orchestration state for the construct loop.

    Does NOT hold ticket data (tasks, issues, tombstones) — tix owns those.
    """

    spec: Optional[str] = None

    # Explicit stage (persisted)
    stage: str = "PLAN"

    # DECOMPOSE state (task-centric recovery)
    decompose_target: Optional[str] = None
    decompose_reason: Optional[str] = None
    decompose_log: Optional[str] = None

    # Batch tracking for bounded fork-join
    batch_items: list = field(default_factory=list)
    batch_completed: list = field(default_factory=list)
    batch_attempt: int = 0

    def get_stage(self) -> str:
        """Return the current stage from explicit state."""
        return self.stage

    # =========================================================================
    # State Transition Methods
    # =========================================================================

    def transition_to_decompose(
        self, task_id: str, reason: str, log_path: Optional[str] = None
    ) -> None:
        """Transition to DECOMPOSE stage for a specific task."""
        self.stage = "DECOMPOSE"
        self.decompose_target = task_id
        self.decompose_reason = reason
        self.decompose_log = log_path

    def transition_to_investigate(self) -> None:
        """Transition to INVESTIGATE stage."""
        self.stage = "INVESTIGATE"
        self._clear_decompose_state()
        self._clear_batch_state()

    def transition_to_build(self) -> None:
        """Transition to BUILD stage."""
        self.stage = "BUILD"
        self._clear_decompose_state()
        self._clear_batch_state()

    def transition_to_verify(self) -> None:
        """Transition to VERIFY stage."""
        self.stage = "VERIFY"
        self._clear_decompose_state()
        self._clear_batch_state()

    def transition_to_complete(self) -> None:
        """Transition to COMPLETE stage."""
        self.stage = "COMPLETE"
        self._clear_decompose_state()
        self._clear_batch_state()

    def _clear_decompose_state(self) -> None:
        """Clear decompose-related state fields."""
        self.decompose_target = None
        self.decompose_reason = None
        self.decompose_log = None

    def _clear_batch_state(self) -> None:
        """Clear batch-related state fields."""
        self.batch_items = []
        self.batch_completed = []
        self.batch_attempt = 0

    # =========================================================================
    # Batch Management Methods
    # =========================================================================

    def get_next_batch(self, items: list, batch_size: int) -> list:
        """Get the next batch of items to process.

        Args:
            items: All items that need processing (task IDs or issue IDs)
            batch_size: Maximum items per batch

        Returns:
            List of item IDs for this batch, or empty list if all done
        """
        remaining = [i for i in items if i not in self.batch_completed]

        if self.batch_items:
            still_pending = [i for i in self.batch_items if i in remaining]
            if still_pending:
                return still_pending
            self.batch_completed.extend(self.batch_items)
            self.batch_items = []
            self.batch_attempt = 0
            remaining = [i for i in items if i not in self.batch_completed]

        if not remaining:
            return []

        self.batch_items = remaining[:batch_size]
        self.batch_attempt = 1
        return self.batch_items

    def mark_batch_complete(self) -> None:
        """Mark the current batch as complete."""
        if self.batch_items:
            self.batch_completed.extend(self.batch_items)
            self.batch_items = []
            self.batch_attempt = 0

    def mark_batch_failed(self, max_retries: int = 2) -> bool:
        """Mark the current batch as failed.

        Args:
            max_retries: Maximum retry attempts per batch

        Returns:
            True if should retry, False if max retries exceeded
        """
        self.batch_attempt += 1
        return self.batch_attempt <= max_retries

    def get_batch_progress(self) -> dict:
        """Get current batch progress info."""
        return {
            "current_batch": self.batch_items,
            "completed_batches": len(self.batch_completed),
            "attempt": self.batch_attempt,
        }


def _repo_hash(repo_root: Path) -> str:
    """Stable short hash of the resolved repo path.

    Uses SHA-256 truncated to 12 hex chars — enough to avoid
    collisions across repos on the same machine.

    Args:
        repo_root: Repository root directory.

    Returns:
        12-character hex string.
    """
    canonical = str(repo_root.resolve())
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def _state_path(repo_root: Path) -> Path:
    """Get the path to the ephemeral ralph-state.json.

    State lives under ``/tmp/ralph-state/<repo-hash>/ralph-state.json``
    so it never pollutes the project tree and is automatically cleaned
    on reboot.

    Args:
        repo_root: Repository root directory.

    Returns:
        Path to the ephemeral state file.
    """
    base = Path(tempfile.gettempdir()) / _STATE_DIR_PREFIX / _repo_hash(repo_root)
    return base / STATE_FILENAME


def load_state(repo_root: Path) -> RalphState:
    """Load orchestration state from the ephemeral state file.

    Falls back to ``.tix/ralph-state.json`` in the repo if the
    ephemeral file does not exist yet (one-time migration).

    Args:
        repo_root: Repository root directory.

    Returns:
        RalphState populated from the file, or empty state if missing.
    """
    path = _state_path(repo_root)
    state = RalphState()

    # Try ephemeral location first
    if path.exists():
        _try_load(state, path)
        return state

    # One-time migration: check legacy in-repo location
    legacy = repo_root / ".tix" / STATE_FILENAME
    if legacy.exists():
        _try_load(state, legacy)
        # Migrate: persist to ephemeral location so we don't read
        # the legacy file again, then remove the in-repo copy.
        save_state(state, repo_root)
        try:
            legacy.unlink()
        except OSError:
            pass
        return state

    return state


def _try_load(state: RalphState, path: Path) -> None:
    """Attempt to load state from *path*, ignoring errors.

    Args:
        state: RalphState to populate in place.
        path: File to read.
    """
    try:
        content = path.read_text().strip()
        if not content:
            return
        d = json.loads(content)
        _populate_from_dict(state, d)
    except (json.JSONDecodeError, KeyError, OSError):
        pass


def _populate_from_dict(state: RalphState, d: dict) -> None:
    """Populate RalphState fields from a dict."""
    state.spec = d.get("spec")
    stage = d.get("stage", "PLAN")
    # Migrate old RESCUE stage to INVESTIGATE
    state.stage = "INVESTIGATE" if stage == "RESCUE" else stage
    state.decompose_target = d.get("decompose_target")
    state.decompose_reason = d.get("decompose_reason")
    state.decompose_log = d.get("decompose_log")
    state.batch_items = d.get("batch_items", [])
    state.batch_completed = d.get("batch_completed", [])
    state.batch_attempt = d.get("batch_attempt", 0)


def save_state(state: RalphState, repo_root: Path) -> None:
    """Save orchestration state to the ephemeral state file.

    Uses atomic write (write to temp, then rename) to prevent
    corruption if the process is killed mid-write.

    Args:
        state: RalphState to save.
        repo_root: Repository root directory.
    """
    path = _state_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    d: dict = {"stage": state.stage}

    if state.spec:
        d["spec"] = state.spec

    _add_optional_fields(state, d)

    # Atomic write: temp file in same directory, then rename.
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(d, indent=2) + "\n")
    os.replace(str(tmp_path), str(path))


def _add_optional_fields(state: RalphState, d: dict) -> None:
    """Add non-default optional fields to the state dict."""
    optional = [
        ("decompose_target", state.decompose_target),
        ("decompose_reason", state.decompose_reason),
        ("decompose_log", state.decompose_log),
        ("batch_items", state.batch_items),
        ("batch_completed", state.batch_completed),
    ]
    for key, value in optional:
        if value:
            d[key] = value
    if state.batch_attempt > 0:
        d["batch_attempt"] = state.batch_attempt
