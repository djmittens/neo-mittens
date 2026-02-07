"""Ralph orchestration state management.

Manages stage transitions, batch tracking, and spec/config metadata.
All ticket data (tasks, issues, tombstones) is owned by tix.

load_state/save_state only read/write orchestration records from plan.jsonl
(t: "spec", t: "stage", t: "config"). Ticket lines are preserved verbatim.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json

from ralph.models import RalphPlanConfig


@dataclass
class RalphState:
    """Orchestration state for the construct loop.

    Does NOT hold ticket data (tasks, issues, tombstones) — tix owns those.
    """

    config: Optional[RalphPlanConfig] = None
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


def load_state(path: Path) -> RalphState:
    """Load orchestration state from plan.jsonl file.

    Only reads spec, stage, and config records. Ticket records
    (task, issue, accept, reject) are ignored — tix owns those.

    Args:
        path: Path to plan.jsonl file

    Returns:
        RalphState populated from the file, or empty state if file missing
    """
    state = RalphState()

    if not path.exists():
        return state

    try:
        content = path.read_text().strip()
        if not content:
            return state

        for line in content.split("\n"):
            if not line.strip():
                continue
            d = json.loads(line)
            _dispatch_record(state, d)
    except (json.JSONDecodeError, KeyError):
        pass

    return state


def _dispatch_record(state: RalphState, d: dict) -> None:
    """Dispatch a parsed JSON record to the appropriate state field."""
    t = d.get("t")
    if t == "spec":
        state.spec = d.get("spec")
    elif t == "config":
        state.config = RalphPlanConfig.from_dict(d)
    elif t == "stage":
        stage = d.get("stage", "PLAN")
        # Migrate old RESCUE stage to INVESTIGATE
        state.stage = "INVESTIGATE" if stage == "RESCUE" else stage
        # DECOMPOSE state
        state.decompose_target = d.get("decompose_target")
        state.decompose_reason = d.get("decompose_reason")
        state.decompose_log = d.get("decompose_log")
        # Batch tracking
        state.batch_items = d.get("batch_items", [])
        state.batch_completed = d.get("batch_completed", [])
        state.batch_attempt = d.get("batch_attempt", 0)
    # task, issue, accept, reject records are ignored — tix owns them


def save_state(state: RalphState, path: Path) -> None:
    """Save orchestration state to plan.jsonl file.

    Preserves all non-orchestration lines (ticket data owned by tix)
    and rewrites only the orchestration records (spec, stage, config).

    Args:
        state: RalphState to save
        path: Path to plan.jsonl file
    """
    # Read existing file and preserve ticket lines
    preserved_lines: list[str] = []
    if path.exists():
        try:
            content = path.read_text().strip()
            if content:
                for line in content.split("\n"):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        d = json.loads(stripped)
                        t = d.get("t")
                        # Skip orchestration records — we'll rewrite them
                        if t in ("spec", "stage", "config"):
                            continue
                        # Preserve everything else (task, issue, accept, reject, etc.)
                        preserved_lines.append(stripped)
                    except json.JSONDecodeError:
                        # Preserve non-JSON lines too
                        preserved_lines.append(stripped)
        except OSError:
            pass

    # Build orchestration lines
    orch_lines: list[str] = []

    if state.config:
        orch_lines.append(state.config.to_jsonl())

    if state.spec:
        orch_lines.append(json.dumps({"t": "spec", "spec": state.spec}))

    orch_lines.append(_build_stage_record(state))

    # Write: orchestration first, then preserved ticket data
    all_lines = orch_lines + preserved_lines
    path.write_text("\n".join(all_lines) + "\n" if all_lines else "")


def _build_stage_record(state: RalphState) -> str:
    """Build the stage record JSON line."""
    stage_record: dict = {"t": "stage", "stage": state.stage}

    optional_fields = [
        ("decompose_target", "decompose_target"),
        ("decompose_reason", "decompose_reason"),
        ("decompose_log", "decompose_log"),
        ("batch_items", "batch_items"),
        ("batch_completed", "batch_completed"),
    ]

    for attr, key in optional_fields:
        value = getattr(state, attr, None)
        if value:
            stage_record[key] = value

    if state.batch_attempt > 0:
        stage_record["batch_attempt"] = state.batch_attempt

    return json.dumps(stage_record)
