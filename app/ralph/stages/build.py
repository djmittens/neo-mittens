"""BUILD stage for implementing tasks."""

from typing import Optional

from ralph.config import GlobalConfig
from ralph.state import RalphState
from ralph.stages.base import Stage, StageResult, StageOutcome


def run(state: RalphState, config: GlobalConfig) -> StageResult:
    """Placeholder BUILD stage implementation."""
    pending_tasks = [t for t in state.tasks if t.status == "p"]

    # No pending tasks
    if not pending_tasks:
        return StageResult(stage=Stage.BUILD, outcome=StageOutcome.SKIP)

    # TODO: Implement actual build logic
    return StageResult(stage=Stage.BUILD, outcome=StageOutcome.SUCCESS)
