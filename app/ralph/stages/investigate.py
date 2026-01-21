"""INVESTIGATE stage for creating tasks from issues."""

from pathlib import Path
from typing import Optional

from ralph.config import GlobalConfig
from ralph.state import RalphState
from ralph.models import Task, Issue
from ralph.stages.base import Stage, StageResult, StageOutcome
from ralph.prompts import load_prompt
from ralph.opencode import spawn_opencode, parse_json_stream, extract_metrics
from ralph.utils import gen_id


def run(state: RalphState, config: GlobalConfig) -> StageResult:
    """Run the INVESTIGATE stage.

    Transforms issues into concrete tasks for the BUILD stage.

    Args:
        state: Current Ralph state with issues and spec context
        config: Global configuration for the run

    Returns:
        StageResult indicating outcome of the investigation stage
    """
    # If no issues to investigate, return SKIP
    if not state.issues:
        return StageResult(stage=Stage.INVESTIGATE, outcome=StageOutcome.SKIP)

    # Load investigation prompt
    prompt = load_prompt("investigate")

    # Prepare context: spec and issues
    spec_contents = (
        Path(f"app/ralph/specs/{state.spec}").read_text() if state.spec else ""
    )
    issue_lines = [
        f"ID: {issue.id}\nDescription: {issue.desc}\nPriority: {issue.priority or 'unset'}"
        for issue in state.issues
    ]

    # Construct full prompt with spec and issues
    full_prompt = prompt.format(spec=spec_contents, issues="\n\n".join(issue_lines))

    # Spawn opencode to generate tasks
    opencode_proc = spawn_opencode(
        full_prompt, cwd=Path.cwd(), timeout=config.stage_timeout_ms // 1000
    )

    # Capture and parse output
    output_text = ""
    new_tasks = []
    for json_obj in parse_json_stream(opencode_proc.stdout):
        # Validate task JSON
        if not all(k in json_obj for k in ["name", "notes"]):
            continue

        # Create Task with generated details
        task = Task(
            id=gen_id(),
            name=json_obj["name"],
            spec=state.spec or "",
            notes=json_obj.get("notes"),
            accept=json_obj.get("accept"),
            created_from=json_obj.get("issue_id") if "issue_id" in json_obj else None,
            priority=json_obj.get("priority") or state.issues[0].priority,
        )

        new_tasks.append(task)
        output_text += str(task) + "\n"

    # Wait for process to complete and extract metrics
    opencode_proc.wait()
    metrics = extract_metrics(output_text)

    # Determine outcome
    if not new_tasks:
        return StageResult(
            stage=Stage.INVESTIGATE,
            outcome=StageOutcome.FAILURE,
            error="No tasks generated from issues",
        )

    # Update state with new tasks
    state.tasks.extend(new_tasks)

    return StageResult(
        stage=Stage.INVESTIGATE,
        outcome=StageOutcome.SUCCESS,
        tokens_used=metrics.total_tokens_out,
        cost=metrics.total_cost,
    )
