"""BUILD stage for implementing tasks.

Run function refactored to under 50 lines with extracted helpers.
Uses context injection to pre-populate prompts with task data.
"""

import sys
from pathlib import Path
from typing import Optional, Tuple, List

project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ralph.config import GlobalConfig
from ralph.context import Metrics
from ralph.models import Task
from ralph.opencode import spawn_opencode, parse_json_stream, extract_metrics
from ralph.prompts import load_and_inject, build_build_context
from ralph.stages.base import Stage, StageOutcome, StageResult
from ralph.state import RalphState
from ralph.utils import gen_id


def _get_current_task(
    state: RalphState,
) -> Tuple[Optional[Task], Optional[StageResult]]:
    """Get the current task from state, returning error result if not found."""
    if not state.current_task_id:
        return None, StageResult(
            stage=Stage.BUILD,
            outcome=StageOutcome.SKIP,
            task_id=None,
            error="No current task to build",
        )
    current_task = next(
        (task for task in state.tasks if task.id == state.current_task_id), None
    )
    if not current_task:
        return None, StageResult(
            stage=Stage.BUILD,
            outcome=StageOutcome.FAILURE,
            task_id=state.current_task_id,
            error="Current task not found in task list",
        )
    return current_task, None


def _load_spec_content(spec_name: str) -> str:
    """Load spec file content, returning empty string if not found."""
    if not spec_name:
        return ""
    spec_path = Path.cwd() / "ralph" / "specs" / spec_name
    if spec_path.exists():
        return spec_path.read_text()
    return ""


def _build_prompt(task: Task) -> Tuple[Optional[str], Optional[str]]:
    """Build the full prompt for the BUILD stage with injected context."""
    try:
        spec_content = _load_spec_content(task.spec)
        context = build_build_context(task, spec_content)
        prompt = load_and_inject("build", context)
        return prompt, None
    except Exception as e:
        return None, f"Failed to load build prompt: {str(e)}"


def _spawn_and_parse(
    prompt: str, config: GlobalConfig, task_id: str
) -> Tuple[Optional[List[dict]], Optional[Metrics], Optional[StageResult]]:
    """Spawn opencode and parse the output."""
    try:
        process = spawn_opencode(prompt, cwd=Path.cwd(), timeout=config.timeout_ms)
        if process.stdout is None:
            return (
                None,
                None,
                StageResult(
                    stage=Stage.BUILD,
                    outcome=StageOutcome.FAILURE,
                    task_id=task_id,
                    error="OpenCode process has no stdout",
                ),
            )
        output_str = process.stdout.read().decode("utf-8")
        output_list = list(parse_json_stream(output_str))
        metrics = Metrics()
        try:
            metrics = extract_metrics(output_str)
        except Exception:
            pass
        return output_list, metrics, None
    except Exception as e:
        return (
            None,
            None,
            StageResult(
                stage=Stage.BUILD,
                outcome=StageOutcome.FAILURE,
                task_id=task_id,
                error=f"OpenCode process failed: {str(e)}",
            ),
        )


def _process_output(
    output_list: List[dict], current_task: Task, state: RalphState
) -> Optional[str]:
    """Process output items and add new tasks to state."""
    try:
        for output_item in output_list:
            if isinstance(output_item, dict) and output_item.get("name"):
                new_task = Task(
                    id=output_item.get("id", f"t-{gen_id()}"),
                    name=output_item["name"],
                    spec=current_task.spec,
                    notes=output_item.get("notes", ""),
                    accept=output_item.get("accept", ""),
                    parent=current_task.id,
                    created_from=current_task.id,
                    priority=current_task.priority,
                )
                state.tasks.append(new_task)
        return None
    except Exception as e:
        return f"Failed to process task outputs: {str(e)}"


def _make_failure(task_id: Optional[str], error: str) -> StageResult:
    """Create a failure StageResult."""
    return StageResult(
        stage=Stage.BUILD,
        outcome=StageOutcome.FAILURE,
        task_id=task_id,
        error=error,
    )


def _make_success(task_id: str, metrics: Optional[Metrics]) -> StageResult:
    """Create a success StageResult."""
    return StageResult(
        stage=Stage.BUILD,
        outcome=StageOutcome.SUCCESS,
        task_id=task_id,
        tokens_used=metrics.tokens_used if metrics else 0,
        cost=metrics.total_cost if metrics else 0.0,
    )


def _execute_build(
    current_task: Task, config: GlobalConfig, state: RalphState
) -> StageResult:
    """Execute the build process for a task."""
    full_prompt, prompt_error = _build_prompt(current_task)
    if prompt_error or full_prompt is None:
        return _make_failure(current_task.id, prompt_error or "Failed to build prompt")

    output_list, metrics, spawn_error = _spawn_and_parse(
        full_prompt, config, current_task.id
    )
    if spawn_error:
        return spawn_error

    if not output_list:
        return _make_failure(current_task.id, "No output generated by OpenCode")

    process_error = _process_output(output_list, current_task, state)
    if process_error:
        return _make_failure(current_task.id, process_error)

    return _make_success(current_task.id, metrics)


def run(state: RalphState, config: GlobalConfig) -> StageResult:
    """Run the BUILD stage for the current task."""
    current_task, error_result = _get_current_task(state)
    if error_result:
        return error_result
    if current_task is None:
        return StageResult(
            stage=Stage.BUILD,
            outcome=StageOutcome.SKIP,
            task_id=None,
            error="No current task",
        )
    return _execute_build(current_task, config, state)
