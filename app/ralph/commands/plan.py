"""Ralph plan command.

Plan mode - generate implementation plan from spec.
"""

from pathlib import Path
import subprocess
import argparse
from typing import Optional, Tuple, List

from ralph.config import GlobalConfig
from ralph.state import load_state, save_state, RalphState
from ralph.prompts import load_prompt
from ralph.opencode import spawn_opencode, parse_json_stream
from ralph.models import Task
from ralph.utils import Colors


__all__ = ["cmd_plan"]


def _build_plan_prompt() -> Optional[str]:
    """Load the plan prompt template.

    Returns:
        Prompt content or None if not found.
    """
    try:
        return load_prompt("plan")
    except FileNotFoundError:
        print(f"{Colors.RED}Error: PROMPT_plan.md not found{Colors.RESET}")
        return None


def _run_opencode(config: GlobalConfig, prompt: str) -> Optional[str]:
    """Spawn OpenCode and get output.

    Args:
        config: Ralph configuration.
        prompt: Prompt to send to OpenCode.

    Returns:
        Output string or None on failure.
    """
    process = spawn_opencode(
        prompt=prompt,
        cwd=Path.cwd(),
        timeout=config.timeout_ms,
        model=config.model,
    )
    try:
        output, _ = process.communicate(timeout=config.timeout_ms / 1000)
        return output.decode("utf-8")
    except subprocess.TimeoutExpired:
        process.kill()
        print(f"{Colors.RED}OpenCode process timed out{Colors.RESET}")
        return None
    except Exception as e:
        print(f"{Colors.RED}Error during OpenCode execution: {e}{Colors.RESET}")
        return None


def _parse_plan_output(output_str: str) -> Tuple[List[Task], bool]:
    """Parse task output from OpenCode.

    Args:
        output_str: Raw output from OpenCode.

    Returns:
        Tuple of (list of tasks, success boolean).
    """
    new_tasks: List[Task] = []
    try:
        for task_data in parse_json_stream(output_str):
            if task_data.get("type") == "task":
                try:
                    task = Task.from_dict(task_data)
                    new_tasks.append(task)
                except (TypeError, ValueError) as e:
                    print(
                        f"{Colors.YELLOW}Warning: Skipping invalid task: {e}{Colors.RESET}"
                    )
        return new_tasks, True
    except Exception as e:
        print(f"{Colors.RED}Error parsing tasks: {e}{Colors.RESET}")
        return [], False


def _update_state_with_tasks(
    state: RalphState, new_tasks: List[Task], spec_name: str, plan_file: Path
) -> bool:
    """Update state with new tasks and save.

    Args:
        state: Current Ralph state.
        new_tasks: List of new tasks to add.
        spec_name: Name of the spec file.
        plan_file: Path to plan.jsonl.

    Returns:
        True on success, False on failure.
    """
    state.tasks.clear()
    state.tasks.extend(new_tasks)
    state.issues = [issue for issue in state.issues if issue.spec != spec_name]
    try:
        save_state(state, plan_file)
        return True
    except Exception as e:
        print(f"{Colors.RED}Error saving state: {e}{Colors.RESET}")
        return False


def cmd_plan(config: GlobalConfig, spec_file: str, args: argparse.Namespace) -> int:
    """Plan mode - generate implementation plan from spec.

    Args:
        config: Ralph configuration.
        spec_file: Spec file to plan.
        args: Command-line arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    plan_file = Path.cwd() / "ralph" / "plan.jsonl"
    state = load_state(plan_file)
    spec_path = Path(spec_file)

    try:
        state.spec = spec_path.read_text()
    except (FileNotFoundError, IOError) as e:
        print(f"{Colors.RED}Error reading spec file: {e}{Colors.RESET}")
        return 1

    prompt_content = _build_plan_prompt()
    if prompt_content is None:
        return 1

    output_str = _run_opencode(config, prompt_content)
    if output_str is None:
        return 1

    new_tasks, success = _parse_plan_output(output_str)
    if not success:
        return 1

    if not _update_state_with_tasks(state, new_tasks, spec_path.name, plan_file):
        return 1

    print(f"{Colors.GREEN}Generated {len(new_tasks)} tasks from spec.{Colors.RESET}")
    return 0
