"""Ralph state management for loading and saving plan.jsonl."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json

from ralph.models import Task, Issue, Tombstone, RalphPlanConfig


@dataclass
class RalphState:
    """Holds the complete Ralph plan state loaded from plan.jsonl."""

    tasks: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    tombstones: dict = field(default_factory=lambda: {"accepted": [], "rejected": []})
    config: Optional[RalphPlanConfig] = None
    spec: Optional[str] = None
    current_task_id: Optional[str] = None

    # Explicit stage (persisted)
    stage: str = "PLAN"

    # DECOMPOSE state (task-centric recovery)
    decompose_target: Optional[str] = None
    decompose_reason: Optional[str] = None
    decompose_log: Optional[str] = None

    # RESCUE state (step-centric recovery for batch failures)
    rescue_stage: Optional[str] = None
    rescue_batch: list = field(default_factory=list)
    rescue_reason: Optional[str] = None
    rescue_log: Optional[str] = None

    # Batch tracking for bounded fork-join
    batch_items: list = field(default_factory=list)
    batch_completed: list = field(default_factory=list)
    batch_attempt: int = 0

    @property
    def pending(self) -> list:
        """Return tasks with status 'p' (pending)."""
        return [t for t in self.tasks if t.status == "p"]

    @property
    def done(self) -> list:
        """Return tasks with status 'd' (done, awaiting verification)."""
        return [t for t in self.tasks if t.status == "d"]

    @property
    def accepted(self) -> list:
        """Return tasks with status 'a' (accepted)."""
        return [t for t in self.tasks if t.status == "a"]

    @property
    def done_ids(self) -> set:
        """Return set of done task IDs."""
        return {t.id for t in self.done}

    @property
    def accepted_ids(self) -> set:
        """Return set of accepted task IDs (from tasks + tombstones)."""
        task_ids = {t.id for t in self.accepted}
        tombstone_ids = {t.id for t in self.tombstones["accepted"]}
        return task_ids | tombstone_ids

    @property
    def completed_ids(self) -> set:
        """Return set of all completed task IDs (done + accepted)."""
        return self.done_ids | self.accepted_ids

    def get_stage(self) -> str:
        """Return the current stage from explicit state.

        Returns:
            Stage name: INVESTIGATE, BUILD, VERIFY, DECOMPOSE, RESCUE, or COMPLETE
        """
        return self.stage

    def compute_initial_stage(self) -> str:
        """Compute initial stage for migration from old format.

        Only used when loading a plan.jsonl that doesn't have a stage record.
        """
        if self.spec is None:
            return "PLAN"
        if self.rescue_stage:
            return "RESCUE"
        if self.decompose_target:
            return "DECOMPOSE"
        if self.done:
            return "VERIFY"
        if self.issues:
            return "INVESTIGATE"
        if self.pending:
            return "BUILD"
        return "COMPLETE"

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

    def transition_to_rescue(
        self, stage: str, batch_items: list, reason: str, log_path: Optional[str] = None
    ) -> None:
        """Transition to RESCUE stage for step-centric recovery."""
        self.stage = "RESCUE"
        self.rescue_stage = stage
        self.rescue_batch = batch_items.copy()
        self.rescue_reason = reason
        self.rescue_log = log_path

    def transition_to_investigate(self) -> None:
        """Transition to INVESTIGATE stage."""
        self.stage = "INVESTIGATE"
        self._clear_decompose_state()
        self._clear_rescue_state()
        self._clear_batch_state()

    def transition_to_build(self) -> None:
        """Transition to BUILD stage."""
        self.stage = "BUILD"
        self._clear_decompose_state()
        self._clear_rescue_state()
        self._clear_batch_state()

    def transition_to_verify(self) -> None:
        """Transition to VERIFY stage."""
        self.stage = "VERIFY"
        self._clear_decompose_state()
        self._clear_rescue_state()
        self._clear_batch_state()

    def transition_to_complete(self) -> None:
        """Transition to COMPLETE stage."""
        self.stage = "COMPLETE"
        self._clear_decompose_state()
        self._clear_rescue_state()
        self._clear_batch_state()

    def _clear_decompose_state(self) -> None:
        """Clear decompose-related state fields."""
        self.decompose_target = None
        self.decompose_reason = None
        self.decompose_log = None

    def _clear_rescue_state(self) -> None:
        """Clear rescue-related state fields."""
        self.rescue_stage = None
        self.rescue_batch = []
        self.rescue_reason = None
        self.rescue_log = None

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
        # Filter out already completed items
        remaining = [i for i in items if i not in self.batch_completed]

        # If we have an in-progress batch, return it
        if self.batch_items:
            still_pending = [i for i in self.batch_items if i in remaining]
            if still_pending:
                return still_pending
            # Batch complete, clear it
            self.batch_completed.extend(self.batch_items)
            self.batch_items = []
            self.batch_attempt = 0
            remaining = [i for i in items if i not in self.batch_completed]

        # Start new batch
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

    def get_decompose_task(self) -> Optional[Task]:
        """Get the task that needs decomposition based on decompose_target."""
        if not self.decompose_target:
            return None
        return self.get_task_by_id(self.decompose_target)

    def get_next_task(self) -> Optional[Task]:
        """Get next ready task by priority and dependency order."""
        sorted_pending = self.get_sorted_pending()
        for task in sorted_pending:
            if self._deps_satisfied(task):
                return task
        return None

    def get_sorted_pending(self) -> list:
        """Return pending tasks sorted by priority and deps."""
        priority_order = {"high": 0, "medium": 1, "low": 2, None: 1}
        return sorted(
            self.pending,
            key=lambda t: (priority_order.get(t.priority, 1), t.id),
        )

    def _deps_satisfied(self, task: Task) -> bool:
        """Check if all task dependencies are satisfied."""
        if not task.deps:
            return True
        return all(dep_id in self.completed_ids for dep_id in task.deps)

    def add_task(self, task: Task) -> None:
        """Add a task to the task list."""
        self.tasks.append(task)

    def get_task_by_id(self, task_id: str) -> Optional[Task]:
        """Get a task by its ID."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def add_tombstone(self, tombstone) -> None:
        """Add a tombstone to the appropriate list."""
        if tombstone.tombstone_type == "accept":
            self.tombstones["accepted"].append(tombstone)
        else:
            self.tombstones["rejected"].append(tombstone)

    def to_dict(self) -> dict:
        """Serialize state to dict for JSON output."""
        return {
            "spec": self.spec,
            "tasks": {
                "pending": [t.to_dict() for t in self.pending],
                "done": [t.to_dict() for t in self.done],
                "accepted": [t.to_dict() for t in self.accepted],
            },
            "issues": [i.to_dict() for i in self.issues],
            "tombstones": {
                "accepted": [t.to_dict() for t in self.tombstones["accepted"]],
                "rejected": [t.to_dict() for t in self.tombstones["rejected"]],
            },
        }


