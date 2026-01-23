"""Ralph query command.

Query current state as JSON.
"""

import json
from typing import Optional

from ralph.state import load_state
from ralph.utils import Colors

__all__ = ["cmd_query"]


def cmd_query(
    config: dict, subcommand: Optional[str] = None, done_only: bool = False
) -> int:
    """Query current state as JSON.

    Args:
        config: Ralph configuration dict.
        subcommand: Optional subquery (stage, tasks, issues, iteration, etc.)
        done_only: If True, only show done tasks.

    Returns:
        Exit code (0 for success).
    """
    plan_file = config["plan_file"]
    state = load_state(plan_file)

    if subcommand == "stage":
        print(state.get_stage())
        return 0

    if subcommand == "tasks":
        tasks = state.done if done_only else state.pending
        print(json.dumps([t.to_dict() for t in tasks], indent=2))
        return 0

    if subcommand == "issues":
        print(json.dumps([i.to_dict() for i in state.issues], indent=2))
        return 0

    if subcommand == "iteration":
        print("0")
        return 0

    result = state.to_dict()
    if state.tasks:
        next_task = state.get_next_task()
        if next_task:
            result["current_task"] = next_task.id
    print(json.dumps(result, indent=2))
    return 0
