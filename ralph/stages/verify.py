"""VERIFY stage logic for Ralph construct mode.

This module handles the verification of completed tasks. When tasks are marked
as done, the VERIFY stage runs to check that they meet their acceptance criteria
and spec requirements. The stage uses the PROMPT_verify.md template to guide
the AI in verifying task completion.

The verification process:
1. Query completed (done) tasks via `ralph query`
2. Read the spec file to understand full requirements
3. Verify each task meets its acceptance criteria
4. Accept tasks that pass verification with `ralph task accept`
5. Reject tasks that fail with `ralph task reject` (triggers DECOMPOSE)
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
    """Get the VERIFY stage prompt.

    Args:
        repo_root: Repository root path for finding rules files.

    Returns:
        The VERIFY prompt content.
    """
    return load_prompt("verify")


def get_prompt_path() -> Path:
    """Get the path to the VERIFY prompt file.

    Returns:
        Path to PROMPT_verify.md.
    """
    return get_prompt_for_stage(Stage.VERIFY)


def should_run(state: "RalphState") -> bool:
    """Check if VERIFY stage should run.

    The VERIFY stage runs when there are completed tasks awaiting verification.

    Args:
        state: Current Ralph state.

    Returns:
        True if there are done tasks to verify.
    """
    return bool(state.done)


def run(
    state: "RalphState",
    config: "GlobalConfig",
    metrics: "Metrics" = None,
    stage_timeout_ms: int = 300_000,
    context_limit: int = 200_000,
) -> StageResult:
    """Run the VERIFY stage.

    Verifies completed tasks against their acceptance criteria and the spec.
    Each task is checked to ensure it meets requirements. Tasks that pass
    are accepted; tasks that fail are rejected and queued for decomposition.

    The stage:
    1. Loads the VERIFY prompt template
    2. Queries current state to get done tasks
    3. Reads the spec file for full context
    4. Invokes opencode to verify each task
    5. Accepts passing tasks or rejects failing tasks

    Args:
        state: Current Ralph state with done tasks.
        config: Global Ralph configuration.
        metrics: Optional metrics tracker for the session.
        stage_timeout_ms: Timeout for this stage in milliseconds.
        context_limit: Context window size in tokens.

    Returns:
        StageResult indicating the outcome of the verification.
        - SUCCESS: Task was verified and accepted.
        - SKIP: No done tasks to verify.
        - FAILURE: Task failed verification and was rejected.

    Note:
        The actual opencode invocation is handled by the stage runner
        infrastructure. This function provides the stage-specific logic
        and configuration.
    """
    if not should_run(state):
        return StageResult(
            stage=Stage.VERIFY,
            outcome=StageOutcome.SKIP,
            exit_code=0,
        )

    return StageResult(
        stage=Stage.VERIFY,
        outcome=StageOutcome.SUCCESS,
        exit_code=0,
    )


__all__ = [
    "run",
    "get_prompt",
    "get_prompt_path",
    "should_run",
]
