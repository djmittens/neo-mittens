"""Ralph plan command.

Plan mode - generate implementation plan from spec.
Uses context injection to pre-populate prompts with spec content.

Features:
- Project rules (AGENTS.md) integration
- Auto-commit plan.jsonl after PLAN_COMPLETE
- Metrics tracking (cost/tokens/time)
- Git push after commit

Agent outputs structured JSON via [RALPH_OUTPUT] markers.
Harness reconciles via tix — agent never calls task commands directly.
"""

import json
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from ..config import GlobalConfig
from ..context import Metrics
from ..git import get_current_branch, has_uncommitted_plan, push_with_retry
from ..opencode import spawn_opencode, extract_metrics
from ..prompts import (
    load_and_inject, build_plan_context, build_prompt_with_rules, find_project_rules,
)
from ..reconcile import reconcile_plan, ReconcileResult
from ..state import load_state, save_state
from ..tix import Tix, TixError
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
    """Spawn OpenCode and stream output in real-time.

    Args:
        config: Ralph configuration.
        prompt: Prompt to send to OpenCode.
        cwd: Working directory.

    Returns:
        Tuple of (output string or None on failure, metrics).
    """
    metrics = Metrics()
    start_time = time.time()
    output_lines = []
    
    process = spawn_opencode(
        prompt=prompt,
        cwd=cwd,
        timeout=config.timeout_ms,
        model=config.model,  # Use main model for planning (reasoning task)
    )
    
    try:
        # Stream output in real-time
        while True:
            # Check if process has finished
            retcode = process.poll()
            
            # Read available output
            if process.stdout:
                ready, _, _ = select.select([process.stdout], [], [], 0.1)
                if ready:
                    line = process.stdout.readline()
                    if line:
                        line_str = line.decode("utf-8", errors="replace")
                        output_lines.append(line_str)
                        
                        # Parse and display based on event type
                        try:
                            event = json.loads(line_str.strip())
                            _display_event(event)
                        except json.JSONDecodeError:
                            # Not JSON, print raw
                            print(line_str, end="", flush=True)
            
            # If process finished and no more output, break
            if retcode is not None:
                # Drain remaining output
                if process.stdout:
                    remaining = process.stdout.read()
                    if remaining:
                        for line in remaining.decode("utf-8", errors="replace").splitlines(keepends=True):
                            output_lines.append(line)
                            try:
                                event = json.loads(line.strip())
                                _display_event(event)
                            except json.JSONDecodeError:
                                print(line, end="", flush=True)
                break
        
        output = "".join(output_lines)
        
        # Extract metrics from output
        try:
            metrics = extract_metrics(output)
        except Exception:
            pass
        
        metrics.total_iterations = 1
        
        return output, metrics
        
    except subprocess.TimeoutExpired:
        process.kill()
        print(f"{Colors.RED}OpenCode process timed out{Colors.NC}")
        return None, metrics
    except KeyboardInterrupt:
        process.kill()
        print(f"\n{Colors.YELLOW}Interrupted.{Colors.NC}")
        return None, metrics
    except Exception as e:
        print(f"{Colors.RED}Error during OpenCode execution: {e}{Colors.NC}")
        return None, metrics


def _display_event(event: dict) -> None:
    """Display an OpenCode JSON event in a human-readable format."""
    event_type = event.get("type", "")
    
    part = event.get("part", {})
    if event_type == "assistant":
        content = event.get("content", "")
        if content:
            print(content, end="", flush=True)
    elif event_type == "text":
        text = part.get("text", "")
        if text:
            print(text, end="", flush=True)
    elif event_type == "tool_use":
        tool = part.get("tool", "unknown")
        title = part.get("state", {}).get("title", "")
        label = f"[{tool}] {title}" if title else f"[{tool}]"
        print(f"\n{Colors.DIM}{label}{Colors.NC}", flush=True)
    elif event_type == "step_finish":
        cost = part.get("cost", 0)
        tok = part.get("tokens", {})
        inp = tok.get("input", 0) + tok.get("cache", {}).get("read", 0)
        out = tok.get("output", 0)
        print(f"\n{Colors.DIM}─ ${cost:.4f} | {inp}in/{out}out{Colors.NC}", flush=True)
    elif event_type == "error":
        msg = event.get("message", event.get("error", "Unknown error"))
        print(f"\n{Colors.RED}Error: {msg}{Colors.NC}", flush=True)


def _prioritize_tasks_tix(tix: Tix, tasks: list[dict]) -> dict:
    """Auto-prioritize tasks via tix based on dependencies and content.

    Priority rules:
    - Tasks with no deps and "setup"/"init"/"create" in name: high
    - Tasks that are dependencies of many others: high
    - Tasks with many deps: low
    - Default: medium

    Args:
        tix: Tix harness instance.
        tasks: List of task dicts from tix.query_tasks().

    Returns:
        Dict with prioritization stats.
    """
    stats = {"prioritized": 0, "high": 0, "medium": 0, "low": 0}

    dep_count: dict[str, int] = {}
    for task in tasks:
        for dep in task.get("deps", []):
            dep_count[dep] = dep_count.get(dep, 0) + 1

    for task in tasks:
        if task.get("priority"):
            stats[task["priority"]] = stats.get(task["priority"], 0) + 1
            continue

        name_lower = task.get("name", "").lower()
        deps = task.get("deps", [])
        tid = task.get("id", "")

        if not deps and any(kw in name_lower for kw in ["setup", "init", "create", "add module", "extract"]):
            priority = "high"
        elif dep_count.get(tid, 0) >= 2:
            priority = "high"
        elif len(deps) >= 3:
            priority = "low"
        else:
            priority = "medium"

        try:
            tix.task_prioritize(tid, priority)
        except TixError:
            pass

        stats[priority] += 1
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
    tasks: list[dict],
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
            priority = task.get("priority", "medium")
            tid = task.get("id", "?")
            name = task.get("name", "untitled")
            deps = task.get("deps", [])
            priority_color = {
                "high": Colors.RED,
                "medium": Colors.YELLOW,
                "low": Colors.DIM,
            }.get(priority, "")
            print(f"  {i}. {name} [{tid}] {priority_color}({priority}){Colors.NC}")
            if deps:
                print(f"     {Colors.CYAN}Deps:{Colors.NC} {', '.join(deps)}")


