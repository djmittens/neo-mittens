"""DECOMPOSE stage for breaking down complex tasks."""

from typing import Optional

from ralph.config import GlobalConfig
from ralph.state import RalphState
from ralph.stages.base import Stage, StageResult, StageOutcome


def run(state: RalphState, config: GlobalConfig) -> StageResult:
    """Placeholder DECOMPOSE stage implementation."""
    killed_tasks = [t for t in state.tasks if getattr(t, "kill_reason", None)]

    # No killed tasks to decompose
    if not killed_tasks:
        return StageResult(stage=Stage.DECOMPOSE, outcome=StageOutcome.SKIP)

    # TODO: Implement actual decompose logic
    return StageResult(
        stage=Stage.DECOMPOSE,
        outcome=StageOutcome.SUCCESS,
        task_id=killed_tasks[0].id,
        kill_reason=killed_tasks[0].kill_reason,
        kill_log=killed_tasks[0].kill_log,
    )
