from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from ralph.config import GlobalConfig
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
    if not task_date_str:
        return False

    try:
        task_date = datetime.fromisoformat(task_date_str)
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

    # Copy config and spec
    compact_state.config = state.config
    compact_state.spec = state.spec
    compact_state.current_task_id = state.current_task_id

    # Keep active tasks and recent done tasks
    for task in state.tasks:
        # If task is active or not too old
        if (task.status != "DONE") or (
            not is_task_too_old(task.done_at, threshold_date)
        ):
            compact_state.tasks.append(task)

    # Keep issues that might be relevant
    compact_state.issues = state.issues

    # Limit accepted tombstones to recent ones
    compact_state.tombstones["accepted"] = [
        tombstone
        for tombstone in state.tombstones.get("accepted", [])
        if tombstone.tombstone_type == "accept"
        and not is_task_too_old(tombstone.done_at, threshold_date)
    ][-100:]  # Take the last 100 tombstones

    # Copy rejected tombstones if needed
    compact_state.tombstones["rejected"] = state.tombstones.get("rejected", [])

    # Save state if compacted
    if len(compact_state.tasks) < len(state.tasks):
        save_state(compact_state, state_file)
        print(f"Compact completed. Removed tasks older than {threshold_days} days.")
    else:
        print("No tasks to compact.")
