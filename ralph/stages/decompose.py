"""DECOMPOSE stage logic for Ralph construct mode.

This module handles the decomposition of failed tasks. When tasks fail due to
timeout or context limit, the DECOMPOSE stage runs to break them into smaller
subtasks. The stage uses the PROMPT_decompose.md template to guide the AI in
analyzing failures and creating appropriately-sized subtasks.

The decomposition process:
1. Query the failed task via `ralph query` (includes kill_reason, kill_log)
2. Review the kill log (head/tail only - NEVER read entire file)
3. Analyze what was attempted and where it got stuck
4. Create 2-5 smaller subtasks with `parent` linking to original
5. Delete the original oversized task
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
    """Get the DECOMPOSE stage prompt.

    Args:
        repo_root: Repository root path for finding rules files.

    Returns:
        The DECOMPOSE prompt content.
    """
    return load_prompt("decompose")


def get_prompt_path() -> Path:
    """Get the path to the DECOMPOSE prompt file.

    Returns:
        Path to PROMPT_decompose.md.
    """
    return get_prompt_for_stage(Stage.DECOMPOSE)


def should_run(state: "RalphState") -> bool:
    """Check if DECOMPOSE stage should run.

    The DECOMPOSE stage runs when there's a pending task with needs_decompose=True.
    This indicates a task that previously failed due to timeout or context limit
    and needs to be broken down into smaller subtasks.

    Args:
        state: Current Ralph state.

    Returns:
        True if there is a task that needs decomposition.
    """
    return state.get_task_needing_decompose() is not None


def run(
    state: "RalphState",
    config: "GlobalConfig",
    metrics: "Metrics" = None,
    stage_timeout_ms: int = 300_000,
    context_limit: int = 200_000,
) -> StageResult:
    """Run the DECOMPOSE stage.

    Breaks down failed tasks into smaller subtasks. Each failed task is analyzed
    to understand why it failed (timeout, context explosion) and what smaller
    pieces of work can accomplish the same goal. The original task is deleted
    and replaced with 2-5 subtasks linked via the `parent` field.

    The stage:
    1. Loads the DECOMPOSE prompt template
    2. Queries current state to get task needing decomposition
    3. Invokes opencode (with extended read permissions) to analyze failure
    4. Reviews kill log safely (head/tail only - log caused context explosion)
    5. Creates subtasks linked to original via `parent` field
    6. Deletes the original oversized task

    Args:
        state: Current Ralph state with task needing decomposition.
        config: Global Ralph configuration.
        metrics: Optional metrics tracker for the session.
        stage_timeout_ms: Timeout for this stage in milliseconds.
        context_limit: Context window size in tokens.

    Returns:
        StageResult indicating the outcome of the decomposition.
        - SUCCESS: Task was decomposed into subtasks.
        - SKIP: No tasks need decomposition.
        - FAILURE: Decomposition failed.

    Note:
        The DECOMPOSE stage has special permissions allowing read access
        to all files (needed to review kill logs). The actual opencode
        invocation is handled by the stage runner infrastructure.
    """
    if not should_run(state):
        return StageResult(
            stage=Stage.DECOMPOSE,
            outcome=StageOutcome.SKIP,
            exit_code=0,
        )

    task = state.get_task_needing_decompose()
    task_id = task.id if task else None

    return StageResult(
        stage=Stage.DECOMPOSE,
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
