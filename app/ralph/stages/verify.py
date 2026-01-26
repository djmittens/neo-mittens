"""VERIFY stage for validating task completion.

Uses context injection to pre-populate prompts with done tasks list.
"""

from pathlib import Path
import subprocess
from typing import Optional, Tuple, List

from ralph.config import GlobalConfig
from ralph.state import RalphState
from ralph.stages.base import Stage, StageOutcome, StageResult
from ralph.prompts import load_and_inject, build_verify_context
from ralph.opencode import spawn_opencode
from ralph.models import Task


def _get_done_tasks(state: RalphState) -> List[Task]:
    """Get all tasks with status 'd' (done, awaiting verification)."""
    return [t for t in state.tasks if t.status == "d"]


def _load_spec_content(spec_name: str) -> str:
    """Load spec file content, returning empty string if not found."""
    if not spec_name:
        return ""
    spec_path = Path.cwd() / "ralph" / "specs" / spec_name
    if spec_path.exists():
        return spec_path.read_text()
    return ""


def _run_acceptance_test(accept_criteria: str) -> Tuple[StageOutcome, Optional[str]]:
    """Run the acceptance criteria test command."""
    try:
        subprocess.run(
            accept_criteria, shell=True, capture_output=True, text=True, check=True
        )
        return StageOutcome.SUCCESS, None
    except subprocess.CalledProcessError as e:
        return StageOutcome.FAILURE, f"Acceptance criteria test failed: {e.stderr}"


def _build_verify_prompt(state: RalphState) -> str:
    """Build the verify prompt with injected context."""
    done_tasks = _get_done_tasks(state)
    spec_content = _load_spec_content(state.spec or "")
    context = build_verify_context(done_tasks, state.spec or "", spec_content)
    return load_and_inject("verify", context)


def run(state: RalphState, config: GlobalConfig) -> StageResult:
    """VERIFY stage: runs acceptance criteria tests to validate task completion.
    
    Context is pre-injected with:
    - DONE_TASKS_JSON: List of done tasks with their acceptance criteria
    - SPEC_FILE: Current spec name
    - SPEC_CONTENT: Full spec file content
    """
    done_tasks = _get_done_tasks(state)
    if not done_tasks:
        return StageResult(
            stage=Stage.VERIFY,
            outcome=StageOutcome.SKIP,
            task_id=None,
            error="No done tasks to verify",
        )

    try:
        verify_prompt = _build_verify_prompt(state)
        spawn_opencode(prompt=verify_prompt, cwd=Path.cwd(), timeout=config.timeout_ms)

        # Run acceptance tests for all done tasks
        all_passed = True
        errors = []
        for task in done_tasks:
            accept_criteria = task.accept or "echo 'No acceptance criteria'"
            outcome, error = _run_acceptance_test(accept_criteria)
            if outcome == StageOutcome.FAILURE:
                all_passed = False
                errors.append(f"{task.id}: {error}")

        if all_passed:
            return StageResult(
                stage=Stage.VERIFY,
                outcome=StageOutcome.SUCCESS,
                task_id=done_tasks[0].id if done_tasks else None,
            )
        else:
            return StageResult(
                stage=Stage.VERIFY,
                outcome=StageOutcome.FAILURE,
                task_id=done_tasks[0].id if done_tasks else None,
                error="; ".join(errors),
            )

    except Exception as e:
        return StageResult(
            stage=Stage.VERIFY,
            outcome=StageOutcome.FAILURE,
            task_id=done_tasks[0].id if done_tasks else None,
            error=f"Verification error: {str(e)}",
        )
