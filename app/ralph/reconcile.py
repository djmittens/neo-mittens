"""Reconcile agent structured output with the ticket system via tix.

The agent outputs structured JSON as its final message. This module
parses that output and applies the corresponding ticket mutations
through the tix harness. The agent never calls tix directly.

Each stage has a specific output schema the agent must produce.
The reconcile functions validate the schema, apply mutations, and
return a summary of what was done.
"""

import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

from ralph.tix import Tix, TixError, TixProtocol

__all__ = [
    "ReconcileResult",
    "reconcile_build",
    "reconcile_verify",
    "reconcile_investigate",
    "reconcile_decompose",
    "reconcile_plan",
    "extract_structured_output",
]

# Marker the agent wraps its structured output in
OUTPUT_MARKER = "[RALPH_OUTPUT]"
OUTPUT_END_MARKER = "[/RALPH_OUTPUT]"


@dataclass
class ReconcileResult:
    """Summary of reconciliation actions taken."""

    ok: bool = True
    tasks_added: list[str] = field(default_factory=list)
    tasks_accepted: list[str] = field(default_factory=list)
    tasks_rejected: list[str] = field(default_factory=list)
    tasks_deleted: list[str] = field(default_factory=list)
    issues_added: list[str] = field(default_factory=list)
    issues_cleared: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """One-line summary of actions taken."""
        parts = []
        if self.tasks_added:
            parts.append(f"{len(self.tasks_added)} tasks added")
        if self.tasks_accepted:
            parts.append(f"{len(self.tasks_accepted)} accepted")
        if self.tasks_rejected:
            parts.append(f"{len(self.tasks_rejected)} rejected")
        if self.tasks_deleted:
            parts.append(f"{len(self.tasks_deleted)} deleted")
        if self.issues_added:
            parts.append(f"{len(self.issues_added)} issues added")
        if self.issues_cleared:
            parts.append(f"{self.issues_cleared} issues cleared")
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return ", ".join(parts) if parts else "no changes"


def extract_structured_output(agent_output: str) -> Optional[dict]:
    """Extract structured JSON from agent output.

    The agent wraps its structured output between markers:
        [RALPH_OUTPUT]
        {"verdict": "done", ...}
        [/RALPH_OUTPUT]

    Args:
        agent_output: Full stdout from the agent run.

    Returns:
        Parsed dict, or None if no structured output found.
    """
    # Try marker-based extraction first
    start = agent_output.find(OUTPUT_MARKER)
    end = agent_output.find(OUTPUT_END_MARKER)
    if start != -1 and end != -1:
        json_str = agent_output[start + len(OUTPUT_MARKER):end].strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # Fallback: find last JSON object in output (for robustness)
    # Look for last {...} block
    last_json = _find_last_json_object(agent_output)
    if last_json is not None:
        return last_json

    return None


def _find_last_json_object(text: str) -> Optional[dict]:
    """Find the last valid JSON object in text."""
    # Search backwards for closing brace
    pos = len(text)
    while pos > 0:
        pos = text.rfind("}", 0, pos)
        if pos == -1:
            break
        # Find matching opening brace
        depth = 0
        for i in range(pos, -1, -1):
            if text[i] == "}":
                depth += 1
            elif text[i] == "{":
                depth -= 1
            if depth == 0:
                candidate = text[i:pos + 1]
                try:
                    obj = json.loads(candidate)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    break
        pos -= 1
    return None


# =============================================================================
# Stage-specific reconcilers
# =============================================================================


def reconcile_build(
    tix: TixProtocol,
    agent_output: str,
    task_id: str,
    stage_metrics: Optional[dict[str, Any]] = None,
) -> ReconcileResult:
    """Reconcile BUILD stage output.

    Expected agent output schema:
    {
        "verdict": "done" | "blocked",
        "issues": [{"desc": "..."}],       // optional, discovered issues
        "summary": "what was done"          // optional
    }

    Args:
        tix: Tix harness instance.
        agent_output: Full agent stdout.
        task_id: The task ID that was being built.
        stage_metrics: Optional telemetry dict with keys like cost,
            tokens_in, tokens_out, iterations, model, retries, kill_count.

    Returns:
        ReconcileResult with actions taken.
    """
    result = ReconcileResult()
    data = extract_structured_output(agent_output)

    if data is None:
        # No structured output — check if agent exited cleanly
        # Conservative: don't mark done without explicit verdict
        result.errors.append("No structured output from agent")
        result.ok = False
        return result

    verdict = data.get("verdict", "")

    if verdict == "done":
        try:
            tix.task_done(task_id)
            result.tasks_added.clear()  # no-op, just for clarity
        except TixError as e:
            result.errors.append(f"Failed to mark task done: {e}")
            result.ok = False

        # Attach telemetry to the ticket if available
        if stage_metrics and result.ok:
            try:
                tix.task_update(task_id, stage_metrics)
            except TixError:
                pass  # best-effort; don't fail the build over telemetry

    elif verdict == "blocked":
        # Task could not be completed — log why
        reason = data.get("reason", "Agent reported task blocked")
        result.errors.append(f"Task blocked: {reason}")
        result.ok = False

    else:
        result.errors.append(f"Unknown verdict: {verdict!r}")
        result.ok = False

    # Process discovered issues
    _add_issues(tix, data.get("issues", []), result)

    return result


