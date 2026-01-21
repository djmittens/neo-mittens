"""VERIFY stage for validating task completion."""

from typing import Optional

from ralph.config import GlobalConfig
from ralph.state import RalphState
from ralph.stages.base import Stage, StageResult, StageOutcome


def run(state: RalphState, config: GlobalConfig) -> StageResult:
    """Placeholder VERIFY stage implementation."""
    done_tasks = [t for t in state.tasks if t.status == "d"]

    # No done tasks to verify
    if not done_tasks:
        return StageResult(stage=Stage.VERIFY, outcome=StageOutcome.SKIP)

    # TODO: Implement actual verify logic
    return StageResult(stage=Stage.VERIFY, outcome=StageOutcome.SUCCESS)
