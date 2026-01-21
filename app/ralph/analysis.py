"""Rejection pattern analysis for detecting recurring failure patterns."""

from collections import defaultdict
from typing import TYPE_CHECKING

from ralph.models import Issue, Tombstone
from ralph.utils import gen_id

if TYPE_CHECKING:
    from ralph.state import RalphState

PATTERN_KEYWORDS = [
    "argument count",
    "not found",
    "grep returns 0",
    "expected 1",
    "expected 0",
    "times out",
    "timeout",
    "still contains",
    "not implemented",
    "missing",
]

REJECTION_THRESHOLD = 3
PATTERN_THRESHOLD = 2


def analyze_rejection_patterns(tombstones: list[Tombstone]) -> dict:
    """Detect recurring failure patterns in rejected tasks.

    Args:
        tombstones: List of tombstone records (rejected tasks).

    Returns:
        Dictionary with:
            - rejections_by_task: dict mapping task_id to list of reasons
            - error_patterns: dict mapping keyword to list of (task_id, reason)
            - repeated_tasks: list of task_ids rejected >= REJECTION_THRESHOLD times
            - common_patterns: list of patterns affecting >= PATTERN_THRESHOLD tasks
    """
    rejections_by_task: dict[str, list[str]] = defaultdict(list)
    for tomb in tombstones:
        if tomb.tombstone_type == "reject":
            rejections_by_task[tomb.id].append(tomb.reason)

    error_patterns: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for tomb in tombstones:
        if tomb.tombstone_type != "reject":
            continue
        reason_lower = tomb.reason.lower()
        for keyword in PATTERN_KEYWORDS:
            if keyword in reason_lower:
                error_patterns[keyword].append((tomb.id, tomb.reason))
                break

    repeated_tasks = [
        task_id
        for task_id, reasons in rejections_by_task.items()
        if len(reasons) >= REJECTION_THRESHOLD
    ]

    common_patterns = [
        pattern
        for pattern, occurrences in error_patterns.items()
        if len(set(task_id for task_id, _ in occurrences)) >= PATTERN_THRESHOLD
    ]

    return {
        "rejections_by_task": dict(rejections_by_task),
        "error_patterns": dict(error_patterns),
        "repeated_tasks": repeated_tasks,
        "common_patterns": common_patterns,
    }


def suggest_issues(
    patterns: dict,
    tasks: list | None = None,
    existing_issues: list[Issue] | None = None,
    spec: str = "",
) -> list[Issue]:
    """Generate issue suggestions from detected patterns.

    Args:
        patterns: Dictionary from analyze_rejection_patterns.
        tasks: Optional list of Task objects for name lookup.
        existing_issues: Optional list of existing issues to avoid duplicates.
        spec: Spec file path for issue association.

    Returns:
        List of suggested Issue objects.
    """
    new_issues: list[Issue] = []
    existing_descs = {i.desc.lower() for i in (existing_issues or [])}

    rejections_by_task = patterns.get("rejections_by_task", {})
    error_patterns = patterns.get("error_patterns", {})

    for task_id in patterns.get("repeated_tasks", []):
        reasons = rejections_by_task.get(task_id, [])
        task_name = _find_task_name(task_id, tasks)

        issue_key = f"repeated rejection: {task_id}"
        if issue_key in existing_descs:
            continue

        unique_reasons = list(set(reasons))[:3]
        reason_summary = "; ".join(r[:100] for r in unique_reasons)

        issue_desc = (
            f"REPEATED REJECTION ({len(reasons)}x): Task '{task_name}' ({task_id}) "
            f"keeps failing with: {reason_summary}. "
            f"Investigate root cause - may need prerequisite task or spec clarification."
        )

        new_issues.append(
            Issue(id=gen_id("i"), desc=issue_desc, spec=spec, priority="high")
        )

    for pattern in patterns.get("common_patterns", []):
        occurrences = error_patterns.get(pattern, [])
        unique_task_ids = list(set(task_id for task_id, _ in occurrences))

        pattern_key = f"common failure pattern: {pattern}"
        if pattern_key in existing_descs:
            continue

        task_names = [_find_task_name(tid, tasks)[:30] for tid in unique_task_ids[:3]]
        sample_reason = occurrences[0][1][:150] if occurrences else ""

        issue_desc = (
            f"COMMON FAILURE PATTERN: {len(unique_task_ids)} tasks fail with '{pattern}'. "
            f"Affected: {', '.join(task_names)}. "
            f"Sample: {sample_reason}. "
            f"Likely missing prerequisite - create blocking task."
        )

        new_issues.append(
            Issue(id=gen_id("i"), desc=issue_desc, spec=spec, priority="high")
        )

    return new_issues


def _find_task_name(task_id: str, tasks: list | None) -> str:
    """Look up task name by ID, returning ID if not found."""
    if not tasks:
        return task_id
    for task in tasks:
        if task.id == task_id:
            return task.name
    return task_id
