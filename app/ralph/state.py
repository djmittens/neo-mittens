"""Ralph orchestration state management.

Manages stage transitions, batch tracking, and spec/config metadata.
All ticket data (tasks, issues, tombstones) is owned by tix.

State is stored in .tix/ralph-state.json — a small JSON file separate
from tix's plan.jsonl. This cleanly separates orchestration concerns
(stage, batch progress, decompose target) from ticket data.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json


# Default state file location relative to repo root
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


def _state_path(repo_root: Path) -> Path:
    """Get the path to ralph-state.json.

    Args:
        repo_root: Repository root directory.

    Returns:
        Path to .tix/ralph-state.json
    """
    return repo_root / ".tix" / STATE_FILENAME


def load_state(repo_root: Path) -> RalphState:
    """Load orchestration state from .tix/ralph-state.json.

    Args:
        repo_root: Repository root directory.

    Returns:
        RalphState populated from the file, or empty state if file missing.
    """
    path = _state_path(repo_root)
    state = RalphState()

    if not path.exists():
        return state

    try:
        content = path.read_text().strip()
        if not content:
            return state
        d = json.loads(content)
        _populate_from_dict(state, d)
    except (json.JSONDecodeError, KeyError, OSError):
        pass

    return state


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
    """Save orchestration state to .tix/ralph-state.json.

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
    path.write_text(json.dumps(d, indent=2) + "\n")


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
