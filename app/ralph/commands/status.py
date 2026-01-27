"""Ralph status command.

Shows the current status of Ralph for a repository.
"""

import subprocess
from pathlib import Path
from typing import Optional

from ralph.state import load_state
from ralph.utils import Colors

__all__ = ["cmd_status"]


def _get_current_branch() -> str:
    """Get current git branch."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _get_log_dir(spec: Optional[str], branch: str) -> str:
    """Get log directory path."""
    repo_name = Path.cwd().name
    spec_name = spec.replace(".md", "") if spec else "default"
    return f"/tmp/ralph-logs/{repo_name}/{branch}/{spec_name}"


def _is_ralph_running_in_cwd() -> bool:
    """Check if Ralph (opencode) is running in the current directory."""
    cwd = str(Path.cwd())
    try:
        result = subprocess.run(
            ["pgrep", "-x", "opencode"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False
        
        pids = result.stdout.strip().split("\n")
        for pid in pids:
            try:
                proc_cwd = Path(f"/proc/{pid}/cwd").resolve()
                if str(proc_cwd) == cwd:
                    return True
            except (OSError, PermissionError):
                continue
        return False
    except Exception:
        return False


def _print_header() -> None:
    """Print status header."""
    print(f"{Colors.BLUE}{'=' * 60}{Colors.NC}")
    print(f"{Colors.BLUE}RALPH STATUS{Colors.NC}")
    print(f"{Colors.BLUE}{'=' * 60}{Colors.NC}")
    print()


def _print_overview(state, branch: str) -> None:
    """Print overview section."""
    print(f"{Colors.CYAN}Overview{Colors.NC}")
    print(f"  Repo:   {Path.cwd()}")
    print(f"  Branch: {branch}")
    print(f"  Spec:   {Colors.CYAN}{state.spec or 'Not set'}{Colors.NC}")
    print(f"  Logs:   {Colors.DIM}{_get_log_dir(state.spec, branch)}{Colors.NC}")
    print(f"  Stage:  {Colors.GREEN}{state.get_stage()}{Colors.NC}")
    
    if _is_ralph_running_in_cwd():
        print(f"  Status: {Colors.BOLD}{Colors.GREEN}Running{Colors.NC}")
    else:
        print(f"  Status: {Colors.BOLD}{Colors.YELLOW}Stopped{Colors.NC}")
    print()


def _truncate(text: str, max_len: int = 70) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _print_single_task(task, icon: str, icon_color: str) -> None:
    """Print a single task with its details."""
    priority = f"[{task.priority}]" if task.priority else ""
    print(f"  {icon_color}{icon}{Colors.NC} {task.id} {priority} {task.name}")
    if task.accept:
        print(f"    {Colors.DIM}accept: {_truncate(task.accept)}{Colors.NC}")
    if task.deps:
        print(f"    {Colors.DIM}deps: {', '.join(task.deps)}{Colors.NC}")


def _print_tasks(state) -> None:
    """Print tasks section."""
    done_count = len(state.done)
    pending_count = len(state.pending)
    print(f"{Colors.CYAN}Tasks ({done_count} done, {pending_count} pending){Colors.NC}")
    print(f"{Colors.DIM}{'-' * 60}{Colors.NC}")

    for task in state.pending:
        _print_single_task(task, "○", Colors.YELLOW)

    for task in state.done:
        _print_single_task(task, "✓", Colors.GREEN)

    if not state.pending and not state.done:
        print(f"  {Colors.DIM}No tasks{Colors.NC}")
    print()


def _print_issues(state) -> None:
    """Print issues section."""
    print(f"{Colors.CYAN}Issues ({len(state.issues)}){Colors.NC}")
    print(f"{Colors.DIM}{'-' * 60}{Colors.NC}")

    for issue in state.issues:
        print(f"  {Colors.RED}!{Colors.NC} {issue.id} {issue.desc}")
        if hasattr(issue, "source") and issue.source:
            print(f"    {Colors.DIM}source: {issue.source}{Colors.NC}")

    if not state.issues:
        print(f"  {Colors.DIM}No issues{Colors.NC}")
    print()


def _print_tombstone_section(
    items: list, title: str, icon: str, icon_color: str, show_reason: bool = False
) -> None:
    """Print a tombstone section (accepted or rejected)."""
    if not items:
        return
    print(f"{Colors.CYAN}{title} ({len(items)}){Colors.NC}")
    print(f"{Colors.DIM}{'-' * 60}{Colors.NC}")
    for tomb in items[-5:]:
        name = tomb.name if hasattr(tomb, "name") else tomb.id
        print(f"  {icon_color}{icon}{Colors.NC} {tomb.id} {name}")
        if show_reason and hasattr(tomb, "reason") and tomb.reason:
            print(f"    {Colors.DIM}Reason: {_truncate(tomb.reason)}{Colors.NC}")
    if len(items) > 5:
        print(f"  {Colors.DIM}... and {len(items) - 5} more{Colors.NC}")
    print()


def _print_tombstones(state) -> None:
    """Print rejected and accepted tombstones."""
    rejected = state.tombstones.get("rejected", [])
    accepted = state.tombstones.get("accepted", [])
    _print_tombstone_section(rejected, "Rejected", "✗", Colors.RED, show_reason=True)
    _print_tombstone_section(accepted, "Accepted", "✓", Colors.GREEN)


def _print_next_action(state) -> None:
    """Print next action section."""
    print(f"{Colors.CYAN}Next Action{Colors.NC}")
    print(f"{Colors.DIM}{'-' * 60}{Colors.NC}")
    print(f"  {Colors.GREEN}{state.get_stage()}{Colors.NC}")
    print()
    print(
        f"{Colors.DIM}Use 'ralph query' for JSON output, 'ralph watch' for live dashboard{Colors.NC}"
    )


def cmd_status(config: dict) -> int:
    """Show current Ralph status.

    Args:
        config: Ralph configuration dict with ralph_dir, plan_file, etc.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    plan_file = config["plan_file"]
    if not plan_file.exists():
        print(
            f"{Colors.YELLOW}Ralph not initialized. Run 'ralph init' first.{Colors.NC}"
        )
        return 1

    state = load_state(plan_file)
    branch = _get_current_branch()

    _print_header()
    _print_overview(state, branch)
    _print_tasks(state)
    _print_issues(state)
    _print_tombstones(state)
    _print_next_action(state)

    return 0
