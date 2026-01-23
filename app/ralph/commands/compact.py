from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple

from ralph.config import GlobalConfig
from ralph.models import Task, Tombstone
from ralph.state import load_state, save_state, RalphState


def is_task_too_old(task_date_str: Optional[str], threshold_date: datetime) -> bool:
    """Check if a task's timestamp is older than the given threshold."""
    if not task_date_str:
        return False

    try:
        task_date = datetime.fromisoformat(task_date_str)
        if task_date.tzinfo is not None:
            task_date = task_date.replace(tzinfo=None)
        return task_date < threshold_date
    except (ValueError, TypeError):
        return False


def _filter_old_tasks(
    tasks: List[Task], threshold_date: datetime
) -> Tuple[List[Task], bool]:
    """Filter out old done tasks, return (kept_tasks, had_removals)."""
    kept = []
    removed_any = False
    for task in tasks:
        is_done = task.status == "DONE"
        is_old = is_task_too_old(task.done_at, threshold_date)
        if is_done and is_old:
            removed_any = True
        else:
            kept.append(task)
    return kept, removed_any


def _filter_old_tombstones(
    tombstones: List[Tombstone], threshold_date: datetime, limit: int = 100
) -> Tuple[List[Tombstone], bool]:
    """Filter old accepted tombstones and limit count, return (kept, had_removals)."""
    original_count = len(tombstones)
    kept = [
        t
        for t in tombstones
        if t.tombstone_type == "accept"
        and not is_task_too_old(t.done_at, threshold_date)
    ][-limit:]
    return kept, len(kept) < original_count


def _report_compaction(removed: bool, threshold_days: int) -> None:
    """Print compaction result message."""
    if removed:
        print(f"Compact completed. Removed tasks older than {threshold_days} days.")
    else:
        print("No tasks to compact.")


def cmd_compact(config: GlobalConfig, args: Optional[object] = None) -> None:
    """Compact plan.jsonl by removing old completed tasks and tombstones."""
    state_file = Path("plan.jsonl")
    state = load_state(state_file)

    threshold_days = 30
    threshold_date = datetime.now() - timedelta(days=threshold_days)

    # Filter tasks and tombstones
    kept_tasks, tasks_removed = _filter_old_tasks(state.tasks, threshold_date)
    kept_tombstones, tombstones_removed = _filter_old_tombstones(
        state.tombstones.get("accepted", []), threshold_date
    )

    state_changed = tasks_removed or tombstones_removed

    if state_changed:
        compact_state = RalphState()
        compact_state.config = state.config
        compact_state.spec = state.spec
        compact_state.current_task_id = state.current_task_id
        compact_state.tasks = kept_tasks
        compact_state.issues = state.issues
        compact_state.tombstones["accepted"] = kept_tombstones
        compact_state.tombstones["rejected"] = state.tombstones.get("rejected", [])
        save_state(compact_state, state_file)

    _report_compaction(state_changed, threshold_days)
