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


def _validate_subtask(
    data: Dict[str, Union[str, int, float, Dict]], parent_spec: str, parent_id: str
) -> Optional[Task]:
    """Validate a single subtask dictionary and create a Task."""
    # Validate input is a dictionary
    if not isinstance(data, dict):
        logger.warning(f"Subtask must be a dictionary, got {type(data)}")
        return None

    # Validate name
    name_val = data.get("name")

    # Handle invalid name cases
    if name_val is None:
        return None

    # Convert to string and strip
    try:
        name_str = str(name_val).strip()
    except Exception:
        return None

    # Check for empty strings or non-string representations
    if not name_str or isinstance(name_val, (dict, list)):
        if isinstance(name_val, (int, float)):
            name_str = str(name_val)
        else:
            return None

    # Generate UUID if no id provided
    subtask_id = str(data.get("id", f"t-{uuid.uuid4().hex[:8]}"))

    # Validate notes
    notes = str(data.get("notes", ""))

    # Validate and convert priority
    priority_val = data.get("priority", "medium")

    # Handle different priority input types
    try:
        if priority_val is None:
            priority = "medium"
        elif isinstance(priority_val, str):
            priority = priority_val
        elif isinstance(priority_val, (int, float)):
            priority = str(int(priority_val))
        elif isinstance(priority_val, dict):
            # Use default for dictionary type
            priority = "medium"
        else:
            priority = "medium"
    except Exception:
        priority = "medium"

    # Validate priority
    priority = priority.strip() if priority else "medium"

    return Task(
        id=subtask_id,
        name=name_str,
        notes=notes,
        spec=parent_spec,
        deps=[parent_id],
        parent=parent_id,
        priority=priority,
    )

    # Validate priority
    priority = priority.strip() if priority else "medium"

    return Task(
        id=subtask_id,
        name=name_str,
        notes=notes,
        spec=parent_spec,
        deps=[parent_id],
        parent=parent_id,
        priority=priority,
    )


def run(state: RalphState, config: GlobalConfig) -> StageResult:
    """Decompose stage breaks down complex or failed tasks into subtasks."""
    try:
        # Identify tasks to decompose (with kill_reason)
        killed_tasks = [t for t in state.tasks if getattr(t, "kill_reason", None)]

        if not killed_tasks:
            return StageResult(stage=Stage.DECOMPOSE, outcome=StageOutcome.SKIP)

        task_to_decompose = killed_tasks[0]
        prompt_text = load_prompt("decompose")

        # Safely build prompt
        try:
            prompt_with_rules = build_prompt_with_rules(
                prompt_text, Path.cwd() / "app/ralph/AGENTS.md"
            )
        except Exception as e:
            logger.error(f"Failed to build prompt: {e}")
            return StageResult(
                stage=Stage.DECOMPOSE,
                outcome=StageOutcome.FAILURE,
                error=f"Prompt build failed: {e}",
            )

        # Prepare context for decomposition
        decompose_context = {
            "task": {
                "id": task_to_decompose.id,
                "name": task_to_decompose.name,
                "notes": task_to_decompose.notes,
                "kill_reason": task_to_decompose.kill_reason,
            }
        }

        # Spawn OpenCode process with timeouts and error handling
        try:
            model = config.model if config.model else None
            process = spawn_opencode(
                prompt_with_rules,
                cwd=Path.cwd(),
                timeout=config.timeout_ms,
                model=model,
            )
            os.environ["OPENCODE_CONTEXT"] = json.dumps(decompose_context)
        except Exception as e:
            logger.error(f"Failed to spawn OpenCode process: {e}")
            return StageResult(
                stage=Stage.DECOMPOSE,
                outcome=StageOutcome.FAILURE,
                error=f"OpenCode spawn failed: {e}",
            )

        # Process communication with error handling
        try:
            output_bytes, _ = process.communicate(timeout=config.timeout_ms // 1000)
            output = output_bytes.decode("utf-8", errors="replace")
        except (subprocess.TimeoutExpired, UnicodeDecodeError) as e:
            logger.error(f"Communication error: {e}")
            return StageResult(
                stage=Stage.DECOMPOSE,
                outcome=StageOutcome.FAILURE,
                error=f"Communication error: {e}",
            )

        # Parse subtasks with robust validation
        subtasks: List[Task] = []
        for item in parse_json_stream(output):
            try:
                if isinstance(item, dict) and "subtasks" in item:
                    # Verify subtasks is a list
                    if not isinstance(item.get("subtasks", []), list):
                        logger.warning(
                            f"Invalid subtasks format: {type(item.get('subtasks'))}"
                        )
                        break

                    # Validate each subtask
                    validated_subtasks = [
                        task
                        for task in [
                            _validate_subtask(
                                t, task_to_decompose.spec, task_to_decompose.id
                            )
                            for t in item["subtasks"]
                        ]
                        if task is not None
                    ]

                    subtasks.extend(validated_subtasks)
                    break
            except Exception as e:
                logger.warning(f"Error processing subtasks item: {e}")

        # Handle failure to decompose
        if not subtasks:
            return StageResult(
                stage=Stage.DECOMPOSE,
                outcome=StageOutcome.FAILURE,
                task_id=task_to_decompose.id,
                kill_reason=task_to_decompose.kill_reason,
                kill_log=getattr(task_to_decompose, "kill_log", None),
                error="No valid subtasks could be generated",
            )

        # Replace parent task with subtasks
        state.tasks = [t for t in state.tasks if t.id != task_to_decompose.id]
        state.tasks.extend(subtasks)

        # Extract metrics with fallback
        try:
            metrics = extract_metrics(output) or Metrics()
        except Exception as e:
            logger.warning(f"Failed to extract metrics: {e}")
            metrics = Metrics()

        return StageResult(
            stage=Stage.DECOMPOSE,
            outcome=StageOutcome.SUCCESS,
            task_id=task_to_decompose.id,
            cost=metrics.total_cost,
            tokens_used=metrics.total_tokens_in + metrics.total_tokens_out,
            error=f"Decomposed task into {len(subtasks)} subtasks",
        )

    except Exception as e:
        logger.error(f"Unexpected error in decompose stage: {e}")
        return StageResult(
            stage=Stage.DECOMPOSE,
            outcome=StageOutcome.FAILURE,
            error=f"Unexpected error: {e}",
        )
