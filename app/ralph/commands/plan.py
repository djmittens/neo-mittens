"""Ralph plan command.

Plan mode - generate implementation plan from spec.
"""

from pathlib import Path
import subprocess
import json
import argparse

from ralph.config import GlobalConfig
from ralph.state import load_state, save_state, RalphState
from ralph.prompts import load_prompt
from ralph.opencode import spawn_opencode, parse_json_stream
from ralph.models import Task, Issue
from ralph.utils import Colors


__all__ = ["cmd_plan"]


def cmd_plan(config: GlobalConfig, spec_file: str, args: argparse.Namespace) -> int:
    """Plan mode - generate implementation plan from spec.

    Args:
        config: Ralph configuration.
        spec_file: Spec file to plan.
        args: Command-line arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    # 1. Load state from plan.jsonl
    plan_file = Path.cwd() / "ralph" / "plan.jsonl"
    state = load_state(plan_file)

    # 2. Read spec file content
    try:
        spec_path = Path(spec_file)
        state.spec = spec_path.read_text()
    except (FileNotFoundError, IOError) as e:
        print(f"{Colors.RED}Error reading spec file: {e}{Colors.RESET}")
        return 1

    # 3. Load PROMPT_plan.md
    try:
        prompt_content = load_prompt("plan")
    except FileNotFoundError:
        print(f"{Colors.RED}Error: PROMPT_plan.md not found{Colors.RESET}")
        return 1

    # 4. Spawn OpenCode with plan prompt
    process = spawn_opencode(
        prompt=prompt_content,
        cwd=Path.cwd(),
        timeout=config.timeout_ms,
        model=config.model,
    )

    # Wait for process to complete and get output
    try:
        output, _ = process.communicate(timeout=config.timeout_ms / 1000)
        output_str = output.decode("utf-8")
    except subprocess.TimeoutExpired:
        process.kill()
        print(f"{Colors.RED}OpenCode process timed out{Colors.RESET}")
        return 1
    except Exception as e:
        print(f"{Colors.RED}Error during OpenCode execution: {e}{Colors.RESET}")
        return 1

    # 5. Parse JSON task output
    state.tasks.clear()  # Clear existing tasks
    new_tasks = []

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

        # Add tasks to state
        state.tasks.extend(new_tasks)
    except Exception as e:
        print(f"{Colors.RED}Error parsing tasks: {e}{Colors.RESET}")
        return 1

    # 6. Save state
    try:
        save_state(state, plan_file)
    except Exception as e:
        print(f"{Colors.RED}Error saving state: {e}{Colors.RESET}")
        return 1

    # 7. Clear issues for spec
    state.issues = [issue for issue in state.issues if issue.spec != spec_path.name]

    # 8. Save state again with cleared issues
    try:
        save_state(state, plan_file)
    except Exception as e:
        print(
            f"{Colors.RED}Error saving state after clearing issues: {e}{Colors.RESET}"
        )
        return 1

    print(f"{Colors.GREEN}Generated {len(new_tasks)} tasks from spec.{Colors.RESET}")
    return 0
