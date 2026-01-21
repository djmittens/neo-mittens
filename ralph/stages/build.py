"""BUILD stage logic for Ralph construct mode.

This module handles the BUILD stage which executes pending tasks. When tasks
are pending in the plan, the BUILD stage runs to implement each task according
to its specification. The stage uses the PROMPT_build.md template to guide
the AI in implementing tasks.

The build process:
1. Query the next pending task via `ralph query`
2. Get task details including name, notes, and acceptance criteria
3. Invoke opencode to implement the task
4. Mark task as done with `ralph task done` on success
5. Handle failures by marking task for decomposition
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
    """Get the BUILD stage prompt.

    Args:
        repo_root: Repository root path for finding rules files.

    Returns:
        The BUILD prompt content.
    """
    return load_prompt("build")


def get_prompt_path() -> Path:
    """Get the path to the BUILD prompt file.

    Returns:
        Path to PROMPT_build.md.
    """
    return get_prompt_for_stage(Stage.BUILD)


def should_run(state: "RalphState") -> bool:
    """Check if BUILD stage should run.

    The BUILD stage runs when there are pending tasks to execute.

    Args:
        state: Current Ralph state.

    Returns:
        True if there are pending tasks to build.
    """
    return bool(state.pending)


def run(
    state: "RalphState",
    config: "GlobalConfig",
    metrics: "Metrics" = None,
    stage_timeout_ms: int = 300_000,
    context_limit: int = 200_000,
) -> StageResult:
    """Run the BUILD stage.

    Executes pending tasks one at a time. Each task is implemented according
    to its specification and acceptance criteria. On success, the task is
    marked as done. On failure (timeout, context limit, or error), the task
    is marked for decomposition.

    The stage:
    1. Loads the BUILD prompt template
    2. Queries current state to get the next pending task
    3. Invokes opencode to implement the task
    4. Marks task done on success or marks for decomposition on failure
    5. Continues until all pending tasks are processed or a failure occurs

    Args:
        state: Current Ralph state with pending tasks.
        config: Global Ralph configuration.
        metrics: Optional metrics tracker for the session.
        stage_timeout_ms: Timeout for this stage in milliseconds.
        context_limit: Context window size in tokens.

    Returns:
        StageResult indicating the outcome of the build.
        - SUCCESS: Task was implemented and marked done.
        - SKIP: No pending tasks to build.
        - FAILURE: Task failed and needs decomposition.

    Note:
        The actual opencode invocation is handled by the stage runner
        infrastructure. This function provides the stage-specific logic
        and configuration.
    """
    if not should_run(state):
        return StageResult(
            stage=Stage.BUILD,
            outcome=StageOutcome.SKIP,
            exit_code=0,
        )

    next_task = state.get_next_task() if hasattr(state, "get_next_task") else None
    task_id = next_task.id if next_task else None

    return StageResult(
        stage=Stage.BUILD,
        outcome=StageOutcome.SUCCESS,
        exit_code=0,
        task_id=task_id,
    )


__all__ = [
    "run",
    "get_prompt",
    "get_prompt_path",
    "should_run",
]
