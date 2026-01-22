"""Rejection pattern analysis for detecting recurring failure patterns."""

from collections import defaultdict
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
    Set,
    Mapping,
    cast,
)

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


def _collect_rejections_by_task(
    tombstones: List[Tombstone],
) -> Dict[str, List[str]]:
    """Group rejection reasons by task ID."""
    rejections: Dict[str, List[str]] = defaultdict(list)
    for tomb in tombstones:
        if tomb.tombstone_type == "reject":
            rejections[tomb.id].append(tomb.reason)
    return dict(rejections)


def _match_error_pattern(reason: str) -> Optional[str]:
    """Find matching keyword pattern in rejection reason."""
    reason_lower = reason.lower()
    for keyword in PATTERN_KEYWORDS:
        if keyword in reason_lower:
            return keyword
    return None


def _collect_error_patterns(
    tombstones: List[Tombstone],
) -> Dict[str, List[Tuple[str, str]]]:
    """Collect error patterns from rejected tombstones."""
    patterns: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for tomb in tombstones:
        if tomb.tombstone_type != "reject":
            continue
        matched = _match_error_pattern(tomb.reason)
        if matched:
            patterns[matched].append((tomb.id, tomb.reason))
    return dict(patterns)


def analyze_rejection_patterns(
    tombstones: List[Tombstone],
) -> Dict[str, Any]:
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
    rejections_by_task = _collect_rejections_by_task(tombstones)
    error_patterns = _collect_error_patterns(tombstones)

    repeated_tasks = [
        tid
        for tid, reasons in rejections_by_task.items()
        if len(reasons) >= REJECTION_THRESHOLD
    ]
    common_patterns = [
        pattern
        for pattern, occs in error_patterns.items()
        if len({tid for tid, _ in occs}) >= PATTERN_THRESHOLD
    ]

    return {
        "rejections_by_task": rejections_by_task,
        "error_patterns": error_patterns,
        "repeated_tasks": repeated_tasks,
        "common_patterns": common_patterns,
    }


def _build_repeated_task_issue(
    task_id: str,
    reasons: List[str],
    tasks: Optional[List],
    spec: str,
) -> Issue:
    """Build an issue for a repeatedly rejected task."""
    task_name = _find_task_name(task_id, tasks)
    unique_reasons = list(set(reasons))[:3]
    reason_summary = "; ".join(r[:100] for r in unique_reasons)
    desc = (
        f"REPEATED REJECTION ({len(reasons)}x): Task '{task_name}' ({task_id}) "
        f"keeps failing with: {reason_summary}. "
        f"Investigate root cause - may need prerequisite task or spec clarification."
    )
    return Issue(id=gen_id("i"), desc=desc, spec=spec, priority="high")


def _build_pattern_issue(
    pattern: str,
    occurrences: List[Tuple[str, str]],
    tasks: Optional[List],
    spec: str,
) -> Issue:
    """Build an issue for a common failure pattern."""
    unique_task_ids = list({tid for tid, _ in occurrences})
    task_names = [_find_task_name(tid, tasks)[:30] for tid in unique_task_ids[:3]]
    sample_reason = occurrences[0][1][:150] if occurrences else ""
    desc = (
        f"COMMON FAILURE PATTERN: {len(unique_task_ids)} tasks fail with '{pattern}'. "
        f"Affected: {', '.join(task_names)}. "
        f"Sample: {sample_reason}. "
        f"Likely missing prerequisite - create blocking task."
    )
    return Issue(id=gen_id("i"), desc=desc, spec=spec, priority="high")


def _collect_repeated_task_issues(
    patterns: Dict[str, Any],
    existing_descs: Set[str],
    tasks: Optional[List],
    spec: str,
) -> List[Issue]:
    """Generate issues for repeated task rejections."""
    rejections = patterns.get("rejections_by_task") or {}
    issues: List[Issue] = []
    for task_id in patterns.get("repeated_tasks") or []:
        if f"repeated rejection: {task_id}" not in existing_descs:
            issues.append(
                _build_repeated_task_issue(
                    task_id, rejections.get(task_id, []), tasks, spec
                )
            )
    return issues


def _collect_pattern_issues(
    patterns: Dict[str, Any],
    existing_descs: Set[str],
    tasks: Optional[List],
    spec: str,
) -> List[Issue]:
    """Generate issues for common failure patterns."""
    error_map = patterns.get("error_patterns") or {}
    issues: List[Issue] = []
    for pattern in patterns.get("common_patterns") or []:
        if f"common failure pattern: {pattern}" not in existing_descs:
            issues.append(
                _build_pattern_issue(pattern, error_map.get(pattern, []), tasks, spec)
            )
    return issues


def suggest_issues(
    patterns: Dict[str, Any],
    tasks: Optional[List] = None,
    existing_issues: Optional[List[Issue]] = None,
    spec: str = "",
) -> List[Issue]:
    """Generate issue suggestions from detected patterns.

    Args:
        patterns: Dictionary from analyze_rejection_patterns.
        tasks: Optional list of Task objects for name lookup.
        existing_issues: Optional list of existing issues to avoid duplicates.
        spec: Spec file path for issue association.

    Returns:
        List of suggested Issue objects.
    """
    existing_descs: Set[str] = {i.desc.lower() for i in (existing_issues or [])}
    return _collect_repeated_task_issues(
        patterns, existing_descs, tasks, spec
    ) + _collect_pattern_issues(patterns, existing_descs, tasks, spec)


def _find_task_name(task_id: str, tasks: Optional[List] = None) -> str:
    """Look up task name by ID, returning ID if not found.

    Args:
        task_id: Unique identifier of the task.
        tasks: Optional list of task objects to search.

    Returns:
        Task name if found, otherwise the original task_id.
    """
    if not tasks:
        return task_id

    for task in tasks:
        if getattr(task, "id", None) == task_id:
            return getattr(task, "name", task_id)

    return task_id
