from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Union

from ralph.config import GlobalConfig
from ralph.models import Task
from ralph.state import load_state, save_state, RalphState


def is_task_too_old(task_date_str: Optional[str], threshold_date: datetime) -> bool:
    """
    Check if a task's timestamp is older than the given threshold.

    Args:
        task_date_str (Optional[str]): Timestamp of the task
        threshold_date (datetime): Cutoff date for old tasks

    Returns:
        bool: True if task is too old, False otherwise
    """
    # No date means task isn't too old
    if not task_date_str:
        return False

    try:
        # Parse the task date
        task_date = datetime.fromisoformat(task_date_str)

        # Normalize to naive datetime for comparison
        # (strip timezone info to avoid aware/naive comparison errors)
        if task_date.tzinfo is not None:
            task_date = task_date.replace(tzinfo=None)

        # Return True if task is older than the threshold
        return task_date < threshold_date
    except (ValueError, TypeError):
        return False


def cmd_compact(config: GlobalConfig, args: Optional[object] = None) -> None:
    """
    Compact plan.jsonl by removing completed tasks older than threshold
    and archiving accepted tombstones.

    Args:
        config (GlobalConfig): Global configuration
        args (Optional[object]): Optional command arguments (reserved for future use)
    """
    # Load the current state from plan.jsonl
    state_file = Path("plan.jsonl")
    state = load_state(state_file)

    # Remove completed tasks older than 30 days
    threshold_days = 30
    now = datetime.now()
    threshold_date = now - timedelta(days=threshold_days)

    # Create a new RalphState to rebuild the state from scratch
    compact_state = RalphState()
    compact_state.config = state.config
    compact_state.spec = state.spec
    compact_state.current_task_id = state.current_task_id

    # Track if state changed
    state_changed = False

    # Rebuild tasks
    for task in state.tasks:
        # Aggressive compaction: filter out old done tasks
        if task.status != "DONE" or (
            task.done_at and not is_task_too_old(task.done_at, threshold_date)
        ):
            compact_state.tasks.append(task)
        else:
            # Mark state as changed if we remove a task
            state_changed = True

    # Keep issues
    compact_state.issues = state.issues

    # Limit accepted tombstones, remove old ones
    compact_tombstones = [
        tombstone
        for tombstone in state.tombstones.get("accepted", [])
        if tombstone.tombstone_type == "accept"
        and (
            not tombstone.done_at
            or not is_task_too_old(tombstone.done_at, threshold_date)
        )
    ][-100:]
    compact_state.tombstones["accepted"] = compact_tombstones

    # Track tombstone changes
    if len(compact_tombstones) < len(state.tombstones.get("accepted", [])):
        state_changed = True

    # Copy rejected tombstones
    compact_state.tombstones["rejected"] = state.tombstones.get("rejected", [])

    # Only save if state actually changed
    if state_changed:
        save_state(compact_state, state_file)
        print(f"Compact completed. Removed tasks older than {threshold_days} days.")
    else:
        print("No tasks to compact.")
