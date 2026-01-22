"""DECOMPOSE stage for breaking down complex tasks."""

import logging
import os
import json
import subprocess
from typing import Optional, List, Dict, Union
from pathlib import Path
import uuid

from ..config import GlobalConfig
from ..state import RalphState
from ..stages.base import Stage, StageResult, StageOutcome
from ..opencode import spawn_opencode, parse_json_stream, extract_metrics
from ..prompts import load_prompt, build_prompt_with_rules
from ..models import Task
from ..context import Metrics

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _extract_name(data: Dict[str, Union[str, int, float, Dict]]) -> Optional[str]:
    """Extract and validate name from subtask data. Returns None if invalid."""
    name_val = data.get("name")
    if name_val is None:
        return None

    try:
        name_str = str(name_val).strip()
    except Exception:
        return None

    if not name_str or isinstance(name_val, (dict, list)):
        if isinstance(name_val, (int, float)):
            return str(name_val)
        return None

    return name_str


def _extract_priority(data: Dict[str, Union[str, int, float, Dict]]) -> str:
    """Extract and normalize priority from subtask data."""
    priority_val = data.get("priority", "medium")
    try:
        if priority_val is None or isinstance(priority_val, dict):
            return "medium"
        if isinstance(priority_val, str):
            return priority_val.strip() or "medium"
        if isinstance(priority_val, (int, float)):
            return str(int(priority_val))
        return "medium"
    except Exception:
        return "medium"


def _validate_subtask(
    data: Dict[str, Union[str, int, float, Dict]], parent_spec: str, parent_id: str
) -> Optional[Task]:
    """Validate a single subtask dictionary and create a Task."""
    if not isinstance(data, dict):
        logger.warning(f"Subtask must be a dictionary, got {type(data)}")
        return None

    name_str = _extract_name(data)
    if name_str is None:
        return None

    return Task(
        id=str(data.get("id", f"t-{uuid.uuid4().hex[:8]}")),
        name=name_str,
        notes=str(data.get("notes", "")),
        spec=parent_spec,
        deps=[parent_id],
        parent=parent_id,
        priority=_extract_priority(data),
    )


def _build_decompose_prompt() -> Optional[str]:
    """Build the decompose prompt with rules. Returns None on failure."""
    prompt_text = load_prompt("decompose")
    try:
        return build_prompt_with_rules(prompt_text, Path.cwd() / "app/ralph/AGENTS.md")
    except Exception as e:
        logger.error(f"Failed to build prompt: {e}")
        return None


def _spawn_and_communicate(
    prompt: str, config: GlobalConfig, task: Task
) -> Optional[str]:
    """Spawn OpenCode and return output. Returns None on failure."""
    decompose_context = {
        "task": {
            "id": task.id,
            "name": task.name,
            "notes": task.notes,
            "kill_reason": getattr(task, "kill_reason", None),
        }
    }
    try:
        model = config.model if config.model else None
        process = spawn_opencode(
            prompt, cwd=Path.cwd(), timeout=config.timeout_ms, model=model
        )
        os.environ["OPENCODE_CONTEXT"] = json.dumps(decompose_context)
    except Exception as e:
        logger.error(f"Failed to spawn OpenCode process: {e}")
        return None

    try:
        output_bytes, _ = process.communicate(timeout=config.timeout_ms // 1000)
        return output_bytes.decode("utf-8", errors="replace")
    except (subprocess.TimeoutExpired, UnicodeDecodeError) as e:
        logger.error(f"Communication error: {e}")
        return None


def _parse_subtasks(output: str, parent_task: Task) -> List[Task]:
    """Parse subtasks from OpenCode output."""
    subtasks: List[Task] = []
    for item in parse_json_stream(output):
        try:
            if not isinstance(item, dict) or "subtasks" not in item:
                continue
            raw_subtasks = item.get("subtasks", [])
            if not isinstance(raw_subtasks, list):
                logger.warning(f"Invalid subtasks format: {type(raw_subtasks)}")
                break
            for t in raw_subtasks:
                task = _validate_subtask(t, parent_task.spec, parent_task.id)
                if task is not None:
                    subtasks.append(task)
            break
        except Exception as e:
            logger.warning(f"Error processing subtasks item: {e}")
    return subtasks


def _extract_metrics_safe(output: str) -> Metrics:
    """Extract metrics with fallback to empty Metrics."""
    try:
        return extract_metrics(output) or Metrics()
    except Exception as e:
        logger.warning(f"Failed to extract metrics: {e}")
        return Metrics()


def run(state: RalphState, config: GlobalConfig) -> StageResult:
    """Decompose stage breaks down complex or failed tasks into subtasks."""
    killed_tasks = [t for t in state.tasks if getattr(t, "kill_reason", None)]
    if not killed_tasks:
        return StageResult(stage=Stage.DECOMPOSE, outcome=StageOutcome.SKIP)

    task = killed_tasks[0]

    prompt = _build_decompose_prompt()
    if prompt is None:
        return StageResult(
            stage=Stage.DECOMPOSE,
            outcome=StageOutcome.FAILURE,
            error="Prompt build failed",
        )

    output = _spawn_and_communicate(prompt, config, task)
    if output is None:
        return StageResult(
            stage=Stage.DECOMPOSE,
            outcome=StageOutcome.FAILURE,
            error="OpenCode communication failed",
        )

    subtasks = _parse_subtasks(output, task)
    if not subtasks:
        return StageResult(
            stage=Stage.DECOMPOSE,
            outcome=StageOutcome.FAILURE,
            task_id=task.id,
            kill_reason=getattr(task, "kill_reason", None),
            kill_log=getattr(task, "kill_log", None),
            error="No valid subtasks could be generated",
        )

    state.tasks = [t for t in state.tasks if t.id != task.id]
    state.tasks.extend(subtasks)

    metrics = _extract_metrics_safe(output)
    return StageResult(
        stage=Stage.DECOMPOSE,
        outcome=StageOutcome.SUCCESS,
        task_id=task.id,
        cost=metrics.total_cost,
        tokens_used=metrics.total_tokens_in + metrics.total_tokens_out,
        error=f"Decomposed task into {len(subtasks)} subtasks",
    )
