"""Ralph plan command.

Plan mode - generate implementation plan from spec.
Uses context injection to pre-populate prompts with spec content.

Features:
- Project rules (AGENTS.md) integration
- Auto-commit plan.jsonl after PLAN_COMPLETE
- Auto-prioritize tasks after planning
- Metrics tracking (cost/tokens/time)
- Git push after commit

Note: Plan mode works by letting OpenCode run `ralph task add` commands.
The tasks are added directly to plan.jsonl by those commands, not parsed
from OpenCode's JSON output.
"""

import re
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple, List

from ..config import GlobalConfig
from ..context import Metrics
from ..git import (
    get_current_branch,
    has_uncommitted_plan,
    push_with_retry,
)
from ..models import Task
from ..opencode import spawn_opencode, extract_metrics
from ..prompts import (
    load_and_inject,
    build_plan_context,
    build_prompt_with_rules,
    find_project_rules,
)
from ..state import load_state, save_state, RalphState
from ..utils import Colors


__all__ = ["cmd_plan"]


def _build_plan_prompt(
    spec_name: str, spec_content: str, project_rules: Optional[str] = None
) -> Optional[str]:
    """Load the plan prompt template with injected spec context.

    Args:
        spec_name: Name of the spec file
        spec_content: Full content of the spec file
        project_rules: Optional project rules from AGENTS.md/CLAUDE.md

    Returns:
        Prompt content with injected context, or None if not found.
    """
    try:
        context = build_plan_context(spec_name, spec_content)
        prompt = load_and_inject("plan", context)
        
        # Prepend project rules if available
        if project_rules:
            prompt = build_prompt_with_rules(prompt, project_rules)
        
        return prompt
    except FileNotFoundError:
        print(f"{Colors.RED}Error: PROMPT_plan.md not found{Colors.NC}")
        return None


def _run_opencode(config: GlobalConfig, prompt: str, cwd: Path) -> Tuple[Optional[str], Metrics]:
    """Spawn OpenCode and get output with metrics.

    OpenCode will run `ralph task add` commands that modify plan.jsonl directly.
    We capture the output to extract metrics and check for completion signal.

    Args:
        config: Ralph configuration.
        prompt: Prompt to send to OpenCode.
        cwd: Working directory.

    Returns:
        Tuple of (output string or None on failure, metrics).
    """
    metrics = Metrics()
    start_time = time.time()
    
    process = spawn_opencode(
        prompt=prompt,
        cwd=cwd,
        timeout=config.timeout_ms,
        model=config.model,  # Use main model for planning (reasoning task)
    )
    
    try:
        output_bytes, _ = process.communicate(timeout=config.timeout_ms / 1000)
        output = output_bytes.decode("utf-8")
        
        # Extract metrics from output
        try:
            metrics = extract_metrics(output)
        except Exception:
            pass
        
        elapsed = time.time() - start_time
        metrics.total_iterations = 1
        
        return output, metrics
        
    except subprocess.TimeoutExpired:
        process.kill()
        print(f"{Colors.RED}OpenCode process timed out{Colors.NC}")
        return None, metrics
    except Exception as e:
        print(f"{Colors.RED}Error during OpenCode execution: {e}{Colors.NC}")
        return None, metrics


def _check_plan_complete(output_str: str) -> Tuple[bool, int]:
    """Check if output contains PLAN_COMPLETE signal.

    Args:
        output_str: Raw output from OpenCode.

    Returns:
        Tuple of (plan_complete, task_count from signal).
    """
    # Check for PLAN_COMPLETE signal
    plan_complete_match = re.search(
        r'\[RALPH\] PLAN_COMPLETE:?\s*(?:Added\s+)?(\d+)?\s*tasks?',
        output_str
    )
    if plan_complete_match:
        task_count = int(plan_complete_match.group(1)) if plan_complete_match.group(1) else 0
        return True, task_count
    return False, 0


