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
        """Determine the current stage based on state.

        Returns:
            Stage name: INVESTIGATE, BUILD, VERIFY, DECOMPOSE, or COMPLETE
        """
        if self.issues:
            return "INVESTIGATE"
        if not self.pending:
            return "COMPLETE"
        next_task = self.get_next_task()
        if next_task:
            if next_task.status == "d":
                return "VERIFY"
            if next_task.needs_decompose:
                return "DECOMPOSE"
            return "BUILD"
        return "BUILD"

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

    for task in state.tasks:
        lines.append(task.to_jsonl())

    for issue in state.issues:
        lines.append(issue.to_jsonl())

    for tombstone in state.tombstones["accepted"]:
        lines.append(tombstone.to_jsonl())

    for tombstone in state.tombstones["rejected"]:
        lines.append(tombstone.to_jsonl())

    path.write_text("\n".join(lines) + "\n" if lines else "")
