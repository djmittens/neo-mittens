"""Ralph task command.

Task subcommands: add, done, accept, reject, delete, prioritize.
"""

import json
import subprocess
from typing import Optional

from ralph.models import Task, Tombstone
from ralph.state import load_state, save_state
from ralph.utils import Colors, gen_id

__all__ = ["cmd_task"]


def cmd_task(
    config: dict, action: str, arg2: Optional[str] = None, arg3: Optional[str] = None
) -> int:
    """Handle task subcommands.

    Args:
        config: Ralph configuration dict.
        action: Task action (add, done, accept, reject, delete, prioritize).
        arg2: Additional argument (task description or task ID).
        arg3: Third argument (e.g., reject reason).

    Returns:
        Exit code (0 for success, 1 for error).
    """
    plan_file = config["plan_file"]
    state = load_state(plan_file)

    if action == "add":
        return _task_add(state, plan_file, arg2)

    if action == "done":
        return _task_done(state, plan_file, config, arg2)

    if action == "accept":
        return _task_accept(state, plan_file, arg2)

    if action == "reject":
        return _task_reject(state, plan_file, arg2, arg3)

    if action == "delete":
        return _task_delete(state, plan_file, arg2)

    if action == "prioritize":
        return _task_prioritize(state, plan_file, arg2, arg3)

    print(f"{Colors.RED}Unknown task action: {action}{Colors.NC}")
    print("Usage: ralph task [add|done|accept|reject|delete|prioritize]")
    return 1


def _task_add(state, plan_file, arg2: Optional[str]) -> int:
    """Add a new task."""
    if not arg2:
        print(
            f"{Colors.RED}Usage: ralph task add '<json>' or ralph task add 'description'{Colors.NC}"
        )
        return 1

    try:
        data = json.loads(arg2)
        task = Task(
            id=gen_id("t"),
            name=data.get("name", ""),
            spec=state.spec or "",
            notes=data.get("notes"),
            accept=data.get("accept"),
            deps=data.get("deps"),
            priority=data.get("priority"),
            parent=data.get("parent"),
            created_from=data.get("created_from"),
        )
    except json.JSONDecodeError:
        task = Task(
            id=gen_id("t"),
            name=arg2,
            spec=state.spec or "",
        )
    state.add_task(task)
    save_state(state, plan_file)
    print(f"{Colors.GREEN}Task added:{Colors.NC} {task.id} - {task.name}")
    return 0


def _task_done(state, plan_file, config: dict, task_id: Optional[str]) -> int:
    """Mark a task as done."""
    if task_id:
        task = state.get_task_by_id(task_id)
    else:
        task = state.get_next_task()

    if not task:
        print(f"{Colors.YELLOW}No pending tasks{Colors.NC}")
        return 1

    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=config["repo_root"],
    )
    commit_hash = result.stdout.strip() if result.returncode == 0 else None

    task.status = "d"
    task.done_at = commit_hash
    save_state(state, plan_file)

    subprocess.run(["git", "add", str(plan_file)], cwd=config["repo_root"], check=False)
    subprocess.run(
        ["git", "commit", "-m", f"ralph: task done {task.id}"],
        cwd=config["repo_root"],
        check=False,
    )

    print(f"{Colors.GREEN}Task done:{Colors.NC} {task.id} - {task.name}")
    return 0


def _create_accept_tombstone(task: Task) -> Tombstone:
    """Create an accept tombstone for a task."""
    return Tombstone(
        id=task.id,
        done_at=task.done_at or "",
        reason="",
        tombstone_type="accept",
        name=task.name,
        notes=task.notes,
    )


def _update_state_on_accept(state, tasks_to_accept: list) -> None:
    """Update state by creating tombstones and removing accepted tasks."""
    task_ids = {t.id for t in tasks_to_accept}
    for task in tasks_to_accept:
        tombstone = _create_accept_tombstone(task)
        state.add_tombstone(tombstone)
    state.tasks = [t for t in state.tasks if t.id not in task_ids]


def _task_accept(state, plan_file, task_id: Optional[str]) -> int:
    """Accept a done task (or all done tasks)."""
    if task_id:
        return _accept_single_task(state, plan_file, task_id)
    return _accept_all_done_tasks(state, plan_file)


def _accept_single_task(state, plan_file, task_id: str) -> int:
    """Accept a single task by ID."""
    task = state.get_task_by_id(task_id)
    if not task:
        print(f"{Colors.RED}Task not found: {task_id}{Colors.NC}")
        return 1
    if task.status != "d":
        print(f"{Colors.RED}Task not done: {task_id}{Colors.NC}")
        return 1
    _update_state_on_accept(state, [task])
    save_state(state, plan_file)
    print(f"{Colors.GREEN}Task accepted:{Colors.NC} {task_id}")
    return 0


def _accept_all_done_tasks(state, plan_file) -> int:
    """Accept all done tasks."""
    done_tasks = state.done
    if not done_tasks:
        print(f"{Colors.YELLOW}No done tasks to accept{Colors.NC}")
        return 1
    _update_state_on_accept(state, done_tasks)
    save_state(state, plan_file)
    print(f"{Colors.GREEN}Accepted {len(done_tasks)} tasks{Colors.NC}")
    return 0


def _task_reject(
    state, plan_file, task_id: Optional[str], reason: Optional[str]
) -> int:
    """Reject a task."""
    reason = reason or "No reason provided"

    if task_id:
        task = state.get_task_by_id(task_id)
    else:
        done_tasks = state.done
        task = done_tasks[0] if done_tasks else None

    if not task:
        print(f"{Colors.RED}No task to reject{Colors.NC}")
        return 1

    tombstone = Tombstone(
        id=task.id,
        done_at=task.done_at or "",
        reason=reason,
        tombstone_type="reject",
    )
    state.add_tombstone(tombstone)
    task.status = "p"
    task.reject_reason = reason
    save_state(state, plan_file)
    print(f"{Colors.YELLOW}Task rejected:{Colors.NC} {task.id} - {reason}")
    return 0


def _task_delete(state, plan_file, task_id: Optional[str]) -> int:
    """Delete a task."""
    if not task_id:
        print(f"{Colors.RED}Usage: ralph task delete <task-id>{Colors.NC}")
        return 1
    task = state.get_task_by_id(task_id)
    if not task:
        print(f"{Colors.RED}Task not found: {task_id}{Colors.NC}")
        return 1
    state.tasks = [t for t in state.tasks if t.id != task_id]
    save_state(state, plan_file)
    print(f"{Colors.GREEN}Task deleted:{Colors.NC} {task_id}")
    return 0


def _task_prioritize(
    state, plan_file, task_id: Optional[str], priority: Optional[str]
) -> int:
    """Change task priority."""
    if not task_id or not priority:
        print(
            f"{Colors.RED}Usage: ralph task prioritize <task-id> <high|medium|low>{Colors.NC}"
        )
        return 1
    task = state.get_task_by_id(task_id)
    if not task:
        print(f"{Colors.RED}Task not found: {task_id}{Colors.NC}")
        return 1
    task.priority = priority
    save_state(state, plan_file)
    print(f"{Colors.GREEN}Task prioritized:{Colors.NC} {task_id} -> {priority}")
    return 0
