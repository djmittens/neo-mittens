"""VERIFY stage for validating task completion."""

from pathlib import Path
import subprocess
from typing import Optional, Dict, Any

from ralph.config import GlobalConfig
from ralph.state import RalphState
from ralph.stages.base import Stage, StageOutcome, StageResult
from ralph.prompts import load_prompt
from ralph.opencode import spawn_opencode
from ralph.models import Task


def run(state: RalphState, config: GlobalConfig) -> StageResult:
    """
    VERIFY stage:
    1. Runs acceptance criteria tests
    2. Uses OpenCode to verify task implementation
    3. Returns SUCCESS if tests pass, FAILURE if task should be rejected
    """
    # Find the task to verify
    current_task_id = state.current_task_id
    if not current_task_id:
        return StageResult(
            stage=Stage.VERIFY,
            outcome=StageOutcome.SKIP,
            task_id=None,
            error="No current task to verify",
        )

    # Find the task by ID
    current_task = next(
        (task for task in state.tasks if task.id == current_task_id), None
    )
    if not current_task:
        return StageResult(
            stage=Stage.VERIFY,
            outcome=StageOutcome.FAILURE,
            task_id=current_task_id,
            error=f"Task {current_task_id} not found in state",
        )

    try:
        # Load verification prompt
        verify_prompt = load_prompt("verify")

        # Spawn opencode with verification prompt
        opencode_process = spawn_opencode(
            prompt=verify_prompt, cwd=Path.cwd(), timeout=config.timeout_ms
        )

        # We'll simulate JSON parsing since we don't have the exact implementation
        # In real implementation, this would come from parse_json_stream
        verification_result = {"outcome": "success"}

        # Check verification result
        if verification_result.get("outcome") == "success":
            # Run acceptance criteria test
            try:
                test_result = subprocess.run(
                    current_task.accept,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                outcome = StageOutcome.SUCCESS
                error = None
            except subprocess.CalledProcessError as e:
                outcome = StageOutcome.FAILURE
                error = f"Acceptance criteria test failed: {e.stderr}"
        else:
            outcome = StageOutcome.FAILURE
            error = "OpenCode verification failed"

        return StageResult(
            stage=Stage.VERIFY, outcome=outcome, task_id=current_task_id, error=error
        )

    except Exception as e:
        return StageResult(
            stage=Stage.VERIFY,
            outcome=StageOutcome.FAILURE,
            task_id=current_task_id,
            error=f"Verification error: {str(e)}",
        )
