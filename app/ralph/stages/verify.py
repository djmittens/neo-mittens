"""VERIFY stage for validating task completion."""

from pathlib import Path
import subprocess
from typing import Optional, Tuple

from ralph.config import GlobalConfig
from ralph.state import RalphState
from ralph.stages.base import Stage, StageOutcome, StageResult
from ralph.prompts import load_prompt
from ralph.opencode import spawn_opencode
from ralph.models import Task


def _get_current_task(
    state: RalphState,
) -> Tuple[Optional[str], Optional[Task], Optional[StageResult]]:
    """Get the current task for verification.

    Returns (task_id, task, error_result). If error_result is set, return it immediately.
    """
    task_id = state.current_task_id
    if not task_id:
        return (
            None,
            None,
            StageResult(
                stage=Stage.VERIFY,
                outcome=StageOutcome.SKIP,
                task_id=None,
                error="No current task to verify",
            ),
        )
    task = next((t for t in state.tasks if t.id == task_id), None)
    if not task:
        return (
            task_id,
            None,
            StageResult(
                stage=Stage.VERIFY,
                outcome=StageOutcome.FAILURE,
                task_id=task_id,
                error=f"Task {task_id} not found in state",
            ),
        )
    return task_id, task, None


def _run_acceptance_test(accept_criteria: str) -> Tuple[StageOutcome, Optional[str]]:
    """Run the acceptance criteria test command."""
    try:
        subprocess.run(
            accept_criteria, shell=True, capture_output=True, text=True, check=True
        )
        return StageOutcome.SUCCESS, None
    except subprocess.CalledProcessError as e:
        return StageOutcome.FAILURE, f"Acceptance criteria test failed: {e.stderr}"


def run(state: RalphState, config: GlobalConfig) -> StageResult:
    """VERIFY stage: runs acceptance criteria tests to validate task completion."""
    task_id, task, error_result = _get_current_task(state)
    if error_result or task is None or task_id is None:
        return error_result or StageResult(
            stage=Stage.VERIFY,
            outcome=StageOutcome.FAILURE,
            task_id=None,
            error="No task available for verification",
        )

    try:
        verify_prompt = load_prompt("verify")
        spawn_opencode(prompt=verify_prompt, cwd=Path.cwd(), timeout=config.timeout_ms)

        # Run acceptance test (OpenCode verification is simulated for now)
        accept_criteria = task.accept or "echo 'No acceptance criteria'"
        outcome, error = _run_acceptance_test(accept_criteria)
        return StageResult(
            stage=Stage.VERIFY, outcome=outcome, task_id=task_id, error=error
        )

    except Exception as e:
        return StageResult(
            stage=Stage.VERIFY,
            outcome=StageOutcome.FAILURE,
            task_id=task_id,
            error=f"Verification error: {str(e)}",
        )

    except Exception as e:
        return StageResult(
            stage=Stage.VERIFY,
            outcome=StageOutcome.FAILURE,
            task_id=task_id,
            error=f"Verification error: {str(e)}",
        )