def _prioritize_tasks(tasks: List[Task]) -> dict:
    """Auto-prioritize tasks based on dependencies and content.

    Priority rules:
    - Tasks with no deps and "setup"/"init"/"create" in name: high
    - Tasks that are dependencies of many others: high
    - Tasks with many deps: low
    - Default: medium

    Args:
        tasks: List of tasks to prioritize.

    Returns:
        Dict with prioritization stats.
    """
    stats = {"prioritized": 0, "high": 0, "medium": 0, "low": 0}
    
    # Count how many tasks depend on each task
    dep_count = {}
    for task in tasks:
        for dep in (task.deps or []):
            dep_count[dep] = dep_count.get(dep, 0) + 1
    
    for task in tasks:
        if task.priority:
            # Already has priority
            stats[task.priority] = stats.get(task.priority, 0) + 1
            continue
        
        name_lower = task.name.lower()
        deps = task.deps or []
        
        # High priority: foundational tasks
        if not deps and any(kw in name_lower for kw in ["setup", "init", "create", "add module", "extract"]):
            task.priority = "high"
        # High priority: tasks that others depend on
        elif dep_count.get(task.id, 0) >= 2:
            task.priority = "high"
        # Low priority: tasks with many dependencies
        elif len(deps) >= 3:
            task.priority = "low"
        else:
            task.priority = "medium"
        
        stats[task.priority] += 1
        stats["prioritized"] += 1
    
    return stats


