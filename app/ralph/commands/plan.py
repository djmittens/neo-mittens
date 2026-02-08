"""Ralph plan command.

Plan mode - generate implementation plan from spec.
Uses context injection to pre-populate prompts with spec content.

Features:
- Project rules (AGENTS.md) integration
- Auto-commit plan after PLAN_COMPLETE
- Metrics tracking (cost/tokens/time)
- Git push after commit
- Incremental planning — existing pending tasks are preserved, agent adds/drops
- Multi-iteration gap detection

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
from ..opencode import (
    spawn_opencode,
    spawn_opencode_continue,
    stream_and_collect,
    SessionResult,
)
from ..prompts import (
    load_and_inject, build_plan_context, build_prompt_with_rules, find_project_rules,
)
from ..reconcile import reconcile_plan, ReconcileResult
from ..state import load_state, save_state
from ..tix import Tix, TixError
from ..utils import Colors


__all__ = ["cmd_plan"]


# Maximum plan iterations for gap detection
DEFAULT_MAX_PLAN_ITERATIONS = 5
# Minimum timeout for plan mode (15 minutes)
MIN_PLAN_TIMEOUT_MS = 900_000
# Maximum tombstones to include in prompt (avoid context bloat)
MAX_HISTORY_ITEMS = 30


def _build_tix_history(tix: Tix, spec_name: str) -> str:
    """Build a formatted history section from tix tombstones for the spec.

    Queries accepted and rejected tombstones so the planning agent can
    learn from prior work — avoiding re-creating accepted tasks and
    addressing rejection reasons in new tasks.

    Args:
        tix: Tix harness instance.
        spec_name: Spec name to filter tombstones for.

    Returns:
        Formatted markdown string for prompt injection, or empty string.
    """
    try:
        tombstones = tix.query_tombstones()
    except TixError:
        return ""

    accepted = tombstones.get("accepted", [])
    rejected = tombstones.get("rejected", [])

    if not accepted and not rejected:
        return ""

    lines = ["## Prior Work History (from tix)", ""]

    if accepted:
        lines.append(f"### Accepted Tasks ({len(accepted)} completed)")
        lines.append("These tasks were already completed and verified. Do NOT re-create them.")
        lines.append("")
        for task in accepted[:MAX_HISTORY_ITEMS]:
            name = task.get("name", "unknown")
            tid = task.get("id", "?")
            lines.append(f"- [{tid}] {name}")
        if len(accepted) > MAX_HISTORY_ITEMS:
            lines.append(f"- ... and {len(accepted) - MAX_HISTORY_ITEMS} more")
        lines.append("")

    if rejected:
        lines.append(f"### Rejected Tasks ({len(rejected)} failed verification)")
        lines.append("These tasks were attempted but failed. Study the rejection reasons.")
        lines.append("")
        for task in rejected[:MAX_HISTORY_ITEMS]:
            name = task.get("name", "unknown")
            tid = task.get("id", "?")
            reason = task.get("reason", "no reason recorded")
            lines.append(f"- [{tid}] {name}")
            lines.append(f"  Rejected: {reason}")
        if len(rejected) > MAX_HISTORY_ITEMS:
            lines.append(f"- ... and {len(rejected) - MAX_HISTORY_ITEMS} more")
        lines.append("")

    return "\n".join(lines)


def _build_plan_prompt(
    spec_name: str,
    spec_content: str,
    project_rules: Optional[str] = None,
    tix_history: Optional[str] = None,
    pending_tasks: Optional[str] = None,
) -> Optional[str]:
    """Load the plan prompt template with injected spec context.

    Args:
        spec_name: Name of the spec file
        spec_content: Full content of the spec file
        project_rules: Optional project rules from AGENTS.md/CLAUDE.md
        tix_history: Optional formatted tix history for the spec
        pending_tasks: Optional formatted pending tasks for incremental planning

    Returns:
        Prompt content with injected context, or None if not found.
    """
    context = build_plan_context(
        spec_name, spec_content, tix_history, pending_tasks
    )
    prompt = load_and_inject("plan", context)

    # Prepend project rules if available
    if project_rules:
        prompt = build_prompt_with_rules(prompt, project_rules)

    return prompt


def _run_opencode(
    config: GlobalConfig,
    prompt: str,
    cwd: Path,
    session_id: Optional[str] = None,
) -> Tuple[Optional[str], Metrics, Optional[str]]:
    """Spawn OpenCode and stream output in real-time.

    Args:
        config: Ralph configuration.
        prompt: Prompt to send to OpenCode.
        cwd: Working directory.
        session_id: If provided, continues an existing session.

    Returns:
        Tuple of (output string or None on failure, metrics, session_id).
    """
    timeout = max(config.timeout_ms, MIN_PLAN_TIMEOUT_MS)
    timeout_seconds = timeout // 1000

    if session_id:
        proc = spawn_opencode_continue(
            session_id, prompt, cwd=cwd, model=config.model
        )
    else:
        proc = spawn_opencode(
            prompt=prompt, cwd=cwd, timeout=timeout, model=config.model,
        )

    try:
        result = stream_and_collect(proc, timeout_seconds, print_output=True)

        if result.timed_out:
            print(f"{Colors.RED}OpenCode process timed out{Colors.NC}")
            return None, result.metrics, result.session_id

        return result.raw_output, result.metrics, result.session_id

    except KeyboardInterrupt:
        proc.kill()
        print(f"\n{Colors.YELLOW}Interrupted.{Colors.NC}")
        return None, Metrics(), None
    except Exception as e:
        print(f"{Colors.RED}Error during OpenCode execution: {e}{Colors.NC}")
        return None, Metrics(), None


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


def _get_pending_tasks_for_spec(tix: Tix, spec_name: str, branch: str) -> list[dict]:
    """Get pending tasks for a spec on the current branch.

    Filters by both spec name and branch to ensure branch isolation.

    Args:
        tix: Tix harness instance.
        spec_name: Spec name to filter tasks for.
        branch: Current git branch name.

    Returns:
        List of pending task dicts matching spec and branch.
    """
    try:
        tasks = tix.query_tasks()
    except TixError:
        return []

    return [
        t for t in tasks
        if t.get("spec") == spec_name
        and (t.get("branch", "") == branch or t.get("branch", "") == "")
        and t.get("assigned", "") == "ralph"
    ]


# Maximum pending tasks to include in prompt (avoid context bloat)
MAX_PENDING_ITEMS = 30


def _build_pending_tasks(tix: Tix, spec_name: str, branch: str) -> str:
    """Build a formatted section of existing pending tasks for the prompt.

    Shows the agent what tasks already exist so it can decide whether to
    keep them (do nothing), drop them (add to "drop" array), or add new
    tasks alongside them.

    Args:
        tix: Tix harness instance.
        spec_name: Spec name to filter tasks for.
        branch: Current git branch name.

    Returns:
        Formatted markdown string for prompt injection, or empty string.
    """
    tasks = _get_pending_tasks_for_spec(tix, spec_name, branch)

    if not tasks:
        return ""

    lines = [f"## Existing Pending Tasks ({len(tasks)} on branch {branch})", ""]
    lines.append("These tasks are already in the backlog. Review each one:")
    lines.append("- **Keep**: If still valid, do nothing (do NOT include in your output).")
    lines.append("- **Drop**: If obsolete or superseded, add its ID to your `\"drop\"` array.")
    lines.append("- You may reference these IDs in `deps` for new tasks.")
    lines.append("")

    for task in tasks[:MAX_PENDING_ITEMS]:
        tid = task.get("id", "?")
        name = task.get("name", "untitled")
        priority = task.get("priority", "medium")
        deps = task.get("deps", [])
        notes = task.get("notes", "")
        accept = task.get("accept", "")
        lines.append(f"- **[{tid}]** {name} ({priority})")
        if deps:
            lines.append(f"  Deps: {', '.join(deps)}")
        if notes:
            # Truncate long notes to keep prompt manageable
            short_notes = notes[:200] + "..." if len(notes) > 200 else notes
            lines.append(f"  Notes: {short_notes}")
        if accept:
            short_accept = accept[:150] + "..." if len(accept) > 150 else accept
            lines.append(f"  Accept: {short_accept}")

    if len(tasks) > MAX_PENDING_ITEMS:
        lines.append(f"- ... and {len(tasks) - MAX_PENDING_ITEMS} more")

    lines.append("")
    return "\n".join(lines)


def _commit_tix_plan(tix: Tix, spec_name: str, task_count: int, cwd: Path) -> bool:
    """Commit the tix plan.jsonl file.

    Args:
        tix: Tix harness instance.
        spec_name: Name of the spec file.
        task_count: Number of tasks in the plan.
        cwd: Working directory for git commands.

    Returns:
        True if committed successfully, False otherwise.
    """
    plan_file = tix.plan_file()
    if not has_uncommitted_plan(plan_file, cwd):
        return True  # Nothing to commit
    
    try:
        # Also commit ralph-state.json if it changed
        state_file = cwd / ".tix" / "ralph-state.json"
        files_to_add = [str(plan_file)]
        if state_file.exists():
            files_to_add.append(str(state_file))

        subprocess.run(
            ["git", "add"] + files_to_add,
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
    2. Gathers existing pending tasks and tombstone history
    3. Builds a prompt with spec + backlog context injected
    4. Runs OpenCode which outputs [RALPH_OUTPUT] JSON
    5. Reconciles agent output — adds new tasks, drops obsolete ones
    6. Auto-prioritizes, commits, and pushes

    Args:
        config: Ralph configuration.
        spec_file: Spec file to plan.
        args: Command-line arguments.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    cwd = Path.cwd()
    ralph_dir = cwd / "ralph"

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

    # Gather tix history (tombstones: accepted/rejected)
    tix_history = _build_tix_history(tix, spec_name)
    if tix_history:
        print(f"{Colors.DIM}Loaded tix history for {spec_name}{Colors.NC}")

    # Gather existing pending tasks for incremental planning
    pending_tasks = _build_pending_tasks(tix, spec_name, branch)
    if pending_tasks:
        pending_count = len(_get_pending_tasks_for_spec(tix, spec_name, branch))
        print(f"{Colors.DIM}Found {pending_count} existing pending tasks{Colors.NC}")

    prompt_content = _build_plan_prompt(
        spec_name, spec_content, project_rules, tix_history, pending_tasks
    )
    if prompt_content is None:
        return 1

    print(f"\n{Colors.CYAN}Running plan generation...{Colors.NC}\n")

    output_str, metrics, session_id = _run_opencode(config, prompt_content, cwd)
    if output_str is None:
        return 1

    return _finalize_plan(
        tix, output_str, metrics, spec_name, branch, cwd,
        config=config, session_id=session_id,
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


def _build_plan_validation_feedback(validation_errors: list[str]) -> str:
    """Build follow-up prompt for PLAN validation failures."""
    error_list = "\n".join(f"- {e}" for e in validation_errors)
    return f"""The harness rejected some of your planned tasks because they failed validation.

