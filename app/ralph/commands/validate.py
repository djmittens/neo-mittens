from typing import Optional, Dict, Any
from pathlib import Path

from ..config import GlobalConfig
from ..state import load_state
from ..models import Task, RalphPlanConfig


def _validate_task_notes(notes: str) -> list[str]:
    """Validate task notes with detailed checks."""
    errors = []
    if len(notes) < 50:
        errors.append("Task notes must be at least 50 characters long.")

    # Check for vague or forbidden phrases
    forbidden_phrases = [
        "implement X",
        "fix the bug",
        "do something",
        "handle stuff",
        "make it work",
        "improve code",
    ]
    for phrase in forbidden_phrases:
        if phrase.lower() in notes.lower():
            errors.append(f"Vague phrase found: '{phrase}'. Be more specific.")

    # Require some specific references
    if not any(x in notes for x in ["src/", "file:", "line ", "function ", "module "]):
        errors.append("Notes should reference specific files, lines, or functions.")

    return errors


def _validate_acceptance_criteria(accept: str) -> list[str]:
    """Validate task acceptance criteria."""
    errors = []
    if len(accept) < 15:
        errors.append("Acceptance criteria must be at least 15 characters long.")

    # Check for concrete verification steps
    if not any(
        x in accept
        for x in ["&&", "cd ", "grep", "test ", "echo ", "assert", "python -c"]
    ):
        errors.append(
            "Acceptance criteria should include verifiable commands or actions."
        )

    return errors


def _validate_priority(priority: Optional[str]) -> list[str]:
    """Validate task priority."""
    errors = []
    valid_priorities = ["high", "medium", "low"]

    if not priority:
        errors.append("Priority is missing. Recommended to set priority.")
    elif priority not in valid_priorities:
        errors.append(
            f"Invalid priority '{priority}'. Must be one of: {', '.join(valid_priorities)}"
        )

    return errors


def _validate_task_fields(task: Dict[str, Any]) -> list[str]:
    """Validate required task fields."""
    errors = []

    # Check required fields are present
    required_fields = ["id", "name", "notes", "accept"]
    for field in required_fields:
        if field not in task or not task[field]:
            errors.append(f"Missing required field: {field}")

    # Optional but recommended validation if fields exist
    if "notes" in task and task["notes"]:
        errors.extend(_validate_task_notes(task["notes"]))

    if "accept" in task and task["accept"]:
        errors.extend(_validate_acceptance_criteria(task["accept"]))

    # Validate priority
    if "priority" in task:
        errors.extend(_validate_priority(task.get("priority")))
    else:
        errors.append("Recommended: Set task priority")

    return errors


def cmd_validate(config: GlobalConfig, args) -> int:
    """Validate tasks in current state.

    Checks:
    - All tasks have required fields
    - Notes are detailed
    - Acceptance criteria are measurable
    - Dependencies reference existing task IDs

    Args:
        config: Global configuration
        args: Command-line arguments (not used in this implementation)

    Returns:
        Exit code: 0 if valid, 1 if errors found
    """
    # Load current state
    try:
        state = load_state(Path("plan.jsonl"))
    except Exception as e:
        print(f"Error loading state: {e}")
        return 1

    all_errors: list[str] = []
    task_ids = {task.id for task in state.tasks}

    # Validate each task
    for task in state.tasks:
        # Convert task to dict for validation
        task_dict = task.to_dict()

        # Check task fields
        task_errors = _validate_task_fields(task_dict)
        all_errors.extend(task_errors)

        # Validate dependencies
        if "deps" in task_dict:
            for dep_id in task_dict["deps"]:
                if dep_id not in task_ids:
                    all_errors.append(
                        f"Task {task.id} has invalid dependency: {dep_id}"
                    )

    # Output results
    if all_errors:
        print("Task Validation Errors:")
        for error in all_errors:
            print(f"- {error}")
        return 1

    print("All tasks validated successfully.")
    return 0
