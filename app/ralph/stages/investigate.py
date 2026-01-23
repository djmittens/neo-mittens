"""INVESTIGATE stage for creating tasks from issues."""

from pathlib import Path
from typing import List

from ralph.config import GlobalConfig
from ralph.state import RalphState
from ralph.models import Task, Issue
from ralph.stages.base import Stage, StageResult, StageOutcome
from ralph.prompts import load_prompt
from ralph.opencode import spawn_opencode, parse_json_stream, extract_metrics
from ralph.utils import gen_id


def _build_investigate_prompt(state: RalphState) -> str:
    """Build the full prompt for investigation stage.

    Args:
        state: Current Ralph state with issues and spec context

    Returns:
        Formatted prompt string with spec and issues
    """
    prompt = load_prompt("investigate")
    spec_contents = (
        Path(f"app/ralph/specs/{state.spec}").read_text() if state.spec else ""
    )
    issue_lines = [
        f"ID: {issue.id}\nDescription: {issue.desc}\nPriority: {issue.priority or 'unset'}"
        for issue in state.issues
    ]
    return prompt.format(spec=spec_contents, issues="\n\n".join(issue_lines))


def _parse_task_from_json(json_obj: dict, state: RalphState) -> Task | None:
    """Parse a single task from JSON object.

    Args:
        json_obj: JSON object with task data
        state: Current Ralph state for defaults

    Returns:
        Task object or None if invalid
    """
    if not all(k in json_obj for k in ["name", "notes"]):
        return None

    default_priority = state.issues[0].priority if state.issues else None
    return Task(
        id=gen_id(),
        name=json_obj["name"],
        spec=state.spec or "",
        notes=json_obj.get("notes"),
        accept=json_obj.get("accept"),
        created_from=json_obj.get("issue_id"),
        priority=json_obj.get("priority") or default_priority,
    )


def _process_opencode_output(stdout_content: str, state: RalphState) -> List[Task]:
    """Process opencode output and extract tasks.

    Args:
        stdout_content: Raw stdout content from opencode
        state: Current Ralph state for defaults

    Returns:
        List of parsed Task objects
    """
    tasks = []
    for json_obj in parse_json_stream(stdout_content):
        task = _parse_task_from_json(json_obj, state)
        if task:
            tasks.append(task)
    return tasks


def run(state: RalphState, config: GlobalConfig) -> StageResult:
    """Run the INVESTIGATE stage.

    Transforms issues into concrete tasks for the BUILD stage.

    Args:
        state: Current Ralph state with issues and spec context
        config: Global configuration for the run

    Returns:
        StageResult indicating outcome of the investigation stage
    """
    if not state.issues:
        return StageResult(stage=Stage.INVESTIGATE, outcome=StageOutcome.SKIP)

    full_prompt = _build_investigate_prompt(state)
    opencode_proc = spawn_opencode(
        full_prompt, cwd=Path.cwd(), timeout=config.stage_timeout_ms // 1000
    )

    if opencode_proc.stdout is None:
        return StageResult(
            stage=Stage.INVESTIGATE,
            outcome=StageOutcome.FAILURE,
            error="OpenCode process has no stdout",
        )

    stdout_content = opencode_proc.stdout.read()
    if isinstance(stdout_content, bytes):
        stdout_content = stdout_content.decode("utf-8")

    new_tasks = _process_opencode_output(stdout_content, state)
    opencode_proc.wait()

    if not new_tasks:
        return StageResult(
            stage=Stage.INVESTIGATE,
            outcome=StageOutcome.FAILURE,
            error="No tasks generated from issues",
        )

    state.tasks.extend(new_tasks)
    metrics = extract_metrics(stdout_content)

    return StageResult(
        stage=Stage.INVESTIGATE,
        outcome=StageOutcome.SUCCESS,
        tokens_used=metrics.total_tokens_out,
        cost=metrics.total_cost,
    )