def cmd_plan(config: GlobalConfig, spec_file: str, args) -> int:
    """Plan mode - generate implementation plan from spec.

    This command:
    1. Loads the spec file
    2. Builds a prompt with the spec content injected
    3. Runs OpenCode which outputs [RALPH_OUTPUT] JSON
    4. Reconciles agent output — creates tasks via tix
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

    if not ralph_dir.exists():
        print(f"{Colors.RED}Ralph not initialized. Run 'ralph init' first.{Colors.NC}")
        return 1

    # Initialize tix
    tix = Tix(cwd)

    # Resolve spec file path
    spec_path = _resolve_spec_path(spec_file, ralph_dir)
    if spec_path is None:
        print(f"{Colors.RED}Spec file not found: {spec_file}{Colors.NC}")
        return 1

    spec_content, spec_name = _read_spec(spec_path)
    if spec_content is None:
        return 1

    # Load project rules and branch info
    project_rules = find_project_rules(cwd)
    rules_source = _find_rules_source(cwd, project_rules)
    branch = get_current_branch(cwd)

    _print_plan_header(spec_name, branch, rules_source, config)

    prompt_content = _build_plan_prompt(spec_name, spec_content, project_rules)
    if prompt_content is None:
        return 1

    print(f"\n{Colors.CYAN}Running plan generation...{Colors.NC}\n")

    output_str, metrics = _run_opencode(config, prompt_content, cwd)
    if output_str is None:
        return 1

    return _finalize_plan(
        tix, output_str, metrics, spec_name, plan_file, branch, cwd
    )


def _resolve_spec_path(spec_file: str, ralph_dir: Path) -> Optional[Path]:
    """Resolve spec file path, checking cwd and ralph/specs/."""
    spec_path = Path(spec_file)
    if spec_path.exists():
        return spec_path
    spec_path = ralph_dir / "specs" / spec_file
    if spec_path.exists():
        return spec_path
    return None


def _read_spec(spec_path: Path) -> Tuple[Optional[str], str]:
    """Read spec file content and name."""
    try:
        return spec_path.read_text(), spec_path.name
    except (FileNotFoundError, IOError) as e:
        print(f"{Colors.RED}Error reading spec file: {e}{Colors.NC}")
        return None, ""


def _find_rules_source(cwd: Path, project_rules: Optional[str]) -> Optional[str]:
    """Find which rules file is being used."""
    if not project_rules:
        return None
    for candidate in ["AGENTS.md", "CLAUDE.md"]:
        if (cwd / candidate).exists():
            return candidate
    return None


def _finalize_plan(
    tix: Tix,
    output_str: str,
    metrics: Metrics,
    spec_name: str,
    plan_file: Path,
    branch: str,
    cwd: Path,
) -> int:
    """Reconcile agent output, prioritize, commit, and report."""
    # Reconcile — parse [RALPH_OUTPUT] and create tasks via tix
    recon = reconcile_plan(tix, output_str, spec_name)

    if not recon.tasks_added:
        _show_debug_output(output_str, recon)
        return 1

    print(f"{Colors.GREEN}Added {len(recon.tasks_added)} tasks via tix{Colors.NC}")

    # Get tasks back from tix for prioritization and reporting
    spec_tasks = tix.query_tasks()

    # Auto-prioritize
    priority_stats = _prioritize_tasks_tix(tix, spec_tasks)

    # Update orchestration state (spec/stage)
    state = load_state(plan_file)
    state.spec = spec_name
    state.stage = "BUILD"
    save_state(state, plan_file)

    # Commit and push
    committed = _commit_plan(plan_file, spec_name, len(spec_tasks), cwd)
    if committed:
        print(f"{Colors.GREEN}Committed plan with {len(spec_tasks)} tasks{Colors.NC}")

    pushed = False
    if committed:
        pushed = push_with_retry(branch, retries=2, plan_file=plan_file, cwd=cwd)
        if pushed:
            print(f"{Colors.GREEN}Pushed to origin/{branch}{Colors.NC}")

    _print_plan_report(spec_tasks, metrics, priority_stats, committed, pushed)
    return 0


def _show_debug_output(output_str: str, recon: ReconcileResult) -> None:
    """Show debug info when no tasks were added."""
    print(f"{Colors.YELLOW}No tasks were added.{Colors.NC}")
    if recon.errors:
        for err in recon.errors:
            print(f"  {Colors.RED}{err}{Colors.NC}")
    output_lines = output_str.strip().split("\n")
    tail = output_lines[-30:] if len(output_lines) > 30 else output_lines
    if len(output_lines) > 30:
        print(f"\n{Colors.DIM}... (showing last 30 lines){Colors.NC}")
    for line in tail:
        print(f"  {line}")
