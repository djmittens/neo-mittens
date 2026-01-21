"""Rejection pattern analysis for detecting recurring task failures."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple

from ralph.models import Issue, Tombstone
from ralph.utils import id_generate


# Threshold for how many times a task must be rejected to trigger an issue
REJECTION_THRESHOLD = 3

# Threshold for how many tasks must share a pattern to trigger an issue
PATTERN_THRESHOLD = 2

# Common error patterns to detect in rejection reasons
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


@dataclass
class RejectionPattern:
    """A detected pattern in task rejections.

    Attributes:
        pattern_type: Type of pattern ('repeated_rejection' or 'common_error').
        keyword: The error keyword detected (for common_error type).
        task_ids: List of task IDs affected by this pattern.
        reasons: List of rejection reasons matching this pattern.
        count: Number of occurrences.
    """

    pattern_type: str
    keyword: str
    task_ids: List[str]
    reasons: List[str]
    count: int


def analyze_rejection_patterns(
    tombstones: List[Tombstone],
) -> List[RejectionPattern]:
    """Detect recurring failure patterns in tombstones.

    Analyzes tombstones to find:
    1. Tasks rejected multiple times (>= REJECTION_THRESHOLD)
    2. Common error patterns affecting multiple tasks (>= PATTERN_THRESHOLD)

    Args:
        tombstones: List of Tombstone objects to analyze.

    Returns:
        List of RejectionPattern objects describing detected patterns.
    """
    if not tombstones:
        return []

    patterns: List[RejectionPattern] = []

    # Track rejections per task
    rejections_by_task: Dict[str, List[str]] = defaultdict(list)
    for tomb in tombstones:
        rejections_by_task[tomb.id].append(tomb.reason)

    # Pattern 1: Tasks rejected multiple times
    for task_id, reasons in rejections_by_task.items():
        if len(reasons) >= REJECTION_THRESHOLD:
            patterns.append(
                RejectionPattern(
                    pattern_type="repeated_rejection",
                    keyword="",
                    task_ids=[task_id],
                    reasons=reasons,
                    count=len(reasons),
                )
            )

    # Track error patterns across tasks
    error_patterns: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for tomb in tombstones:
        reason_lower = tomb.reason.lower()
        for keyword in PATTERN_KEYWORDS:
            if keyword in reason_lower:
                error_patterns[keyword].append((tomb.id, tomb.reason))
                break  # Only match first keyword

    # Pattern 2: Common errors affecting multiple tasks
    for keyword, occurrences in error_patterns.items():
        # Get unique task IDs affected by this pattern
        unique_tasks = list(set(task_id for task_id, _ in occurrences))
        if len(unique_tasks) >= PATTERN_THRESHOLD:
            patterns.append(
                RejectionPattern(
                    pattern_type="common_error",
                    keyword=keyword,
                    task_ids=unique_tasks,
                    reasons=[reason for _, reason in occurrences],
                    count=len(occurrences),
                )
            )

    return patterns


def suggest_issues(
    patterns: List[RejectionPattern],
    spec: str,
    existing_issue_descs: List[str] = None,
) -> List[Issue]:
    """Generate issues from detected rejection patterns.

    Creates high-priority issues for:
    - Tasks that have been rejected repeatedly
    - Common error patterns affecting multiple tasks

    Skips creating issues for patterns that already have matching issues.

    Args:
        patterns: List of RejectionPattern objects from analyze_rejection_patterns.
        spec: Spec file name to associate with created issues.
        existing_issue_descs: List of existing issue descriptions to avoid duplicates.

    Returns:
        List of new Issue objects to add to the plan.
    """
    if not patterns:
        return []

    if existing_issue_descs is None:
        existing_issue_descs = []

    issues: List[Issue] = []
    existing_lower = [desc.lower() for desc in existing_issue_descs]

    for pattern in patterns:
        if pattern.pattern_type == "repeated_rejection":
            # Issue for repeatedly rejected task
            task_id = pattern.task_ids[0]
            desc = (
                f"Task {task_id} rejected {pattern.count} times - "
                f"needs investigation or decomposition"
            )
            if not _desc_exists(desc, existing_lower):
                issues.append(
                    Issue(
                        id=id_generate("i"),
                        desc=desc,
                        spec=spec,
                        priority="high",
                    )
                )

        elif pattern.pattern_type == "common_error":
            # Issue for common error pattern
            task_list = ", ".join(pattern.task_ids[:3])
            if len(pattern.task_ids) > 3:
                task_list += f" (+{len(pattern.task_ids) - 3} more)"
            desc = (
                f"Common '{pattern.keyword}' error affecting "
                f"{len(pattern.task_ids)} tasks: {task_list}"
            )
            if not _desc_exists(desc, existing_lower):
                issues.append(
                    Issue(
                        id=id_generate("i"),
                        desc=desc,
                        spec=spec,
                        priority="high",
                    )
                )

    return issues


def _desc_exists(desc: str, existing_lower: List[str]) -> bool:
    """Check if an issue description already exists.

    Args:
        desc: The new issue description to check.
        existing_lower: List of existing descriptions in lowercase.

    Returns:
        True if a similar issue already exists.
    """
    desc_lower = desc.lower()
    for existing in existing_lower:
        # Check for significant overlap (task ID match or keyword match)
        if desc_lower in existing or existing in desc_lower:
            return True
    return False