def _commit_plan(plan_file: Path, spec_name: str, task_count: int, cwd: Path) -> bool:
    """Commit the plan.jsonl file.

    Args:
        plan_file: Path to plan.jsonl.
        spec_name: Name of the spec file.
        task_count: Number of tasks in the plan.
        cwd: Working directory for git commands.

    Returns:
        True if committed successfully, False otherwise.
    """
    if not has_uncommitted_plan(plan_file, cwd):
        return True  # Nothing to commit
    
    try:
        subprocess.run(
            ["git", "add", str(plan_file)],
            cwd=cwd,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"ralph: plan {spec_name} ({task_count} tasks)"],
            cwd=cwd,
            capture_output=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _print_plan_header(
    spec_name: str,
    branch: str,
    rules_source: Optional[str],
    config: GlobalConfig,
) -> None:
    """Print the plan mode header."""
    print(f"{Colors.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
    print(f"Mode:   {Colors.GREEN}plan{Colors.NC}")
    print(f"Spec:   {Colors.CYAN}{spec_name}{Colors.NC}")
    print(f"Branch: {branch}")
    if rules_source:
        print(f"Rules:  {Colors.GREEN}{rules_source}{Colors.NC}")
    else:
        print(f"Rules:  {Colors.YELLOW}None{Colors.NC}")
    print(f"Model:  {config.model or 'default'}")
    print(f"{Colors.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")


def _print_plan_report(
    tasks: List[Task],
    metrics: Metrics,
    priority_stats: dict,
    committed: bool,
    pushed: bool,
) -> None:
    """Print the plan completion report."""
    print()
    print(f"{Colors.GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
    print(f"{Colors.GREEN}PLAN COMPLETE{Colors.NC}")
    print()
    
    # Task summary
    print(f"Tasks:    {len(tasks)} total")
    if priority_stats["prioritized"] > 0:
        print(f"Priority: {priority_stats['high']} high, {priority_stats['medium']} medium, {priority_stats['low']} low")
    
    # Metrics
    if metrics.total_cost > 0:
        print(f"Cost:     ${metrics.total_cost:.4f}")
    if metrics.tokens_used > 0:
        print(f"Tokens:   {metrics.tokens_used:,}")
    
    # Git status
    if committed:
        print(f"Commit:   {Colors.GREEN}Yes{Colors.NC}")
    if pushed:
        print(f"Push:     {Colors.GREEN}Yes{Colors.NC}")
    
    print(f"{Colors.GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
    
    # Show task list
    if tasks:
        print()
        print(f"{Colors.YELLOW}PENDING TASKS ({len(tasks)}){Colors.NC}")
        print()
        for i, task in enumerate(tasks, 1):
            priority = task.priority or "medium"
            priority_color = {
                "high": Colors.RED,
                "medium": Colors.YELLOW,
                "low": Colors.DIM,
            }.get(priority, "")
            print(f"  {i}. {task.name} [{task.id}] {priority_color}({priority}){Colors.NC}")
            if task.deps:
                print(f"     {Colors.CYAN}Deps:{Colors.NC} {', '.join(task.deps)}")


def cmd_plan(config: GlobalConfig, spec_file: str, args) -> int:
    """Plan mode - generate implementation plan from spec.

    This command:
    1. Loads the spec file
    2. Builds a prompt with the spec content injected
    3. Runs OpenCode which executes `ralph task add` commands
    4. Reloads state to get the added tasks
    5. Auto-prioritizes and commits

    Args:
        config: Ralph configuration.
        spec_file: Spec file to plan.
        args: Command-line arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    cwd = Path.cwd()
    ralph_dir = cwd / "ralph"
    plan_file = ralph_dir / "plan.jsonl"
    
    # Check ralph is initialized
    if not ralph_dir.exists():
        print(f"{Colors.RED}Ralph not initialized. Run 'ralph init' first.{Colors.NC}")
        return 1
    
    # Load initial state (to get task count before planning)
    initial_state = load_state(plan_file)
    initial_task_count = len(initial_state.tasks)
    
    # Resolve spec file path
    spec_path = Path(spec_file)
    if not spec_path.exists():
        # Try ralph/specs/ directory
        spec_path = ralph_dir / "specs" / spec_file
    if not spec_path.exists():
        print(f"{Colors.RED}Spec file not found: {spec_file}{Colors.NC}")
        return 1
    
    # Read spec content
    try:
        spec_content = spec_path.read_text()
        spec_name = spec_path.name
    except (FileNotFoundError, IOError) as e:
        print(f"{Colors.RED}Error reading spec file: {e}{Colors.NC}")
        return 1
    
    # Load project rules
    project_rules = find_project_rules(cwd)
    rules_source = None
    if project_rules:
        for candidate in ["AGENTS.md", "CLAUDE.md"]:
            if (cwd / candidate).exists():
                rules_source = candidate
                break
    
    # Get branch info
    branch = get_current_branch(cwd)
    
    # Print header
    _print_plan_header(spec_name, branch, rules_source, config)
    
    # Build prompt
    prompt_content = _build_plan_prompt(spec_name, spec_content, project_rules)
    if prompt_content is None:
        return 1
    
    print(f"\n{Colors.CYAN}Running plan generation...{Colors.NC}\n")
    
    # Run OpenCode - it will execute `ralph task add` commands
    output_str, metrics = _run_opencode(config, prompt_content, cwd)
    if output_str is None:
        return 1
    
    # Check for completion signal
    plan_complete, signal_task_count = _check_plan_complete(output_str)
    
    # Reload state to get tasks added by OpenCode's `ralph task add` commands
    state = load_state(plan_file)
    
    # Count new tasks
    new_task_count = len(state.tasks) - initial_task_count
    
    # Get tasks for this spec
    spec_tasks = [t for t in state.tasks if t.spec == spec_name]
    
    if new_task_count == 0 and not plan_complete:
        print(f"{Colors.YELLOW}No tasks were added. OpenCode may have failed or the spec may already be implemented.{Colors.NC}")
        # Show last 30 lines of output for debugging
        output_lines = output_str.strip().split('\n')
        if len(output_lines) > 30:
            print(f"\n{Colors.DIM}... (showing last 30 lines of output){Colors.NC}")
            for line in output_lines[-30:]:
                print(f"  {line}")
        else:
            for line in output_lines:
                print(f"  {line}")
        return 1
    
    # Set spec on state
    state.spec = spec_name
    state.stage = "BUILD"
    
    # Auto-prioritize tasks
    priority_stats = _prioritize_tasks(spec_tasks)
    
    # Save state with updated priorities
    save_state(state, plan_file)
    
    # Commit plan
    committed = _commit_plan(plan_file, spec_name, len(spec_tasks), cwd)
    if committed:
        print(f"{Colors.GREEN}Committed plan with {len(spec_tasks)} tasks{Colors.NC}")
    
    # Push to remote
    pushed = False
    if committed:
        pushed = push_with_retry(branch, retries=2, plan_file=plan_file, cwd=cwd)
        if pushed:
            print(f"{Colors.GREEN}Pushed to origin/{branch}{Colors.NC}")
    
    # Print report
    _print_plan_report(spec_tasks, metrics, priority_stats, committed, pushed)
    
    return 0