## Validation Errors

{error_list}

## What to fix

Your acceptance criteria MUST be a **specific, runnable shell command** targeting
the exact files/tests for this task. The harness auto-executes these commands to
verify tasks — vague or untargeted criteria cannot be auto-verified.

**Bad** (will be rejected):
- `make test`, `pytest`, `npm test` (runs entire suite, not specific to task)
- `works correctly`, `is implemented` (not a command)
- `tests pass` (which tests?)

**Good** (will be accepted):
- `pytest tests/unit/test_config.py -v` (specific test file)
- `test -f src/foo.py && python3 -c "from foo import Bar"` (file exists + import works)
- `grep -c "class GlobalConfig" app/ralph/config.py` returns 1

Also ensure task notes are >= 50 characters with specific file paths and line numbers.

Please output a corrected [RALPH_OUTPUT] block with ONLY the fixed tasks.
Do not repeat tasks that already passed validation.
"""


def _finalize_plan(
    tix: Tix,
    output_str: str,
    metrics: Metrics,
    spec_name: str,
    branch: str,
    cwd: Path,
    config: Optional[GlobalConfig] = None,
    session_id: Optional[str] = None,
) -> int:
    """Reconcile agent output, prioritize, commit, and report."""
    # Reconcile — parse [RALPH_OUTPUT], add new tasks, drop obsolete ones
    recon = reconcile_plan(tix, output_str, spec_name)

    # Validation retry loop: if tasks were rejected by the harness,
    # continue the same session with error feedback (reuses cached tokens).
    max_retries = 2
    validation_errors = [
        e for e in recon.errors if "rejected by validation" in e
    ]
    retry = 0
    while (validation_errors and session_id and config
           and retry < max_retries):
        retry += 1
        print(f"\n{Colors.YELLOW}PLAN validation retry {retry}/{max_retries} "
              f"— {len(validation_errors)} task(s) failed, "
              f"continuing session{Colors.NC}")

        feedback = _build_plan_validation_feedback(validation_errors)
        retry_output, retry_metrics, session_id = _run_opencode(
            config, feedback, cwd, session_id=session_id
        )
        if retry_output is None:
            break

        metrics.total_cost += retry_metrics.total_cost
        metrics.total_tokens_in += retry_metrics.total_tokens_in
        metrics.total_tokens_out += retry_metrics.total_tokens_out

        recon = reconcile_plan(tix, retry_output, spec_name)
        if recon.tasks_added:
            print(f"  Retry {retry}: added {len(recon.tasks_added)} tasks")

        validation_errors = [
            e for e in recon.errors if "rejected by validation" in e
        ]

    # A valid incremental plan may have adds, drops, or both
    if not recon.tasks_added and not recon.tasks_deleted:
        _show_debug_output(output_str, recon)
        return 1

    if recon.tasks_added:
        print(f"{Colors.GREEN}Added {len(recon.tasks_added)} tasks via tix{Colors.NC}")
    if recon.tasks_deleted:
        print(f"{Colors.YELLOW}Dropped {len(recon.tasks_deleted)} obsolete tasks{Colors.NC}")

    # Get tasks back from tix for prioritization and reporting
    spec_tasks = tix.query_tasks()

    # Auto-prioritize
    priority_stats = _prioritize_tasks_tix(tix, spec_tasks)

    # Update orchestration state
    state = load_state(cwd)
    state.spec = spec_name
    state.stage = "BUILD"
    save_state(state, cwd)

    # Commit and push
    committed = _commit_tix_plan(tix, spec_name, len(spec_tasks), cwd)
    if committed:
        print(f"{Colors.GREEN}Committed plan with {len(spec_tasks)} tasks{Colors.NC}")

    pushed = False
    if committed:
        plan_file = tix.plan_file()
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
