"""State management for Ralph's plan.jsonl files.

This module provides the RalphState class and functions for loading and saving
Ralph plan state to JSONL files. The JSONL format is designed to be Git-friendly,
with each record on its own line for clean diffs and easy merges.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from ralph.models import Issue, RalphPlanConfig, Task, Tombstone


@dataclass
class RalphState:
    """State container for a Ralph plan.

    Holds all tasks, issues, tombstones, and configuration for a Ralph plan.
    Provides methods for querying the current state and determining the next
    action to take.

    Attributes:
        spec: Path to the spec file for this plan.
        tasks: List of all tasks (pending and done).
        issues: List of issues awaiting investigation.
        tombstones: List of rejected task records.
        config: Optional plan-level configuration.
    """

    spec: Optional[str] = None
    tasks: List[Task] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)
    tombstones: List[Tombstone] = field(default_factory=list)
    config: Optional[RalphPlanConfig] = None

    @property
    def pending(self) -> List[Task]:
        """Get all pending tasks.

        Returns:
            List of tasks with status 'p' (pending).
        """
        return [t for t in self.tasks if t.status == "p"]

    @property
    def done(self) -> List[Task]:
        """Get all completed tasks.

        Returns:
            List of tasks with status 'd' (done).
        """
        return [t for t in self.tasks if t.status == "d"]

    @property
    def done_ids(self) -> Set[str]:
        """Get IDs of all completed tasks.

        Returns:
            Set of task IDs for completed tasks.
        """
        return {t.id for t in self.tasks if t.status == "d"}

    @property
    def task_ids(self) -> Set[str]:
        """Get IDs of all tasks.

        Returns:
            Set of all task IDs.
        """
        return {t.id for t in self.tasks}

    def get_task_by_id(self, task_id: str) -> Optional[Task]:
        """Get a task by its ID.

        Args:
            task_id: The task ID to look up.

        Returns:
            The task if found, None otherwise.
        """
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def get_issue_by_id(self, issue_id: str) -> Optional[Issue]:
        """Get an issue by its ID.

        Args:
            issue_id: The issue ID to look up.

        Returns:
            The issue if found, None otherwise.
        """
        for issue in self.issues:
            if issue.id == issue_id:
                return issue
        return None

    def get_sorted_pending(self) -> List[Task]:
        """Get pending tasks sorted by priority and dependencies.

        Tasks are sorted first by priority (high > medium > low > None),
        then by topological order based on dependencies.

        Returns:
            Sorted list of pending tasks.
        """
        pending = self.pending
        if not pending:
            return []

        priority_order = {"high": 0, "medium": 1, "low": 2, None: 3}

        def can_run(task: Task) -> bool:
            if not task.deps:
                return True
            return all(dep in self.done_ids for dep in task.deps)

        runnable = [t for t in pending if can_run(t)]
        runnable.sort(key=lambda t: (priority_order.get(t.priority, 3), t.id))
        return runnable

    def get_next_task(self) -> Optional[Task]:
        """Get the next task to work on.

        Returns the highest priority runnable task (one whose dependencies
        are all satisfied).

        Returns:
            The next task to work on, or None if no tasks are runnable.
        """
        sorted_pending = self.get_sorted_pending()
        return sorted_pending[0] if sorted_pending else None

    def get_task_needing_decompose(self) -> Optional[Task]:
        """Get a task that needs decomposition.

        Returns:
            A pending task with needs_decompose=True, or None.
        """
        for task in self.pending:
            if task.needs_decompose:
                return task
        return None

    def get_stage(self) -> str:
        """Determine the current construct stage.

        Returns:
            One of: 'PLAN', 'INVESTIGATE', 'DECOMPOSE', 'BUILD', 'VERIFY', 'COMPLETE'.
        """
        if not self.tasks and not self.issues:
            return "PLAN"

        if self.issues:
            return "INVESTIGATE"

        task_needing_decompose = self.get_task_needing_decompose()
        if task_needing_decompose:
            return "DECOMPOSE"

        next_task = self.get_next_task()
        if next_task:
            if next_task.status == "d":
                return "VERIFY"
            return "BUILD"

        if all(t.status == "d" for t in self.tasks):
            return "COMPLETE"

        return "BUILD"

    def get_next(self) -> Dict:
        """Get the next action to take.

        Returns a dictionary describing what should happen next in the
        construct loop.

        Returns:
            Dictionary with 'action' key and relevant context.
        """
        stage = self.get_stage()

        if stage == "PLAN":
            return {"action": "PLAN", "reason": "No tasks or issues exist"}

        if stage == "INVESTIGATE":
            return {
                "action": "INVESTIGATE",
                "issue": self.issues[0].to_dict() if self.issues else None,
            }

        if stage == "DECOMPOSE":
            task = self.get_task_needing_decompose()
            return {
                "action": "DECOMPOSE",
                "task": task.to_dict() if task else None,
            }

        if stage == "BUILD":
            task = self.get_next_task()
            return {
                "action": "BUILD",
                "task": task.to_dict() if task else None,
            }

        if stage == "VERIFY":
            done_tasks = [t for t in self.done if t.done_at]
            task = done_tasks[-1] if done_tasks else None
            return {
                "action": "VERIFY",
                "task": task.to_dict() if task else None,
            }

        return {"action": "COMPLETE", "reason": "All tasks completed"}

    def to_dict(self) -> Dict:
        """Convert state to a dictionary for JSON output.

        Returns:
            Dictionary representation of the state.
        """
        return {
            "spec": self.spec,
            "tasks": {
                "pending": [t.to_dict() for t in self.pending],
                "done": [t.to_dict() for t in self.done],
            },
            "issues": [i.to_dict() for i in self.issues],
            "stage": self.get_stage(),
            "next": self.get_next(),
        }

    def add_task(self, task: Task) -> None:
        """Add a task to the state.

        Args:
            task: The task to add.
        """
        self.tasks.append(task)

    def add_issue(self, issue: Issue) -> None:
        """Add an issue to the state.

        Args:
            issue: The issue to add.
        """
        self.issues.append(issue)

    def add_tombstone(self, tombstone: Tombstone) -> None:
        """Add a tombstone to the state.

        Args:
            tombstone: The tombstone to add.
        """
        self.tombstones.append(tombstone)

    def remove_issue(self, issue_id: str) -> bool:
        """Remove an issue by ID.

        Args:
            issue_id: The issue ID to remove.

        Returns:
            True if issue was found and removed, False otherwise.
        """
        for i, issue in enumerate(self.issues):
            if issue.id == issue_id:
                self.issues.pop(i)
                return True
        return False


def load_state(path: Path) -> RalphState:
    """Load state from a plan.jsonl file.

    Parses the JSONL file line by line, creating appropriate objects
    based on the record type ('t' field).

    Args:
        path: Path to the plan.jsonl file.

    Returns:
        RalphState containing all parsed records.
    """
    state = RalphState()

    if not path.exists():
        return state

    try:
        content = path.read_text()
        for line in content.strip().split("\n"):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                t = d.get("t")
                if t == "spec":
                    state.spec = d.get("spec")
                elif t == "task":
                    state.tasks.append(Task.from_dict(d))
                elif t == "issue":
                    state.issues.append(Issue.from_dict(d))
                elif t == "reject":
                    state.tombstones.append(Tombstone.from_dict(d))
                elif t == "config":
                    state.config = RalphPlanConfig.from_dict(d)
            except (json.JSONDecodeError, KeyError):
                continue
    except (OSError, IOError):
        pass

    return state


def save_state(state: RalphState, path: Path) -> None:
    """Save state to a plan.jsonl file.

    Serializes the state to JSONL format with records in this order:
    1. Config (if present)
    2. Spec (if present)
    3. All tasks
    4. All issues
    5. All tombstones

    Args:
        state: The RalphState to save.
        path: Path to write the plan.jsonl file.
    """
    lines: List[str] = []

    if state.config:
        lines.append(state.config.to_jsonl())

    if state.spec:
        lines.append(json.dumps({"t": "spec", "spec": state.spec}))

    for task in state.tasks:
        lines.append(task.to_jsonl())

    for issue in state.issues:
        lines.append(issue.to_jsonl())

    for tombstone in state.tombstones:
        lines.append(tombstone.to_jsonl())

    path.write_text("\n".join(lines) + "\n" if lines else "")
