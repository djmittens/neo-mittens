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
        """Get IDs of all completed tasks awaiting verification.

        Returns:
            Set of task IDs for done (not yet accepted) tasks.
        """
        return {t.id for t in self.tasks if t.status == "d"}

    @property
    def accepted(self) -> List[Task]:
        """Get all accepted tasks.

        Returns:
            List of tasks with status 'a' (accepted/verified).
        """
        return [t for t in self.tasks if t.status == "a"]

    @property
    def accepted_ids(self) -> Set[str]:
        """Get IDs of all accepted tasks.

        Returns:
            Set of task IDs for accepted tasks.
        """
        return {t.id for t in self.tasks if t.status == "a"}

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
                "accepted": [t.to_dict() for t in self.accepted],
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
    based on the record type ('t' field). Accept and reject records
    are applied after all tasks are loaded to update task statuses.

    Args:
        path: Path to the plan.jsonl file.

    Returns:
        RalphState containing all parsed records.
    """
    state = RalphState()

    if not path.exists():
        return state

    # Collect accept/reject records to apply after loading tasks
    accepts: List[Dict] = []
    rejects: List[Dict] = []

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
                    rejects.append(d)
                elif t == "accept":
                    accepts.append(d)
                elif t == "config":
                    state.config = RalphPlanConfig.from_dict(d)
            except (json.JSONDecodeError, KeyError):
                continue
    except (OSError, IOError):
        pass

    # Apply accept records: mark tasks as accepted, or create synthetic tasks for display
    # Use status "a" to distinguish accepted from done (awaiting verification)
    for accept in accepts:
        task_id = accept.get("id")
        if task_id:
            task = state.get_task_by_id(task_id)
            if task:
                # Task exists, mark it as accepted (not just done)
                task.status = "a"
                if accept.get("done_at"):
                    task.done_at = accept.get("done_at")
            else:
                # Task was compacted (removed) but accept record remains
                # Create a minimal synthetic task record for display/tracking
                # Preserve the name from the accept record if available
                synthetic_task = Task(
                    id=task_id,
                    name=accept.get("name", f"[Compacted] {task_id}"),
                    spec=state.spec or "",
                    status="a",  # Accepted, not done - won't show in VERIFY queue
                    done_at=accept.get("done_at"),
                    notes=accept.get("notes"),
                )
                state.tasks.append(synthetic_task)

    # Apply reject records: create tombstones and reset task status to pending
    for reject in rejects:
        state.tombstones.append(Tombstone.from_dict(reject, "reject"))
        # If a task was rejected, it should be back to pending (unless later accepted)
        task_id = reject.get("id")
        if task_id:
            task = state.get_task_by_id(task_id)
            if task and task.status != "d":  # Don't reset if later accepted
                task.status = "p"
                task.reject_reason = reject.get("reason")

    # Also add accept tombstones for tracking (separate from task status updates)
    for accept in accepts:
        state.tombstones.append(Tombstone.from_dict(accept, "accept"))

    return state


def validate_state(state: RalphState, valid_ids: Optional[Set[str]] = None) -> Dict:
    """Validate state for common issues like dangling dependencies.

    Checks for:
    - Dangling dependencies (deps referencing non-existent tasks)
    - Dangling parent references
    - Invalid created_from references
    - Circular dependencies

    Args:
        state: Current RalphState to validate.
        valid_ids: Optional set of all valid task IDs (current + historical).
            If None, only checks current state + tombstones.

    Returns:
        Dict with 'valid' (bool), 'errors' (list), and 'warnings' (list).
    """
    errors: List[str] = []
    warnings: List[str] = []

    if valid_ids is None:
        valid_ids = {t.id for t in state.tasks}
        valid_ids.update(t.id for t in state.tombstones)

    current_task_ids = {t.id for t in state.tasks}

    for task in state.pending:
        if task.deps:
            for dep_id in task.deps:
                if dep_id not in valid_ids:
                    errors.append(f"Task {task.id} has dangling dep: {dep_id}")

    for task in state.tasks:
        if task.parent and task.parent not in valid_ids:
            warnings.append(f"Task {task.id} has dangling parent: {task.parent}")

    for task in state.tasks:
        if task.created_from:
            if not task.created_from.startswith("i-"):
                warnings.append(
                    f"Task {task.id} has invalid created_from: {task.created_from}"
                )

    def has_cycle(task_id: str, visited: Set[str], path: Set[str]) -> bool:
        if task_id in path:
            return True
        if task_id in visited:
            return False
        visited.add(task_id)
        path.add(task_id)
        task = next((t for t in state.tasks if t.id == task_id), None)
        if task and task.deps:
            for dep_id in task.deps:
                if dep_id in current_task_ids and has_cycle(dep_id, visited, path):
                    return True
        path.remove(task_id)
        return False

    visited: Set[str] = set()
    for task in state.pending:
        if has_cycle(task.id, visited, set()):
            errors.append(f"Circular dependency detected involving task {task.id}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


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
