"""Ralph subagent command.

Generate structured subagent prompts with JSON schemas.
"""

import json
from typing import Optional

from ralph.subagent import (
    build_investigate_prompt,
    build_verify_task_prompt,
    build_verify_criterion_prompt,
    build_research_prompt,
    build_decompose_prompt,
    get_schema,
    validate_response,
)
from ralph.utils import Colors

__all__ = ["cmd_subagent"]


def cmd_subagent(
    subagent_type: str,
    context_json: Optional[str] = None,
    validate_json: Optional[str] = None,
) -> int:
    """Generate subagent prompts or validate responses.

    Args:
        subagent_type: Type of subagent (investigate, verify_task, verify_criterion, research, decompose)
        context_json: JSON string with context for prompt generation
        validate_json: JSON string to validate against schema

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # If validate_json provided, validate against schema
    if validate_json:
        return _validate_response(subagent_type, validate_json)

    # Otherwise, generate a prompt
    if not context_json:
        print(f"{Colors.RED}Error: --context required for prompt generation{Colors.NC}")
        _print_usage()
        return 1

    try:
        context = json.loads(context_json)
    except json.JSONDecodeError as e:
        print(f"{Colors.RED}Error: Invalid JSON context: {e}{Colors.NC}")
        return 1

    return _generate_prompt(subagent_type, context)


def _generate_prompt(subagent_type: str, context: dict) -> int:
    """Generate a subagent prompt based on type and context."""
    try:
        if subagent_type == "investigate":
            prompt = build_investigate_prompt(
                issue_id=context.get("issue_id", ""),
                issue_desc=context.get("issue_desc", ""),
                priority=context.get("priority", "medium"),
            )
        elif subagent_type == "verify_task":
            prompt = build_verify_task_prompt(
                task_id=context.get("task_id", ""),
                task_name=context.get("task_name", ""),
                accept_criteria=context.get("accept_criteria", ""),
            )
        elif subagent_type == "verify_criterion":
            prompt = build_verify_criterion_prompt(
                criterion=context.get("criterion", ""),
                spec_file=context.get("spec_file", ""),
            )
        elif subagent_type == "research":
            prompt = build_research_prompt(
                requirement=context.get("requirement", ""),
                spec_file=context.get("spec_file", ""),
            )
        elif subagent_type == "decompose":
            prompt = build_decompose_prompt(
                task_name=context.get("task_name", ""),
                task_notes=context.get("task_notes", ""),
                kill_reason=context.get("kill_reason", ""),
            )
        else:
            print(f"{Colors.RED}Error: Unknown subagent type: {subagent_type}{Colors.NC}")
            _print_usage()
            return 1

        # Output the rendered prompt
        print(prompt.render())
        return 0

    except Exception as e:
        print(f"{Colors.RED}Error generating prompt: {e}{Colors.NC}")
        return 1


def _validate_response(subagent_type: str, response_json: str) -> int:
    """Validate a subagent response against its schema."""
    try:
        response = json.loads(response_json)
    except json.JSONDecodeError as e:
        result = {
            "valid": False,
            "errors": [f"Invalid JSON: {e}"],
        }
        print(json.dumps(result))
        return 1

    is_valid, errors = validate_response(subagent_type, response)
    result = {
        "valid": is_valid,
        "errors": errors,
    }
    print(json.dumps(result))
    return 0 if is_valid else 1


def cmd_subagent_schema(subagent_type: str) -> int:
    """Output the JSON schema for a subagent type.

    Args:
        subagent_type: Type of subagent

    Returns:
        Exit code (0 for success, 1 for error)
    """
    schema = get_schema(subagent_type)
    if not schema:
        print(f"{Colors.RED}Error: Unknown subagent type: {subagent_type}{Colors.NC}")
        _print_usage()
        return 1

    print(json.dumps(schema, indent=2))
    return 0


def _print_usage() -> None:
    """Print usage information."""
    print("""
Usage: ralph subagent <type> --context '<json>' [--validate '<json>']

Subagent types:
  investigate      - Investigate an issue, return root cause and task
  verify_task      - Verify a task meets acceptance criteria
  verify_criterion - Verify a spec criterion still holds
  research         - Research a requirement in the codebase
  decompose        - Analyze how to decompose a killed task

Examples:
  # Generate an investigate prompt
  ralph subagent investigate --context '{"issue_id": "i-123", "issue_desc": "Test failure"}'

  # Validate a response
  ralph subagent investigate --validate '{"issue_id": "i-123", "root_cause": "...", "resolution": "task"}'

  # Get the schema
  ralph subagent-schema investigate
""")