def load_state(path: Path) -> RalphState:
    """Load state from plan.jsonl file.

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

        _mark_accepted_tasks(state)
    except (json.JSONDecodeError, KeyError):
        pass

    return state


def _dispatch_record(state: RalphState, d: dict) -> None:
    """Dispatch a parsed JSON record to the appropriate state field."""
    t = d.get("t")
    if t == "spec":
        state.spec = d.get("spec")
    elif t == "task":
        state.tasks.append(Task.from_dict(d))
    elif t == "issue":
        state.issues.append(Issue.from_dict(d))
    elif t == "reject":
        state.tombstones["rejected"].append(Tombstone.from_dict(d, "reject"))
    elif t == "accept":
        state.tombstones["accepted"].append(Tombstone.from_dict(d, "accept"))
    elif t == "config":
        state.config = RalphPlanConfig.from_dict(d)
    elif t == "stage":
        # Explicit state machine stage
        state.stage = d.get("stage", "PLAN")
        # DECOMPOSE state
        state.decompose_target = d.get("decompose_target")
        state.decompose_reason = d.get("decompose_reason")
        state.decompose_log = d.get("decompose_log")
        # RESCUE state
        state.rescue_stage = d.get("rescue_stage")
        state.rescue_batch = d.get("rescue_batch", [])
        state.rescue_reason = d.get("rescue_reason")
        state.rescue_log = d.get("rescue_log")
        # Batch tracking
        state.batch_items = d.get("batch_items", [])
        state.batch_completed = d.get("batch_completed", [])
        state.batch_attempt = d.get("batch_attempt", 0)


def _mark_accepted_tasks(state: RalphState) -> None:
    """Mark tasks as accepted if they have accept tombstones."""
    accepted_ids = {t.id for t in state.tombstones["accepted"]}
    for task in state.tasks:
        if task.id in accepted_ids and task.status == "d":
            task.status = "a"


def save_state(state: RalphState, path: Path) -> None:
    """Save state to plan.jsonl file.

    Args:
        state: RalphState to save
        path: Path to plan.jsonl file
    """
    lines = []

    if state.config:
        lines.append(state.config.to_jsonl())

    if state.spec:
        lines.append(json.dumps({"t": "spec", "spec": state.spec}))

    # Write explicit stage record
    lines.append(_build_stage_record(state))

    for task in state.tasks:
        lines.append(task.to_jsonl())

    for issue in state.issues:
        lines.append(issue.to_jsonl())

    for tombstone in state.tombstones["accepted"]:
        lines.append(tombstone.to_jsonl())

    for tombstone in state.tombstones["rejected"]:
        lines.append(tombstone.to_jsonl())

    path.write_text("\n".join(lines) + "\n" if lines else "")


def _build_stage_record(state: RalphState) -> str:
    """Build the stage record JSON line."""
    stage_record: dict = {"t": "stage", "stage": state.stage}

    # DECOMPOSE state
    if state.decompose_target:
        stage_record["decompose_target"] = state.decompose_target
    if state.decompose_reason:
        stage_record["decompose_reason"] = state.decompose_reason
    if state.decompose_log:
        stage_record["decompose_log"] = state.decompose_log

    # RESCUE state
    if state.rescue_stage:
        stage_record["rescue_stage"] = state.rescue_stage
    if state.rescue_batch:
        stage_record["rescue_batch"] = state.rescue_batch
    if state.rescue_reason:
        stage_record["rescue_reason"] = state.rescue_reason
    if state.rescue_log:
        stage_record["rescue_log"] = state.rescue_log

    # Batch tracking
    if state.batch_items:
        stage_record["batch_items"] = state.batch_items
    if state.batch_completed:
        stage_record["batch_completed"] = state.batch_completed
    if state.batch_attempt > 0:
        stage_record["batch_attempt"] = state.batch_attempt

    return json.dumps(stage_record)
