"""INVESTIGATE stage logic for Ralph construct mode.

This module handles the investigation of issues. When issues exist in the plan,
the INVESTIGATE stage runs to analyze each issue and convert it into actionable
tasks. The stage uses the PROMPT_investigate.md template to guide the AI in
investigating issues and creating tasks from them.

The investigation process:
1. Query all pending issues via `ralph query`
2. Investigate each issue (potentially in parallel via subagents)
3. Create tasks with `created_from` field linking to the source issue
4. Clear investigated issues with `ralph issue done` or `ralph issue done-all`
"""

from pathlib import Path
from typing import TYPE_CHECKING

from ralph.prompts import get_prompt_for_stage, load_prompt
from ralph.stages.base import Stage, StageOutcome, StageResult

if TYPE_CHECKING:
    from ralph.config import GlobalConfig
    from ralph.context import Metrics
    from ralph.state import RalphState


def get_prompt(repo_root: Path) -> str:
    """Get the INVESTIGATE stage prompt.

    Args:
        repo_root: Repository root path for finding rules files.

    Returns:
        The INVESTIGATE prompt content.
    """
    return load_prompt("investigate")


def get_prompt_path() -> Path:
    """Get the path to the INVESTIGATE prompt file.

    Returns:
        Path to PROMPT_investigate.md.
    """
    return get_prompt_for_stage(Stage.INVESTIGATE)


def should_run(state: "RalphState") -> bool:
    """Check if INVESTIGATE stage should run.

    The INVESTIGATE stage runs when there are issues pending investigation.

    Args:
        state: Current Ralph state.

    Returns:
        True if there are issues to investigate.
    """
    return bool(state.issues)


def run(
    state: "RalphState",
    config: "GlobalConfig",
    metrics: "Metrics" = None,
    stage_timeout_ms: int = 300_000,
    context_limit: int = 200_000,
) -> StageResult:
    """Run the INVESTIGATE stage.

    Investigates all pending issues and converts them into actionable tasks.
    Each issue is analyzed to understand the problem and create appropriate
    tasks to address it.

    The stage:
    1. Loads the INVESTIGATE prompt template
    2. Queries current state to get pending issues
    3. Invokes opencode to investigate issues
    4. Creates tasks linked to source issues via `created_from` field
    5. Clears investigated issues

    Args:
        state: Current Ralph state with pending issues.
        config: Global Ralph configuration.
        metrics: Optional metrics tracker for the session.
        stage_timeout_ms: Timeout for this stage in milliseconds.
        context_limit: Context window size in tokens.

    Returns:
        StageResult indicating the outcome of the investigation.

    Note:
        The actual opencode invocation is handled by the stage runner
        infrastructure. This function provides the stage-specific logic
        and configuration.
    """
    if not should_run(state):
        return StageResult(
            stage=Stage.INVESTIGATE,
            outcome=StageOutcome.SKIP,
            exit_code=0,
        )

    return StageResult(
        stage=Stage.INVESTIGATE,
        outcome=StageOutcome.SUCCESS,
        exit_code=0,
    )


__all__ = [
    "run",
    "get_prompt",
    "get_prompt_path",
    "should_run",
]