def reconcile_verify(
    tix: TixProtocol,
    agent_output: str,
) -> ReconcileResult:
    """Reconcile VERIFY stage output.

    Expected agent output schema:
    {
        "results": [
            {"task_id": "t-xxx", "passed": true},
            {"task_id": "t-yyy", "passed": false, "reason": "diagnostic..."}
        ],
        "issues": [{"desc": "...", "priority": "high"}],
        "spec_complete": true | false,
        "new_tasks": [{"name": "...", "notes": "...", "accept": "..."}]
    }

    VERIFY is the primary source of issues. It sees all failures and can
    synthesize cross-cutting patterns (e.g., multiple tasks failing for the
    same root cause). Issues are investigated in the next INVESTIGATE stage.

    Args:
        tix: Tix harness instance.
        agent_output: Full agent stdout.

    Returns:
        ReconcileResult with accept/reject actions taken.
    """
    result = ReconcileResult()
    data = extract_structured_output(agent_output)

    if data is None:
        result.errors.append("No structured output from agent")
        result.ok = False
        return result

    # Process task verdicts
    for item in data.get("results", []):
        task_id = item.get("task_id", "")
        passed = item.get("passed", False)

        if not task_id:
            result.errors.append("Verify result missing task_id")
            continue

        if passed:
            _accept_task(tix, task_id, result)
        else:
            reason = item.get("reason", "Failed verification")
            _reject_task(tix, task_id, reason, result)

    # Process cross-cutting issues surfaced by VERIFY
    _add_issues(tix, data.get("issues", []), result)

    # Process new tasks from uncovered spec criteria
    for task_data in data.get("new_tasks", []):
        _add_task(tix, task_data, result)

    return result


def reconcile_investigate(
    tix: TixProtocol,
    agent_output: str,
    batch_issue_ids: Optional[list[str]] = None,
) -> ReconcileResult:
    """Reconcile INVESTIGATE stage output.

    Expected agent output schema:
    {
        "tasks": [
            {"name": "...", "notes": "...", "accept": "...", "priority": "..."},
            ...
        ],
        "out_of_scope": ["i-xxx"],    // optional
        "summary": "..."              // optional
    }

    After creating tasks, only the issues in the current batch are cleared.
    This is batch-aware: issues outside the batch are preserved for the
    next batch iteration.

    Args:
        tix: Tix harness instance.
        agent_output: Full agent stdout.
        batch_issue_ids: Issue IDs in the current batch to clear.
            If None, clears all issues (legacy fallback).

    Returns:
        ReconcileResult with tasks added and issues cleared.
    """
    result = ReconcileResult()
    data = extract_structured_output(agent_output)

    if data is None:
        result.errors.append("No structured output from agent")
        result.ok = False
        return result

    # Add all investigation tasks
    for task_data in data.get("tasks", []):
        _add_task(tix, task_data, result)

    # Clear only the batch's issues (or all if no batch specified)
    try:
        if batch_issue_ids:
            tix.issue_done_ids(batch_issue_ids)
            result.issues_cleared = len(batch_issue_ids)
        else:
            tix.issue_done_all()
            result.issues_cleared = len(data.get("tasks", [])) + len(
                data.get("out_of_scope", [])
            )
    except TixError:
        # No issues to clear is fine
        pass

    return result


def reconcile_decompose(
    tix: TixProtocol,
    agent_output: str,
    original_task_id: str,
    parent_depth: int = 0,
) -> ReconcileResult:
    """Reconcile DECOMPOSE stage output.

    Expected agent output schema:
    {
        "subtasks": [
            {"name": "...", "notes": "...", "accept": "...", "deps": [...]},
            ...
        ]
    }

    Creates subtasks with parent link and incremented decompose_depth,
    then deletes original task.

    Args:
        tix: Tix harness instance.
        agent_output: Full agent stdout.
        original_task_id: The task being decomposed.
        parent_depth: Decompose depth of the parent task.

    Returns:
        ReconcileResult with subtasks added and original deleted.
    """
    result = ReconcileResult()
    data = extract_structured_output(agent_output)

    if data is None:
        result.errors.append("No structured output from agent")
        result.ok = False
        return result

    subtasks = data.get("subtasks", [])
    if not subtasks:
        result.errors.append("No subtasks in decompose output")
        result.ok = False
        return result

    # Add each subtask with parent link and incremented depth
    child_depth = parent_depth + 1
    for task_data in subtasks:
        task_data["parent"] = original_task_id
        task_data["decompose_depth"] = child_depth
        _add_task(tix, task_data, result)

    # Delete original task (only if subtasks were added)
    if result.tasks_added:
        try:
            tix.task_delete(original_task_id)
            result.tasks_deleted.append(original_task_id)
        except TixError as e:
            result.errors.append(f"Failed to delete original task: {e}")

    return result


