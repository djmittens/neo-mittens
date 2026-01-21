"""DECOMPOSE stage for breaking down complex tasks."""

from typing import Optional

import os
import json
from pathlib import Path

from ralph.config import GlobalConfig
from ralph.state import RalphState
from ralph.stages.base import Stage, StageResult, StageOutcome
from ralph.opencode import spawn_opencode, parse_json_stream, extract_metrics
from ralph.prompts import load_prompt, build_prompt_with_rules
from ralph.models import Task
from ralph.context import Metrics


def run(state: RalphState, config: GlobalConfig) -> StageResult:
    """Decompose stage breaks down complex or failed tasks into subtasks."""
    killed_tasks = [t for t in state.tasks if getattr(t, "kill_reason", None)]

    if not killed_tasks:
        return StageResult(stage=Stage.DECOMPOSE, outcome=StageOutcome.SKIP)

    task_to_decompose = killed_tasks[0]
    prompt_text = load_prompt("decompose")
    prompt_with_rules = build_prompt_with_rules(
        prompt_text, Path.cwd() / "app/ralph/AGENTS.md"
    )

    decompose_context = {
        "task": {
            "id": task_to_decompose.id,
            "name": task_to_decompose.name,
            "notes": task_to_decompose.notes,
            "kill_reason": task_to_decompose.kill_reason,
        }
    }

    model = config.model if config.model else None

    process = spawn_opencode(
        prompt_with_rules, cwd=Path.cwd(), timeout=config.timeout_ms, model=model
    )
    os.environ["OPENCODE_CONTEXT"] = json.dumps(decompose_context)
    output = process.communicate()[0].decode("utf-8")

    subtasks = []
    for item in parse_json_stream(output):
        if isinstance(item, dict) and "subtasks" in item:
            subtasks = [
                Task(
                    id=t.get("id", None),
                    name=t["name"],
                    notes=t.get("notes", ""),
                    spec=task_to_decompose.spec,
                    deps=[task_to_decompose.id],
                    parent=task_to_decompose.id,
                    priority=t.get("priority", "medium"),
                )
                for t in item["subtasks"]
            ]
            break

    if not subtasks:
        return StageResult(
            stage=Stage.DECOMPOSE,
            outcome=StageOutcome.FAILURE,
            task_id=task_to_decompose.id,
            kill_reason=task_to_decompose.kill_reason,
            kill_log=task_to_decompose.kill_log,
        )

    state.tasks = [t for t in state.tasks if t.id != task_to_decompose.id]
    state.tasks.extend(subtasks)

    metrics = extract_metrics(output)
    return StageResult(
        stage=Stage.DECOMPOSE,
        outcome=StageOutcome.SUCCESS,
        task_id=task_to_decompose.id,
        cost=metrics.total_cost,
        tokens_used=metrics.total_tokens_in + metrics.total_tokens_out,
        error=f"Decomposed task into {len(subtasks)} subtasks",
    )