def reconcile_plan(
    tix: TixProtocol,
    agent_output: str,
    spec_name: str,
) -> ReconcileResult:
    """Reconcile PLAN stage output — incremental add/drop.

    Expected agent output schema:
    {
        "tasks": [
            {"name": "...", "notes": "...", "accept": "...", "deps": [...]},
            ...
        ],
        "drop": ["t-abc123", ...]  // optional: IDs of obsolete tasks to remove
    }

    The agent only outputs NEW tasks to add. Existing pending tasks that
    the agent wants to keep are simply omitted from output. Tasks the
    agent wants to remove are listed in the "drop" array.

    Args:
        tix: Tix harness instance.
        agent_output: Full agent stdout.
        spec_name: The spec file being planned.

    Returns:
        ReconcileResult with tasks added and dropped.
    """
    result = ReconcileResult()
    data = extract_structured_output(agent_output)

    if data is None:
        result.errors.append("No structured output from agent")
        result.ok = False
        return result

    raw_tasks = data.get("tasks", [])
    drop_ids = data.get("drop", [])

    # Drop obsolete tasks first (so IDs don't conflict with new tasks)
    for task_id in drop_ids:
        if not isinstance(task_id, str) or not task_id:
            continue
        try:
            tix.task_delete(task_id)
            result.tasks_deleted.append(task_id)
        except TixError as e:
            result.errors.append(f"Failed to drop {task_id}: {e}")

    # Allow plans with only drops and no new tasks
    if not raw_tasks and not drop_ids:
        result.errors.append("No tasks or drops in plan output")
        result.ok = False
        return result

    # Inject spec name into all new tasks
    tasks_to_add = []
    for task_data in raw_tasks:
        if not task_data.get("name"):
            result.errors.append("Task missing name field")
            continue
        task_data["spec"] = spec_name
        task_data.setdefault("assigned", "ralph")
        tasks_to_add.append(task_data)

    if tasks_to_add:
        # Batch add via tix (single subprocess call)
        try:
            added = tix.task_batch_add(tasks_to_add)
            for resp in added:
                task_id = resp.get("id", "")
                if task_id:
                    result.tasks_added.append(task_id)
        except TixError as e:
            result.errors.append(f"Batch add failed: {e}")
            # Fallback: try individual adds
            for task_data in tasks_to_add:
                _add_task(tix, task_data, result)

    return result


# =============================================================================
# Helpers
# =============================================================================


def _add_task(tix: TixProtocol, task_data: dict, result: ReconcileResult) -> None:
    """Add a single task via tix, updating result."""
    name = task_data.get("name", "")
    if not name:
        result.errors.append("Task missing name field")
        return

    # Tag all tasks created by ralph so they can be filtered by assignee
    task_data.setdefault("assigned", "ralph")

    try:
        resp = tix.task_add(task_data)
        task_id = resp.get("id", "")
        if task_id:
            result.tasks_added.append(task_id)
    except TixError as e:
        result.errors.append(f"Failed to add task '{name}': {e}")


def _accept_task(tix: TixProtocol, task_id: str, result: ReconcileResult) -> None:
    """Accept a task via tix, updating result."""
    try:
        tix.task_accept(task_id)
        result.tasks_accepted.append(task_id)
    except TixError as e:
        result.errors.append(f"Failed to accept {task_id}: {e}")


def _reject_task(
    tix: TixProtocol, task_id: str, reason: str, result: ReconcileResult
) -> None:
    """Reject a task via tix, updating result.

    Also increments reject_count so the harness can detect stuck tasks.
    """
    try:
        tix.task_reject(task_id, reason)
        result.tasks_rejected.append(task_id)
    except TixError as e:
        result.errors.append(f"Failed to reject {task_id}: {e}")
        return

    _increment_reject_count(tix, task_id)


def _increment_reject_count(tix: TixProtocol, task_id: str) -> None:
    """Increment reject_count on a task for pattern detection.

    Best-effort: failure here does not affect reconciliation.
    """
    try:
        full = tix.query_full()
        all_tasks = (
            full.get("tasks", {}).get("pending", [])
            + full.get("tasks", {}).get("done", [])
        )
        task = next(
            (t for t in all_tasks if t.get("id") == task_id), None
        )
        current = task.get("reject_count", 0) if task else 0
        tix.task_update(task_id, {"reject_count": current + 1})
    except (TixError, Exception):
        pass


def _add_issues(
    tix: TixProtocol, issues: list[dict], result: ReconcileResult
) -> None:
    """Add discovered issues via tix, updating result."""
    for issue in issues:
        desc = issue.get("desc", "")
        if not desc:
            continue
        try:
            resp = tix.issue_add(desc)
            issue_id = resp.get("id", "")
            if issue_id:
                result.issues_added.append(issue_id)
        except TixError as e:
            result.errors.append(f"Failed to add issue: {e}")
