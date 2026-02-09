"""Ralph construct command.

Construct mode - main autonomous development loop.

Features:
- Project rules (AGENTS.md) integration
- Context injection for stage prompts
- Circuit breaker (batch failures handled by state machine in stages/base.py)
- Max cost limit
- Git sync/push each iteration
- Full metrics tracking
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple, Callable

from ..config import GlobalConfig
from ..context import Metrics, LoopDetector, SessionSummary, context_pressure
from ..git import (
    get_current_branch,
    get_current_commit,
    get_uncommitted_diff,
    push_with_retry,
    sync_with_remote,
    IterationCommitInfo,
    TaskVerdict,
    commit_iteration,
    lookup_task_names,
)
from ..ledger import (
    RunRecord,
    IterationRecord,
    StageBreakdown,
    TokenBreakdown,
    config_snapshot,
    write_iteration,
    write_run,
    _generate_run_id,
    _get_worktree_root,
)
from ..opencode import (
    spawn_opencode,
    spawn_opencode_continue,
    stream_and_collect,
    SessionResult,
)
from ..prompts import (
    find_project_rules,
    build_prompt_with_rules,
    load_and_inject,
    build_build_context,
    build_verify_context,
    build_investigate_context,
    build_decompose_context,
)
from ..reconcile import (
    dedup_tasks,
    reconcile_build,
    reconcile_verify,
    reconcile_investigate,
    reconcile_decompose,
    ReconcileResult,
)
from ..tix import Tix, TixError, TixProtocol
from ..stages.base import (
    ConstructStateMachine,
    Stage,
    StageOutcome,
    StageResult,
)
from ..state import RalphState, load_state, save_state
from ..commands.init import cmd_init
from ..utils import Colors

__all__ = ["cmd_construct"]

# Mutable container for passing reconcile result from _run_stage to wrapper.
# Set by _run_stage after reconciliation, read by the stage wrapper for
# IterationRecord. Reset each iteration.
_last_reconcile_result: dict[str, Optional[ReconcileResult]] = {"result": None}

# Default values
DEFAULT_MAX_FAILURES = 3
DEFAULT_STAGE_TIMEOUT_MS = 900_000  # 15 minutes
DEFAULT_CONTEXT_WINDOW = 200_000


def _check_opencode_available() -> Tuple[bool, str]:
    """Check if opencode is available and configured.
    
    Returns:
        Tuple of (is_available, error_message).
    """
    try:
        result = subprocess.run(
            ["opencode", "--version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, ""
        return False, f"opencode exited with code {result.returncode}"
    except FileNotFoundError:
        return False, "opencode not found. Install with: go install github.com/opencode-ai/opencode@latest"
    except subprocess.TimeoutExpired:
        return False, "opencode --version timed out"
    except Exception as e:
        return False, f"Error checking opencode: {e}"


def _load_spec_content(ralph_dir: Path, spec_name: str) -> str:
    """Load spec file content for prompt injection.

    Args:
        ralph_dir: Path to ralph directory.
        spec_name: Name of the spec file (e.g. "feature.md").

    Returns:
        Spec file content, or empty string if not found.
    """
    if not spec_name:
        return ""
    spec_path = ralph_dir / "specs" / spec_name
    if not spec_path.exists():
        return ""
    try:
        return spec_path.read_text()
    except OSError:
        return ""


def _filter_by_spec(items: list[dict], spec_name: str) -> list[dict]:
    """Filter task/issue dicts to only those belonging to *spec_name*.

    Items with an empty ``spec`` field are kept so in-flight work
    (e.g. issues created during BUILD) isn't silently dropped.
    """
    if not spec_name:
        return items
    return [t for t in items if t.get("spec", "") in (spec_name, "")]


def _filter_full_by_spec(full: dict, spec_name: str) -> dict:
    """Filter a query_full() result dict so every list is spec-scoped."""
    if not spec_name:
        return full
    tasks = full.get("tasks", {})
    return {
        "tasks": {
            status: _filter_by_spec(task_list, spec_name)
            for status, task_list in tasks.items()
        },
        "issues": _filter_by_spec(full.get("issues", []), spec_name),
    }


_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _pick_best_task(
    tasks: list[dict],
    retry_counts: Optional[dict[str, int]] = None,
) -> dict:
    """Select the highest-priority task from a list of pending tasks.

    Priority ordering:
      0. Dependency readiness: tasks with unmet deps sort last
      1. Priority field: high > medium > low > unset
      2. Retry count: prefer fresher tasks (lower retries)
      3. Original order preserved as tiebreaker

    A dep is "unmet" if its ID is still in the pending task list.

    Args:
        tasks: Non-empty list of task dicts from tix.
        retry_counts: In-memory retry counts from ConstructStateMachine.

    Returns:
        The best task to build next.
    """
    pending_ids = {t.get("id", "") for t in tasks}
    retries_map = retry_counts or {}

    def sort_key(task: dict) -> tuple[int, int, int]:
        deps = task.get("deps") or []
        unmet = 1 if any(d in pending_ids for d in deps) else 0
        prio = _PRIORITY_ORDER.get(
            task.get("priority", ""), 3
        )
        tid = task.get("id", "")
        retries = retries_map.get(tid, 0)
        return (unmet, prio, retries)

    return min(tasks, key=sort_key)


def _build_stage_prompt_tix(
    stage: Stage,
    tix: TixProtocol,
    state: RalphState,
    ralph_dir: Path,
    project_rules: Optional[str] = None,
    config: Optional[GlobalConfig] = None,
    repo_root: Optional[Path] = None,
) -> Tuple[Optional[str], Optional[dict]]:
    """Build a prompt for a stage using tix for ticket data.
    
    Returns:
        Tuple of (prompt_string, context_metadata) where context_metadata
        contains stage-specific info needed for reconciliation (e.g. task_id).
        Returns (None, None) if stage cannot be built.
    """
    stage_name = stage.name.lower()
    spec_name = state.spec or ""
    meta: dict = {"spec_name": spec_name}
    spec_content = _load_spec_content(ralph_dir, spec_name)
    
    if stage == Stage.BUILD:
        tasks = _filter_by_spec(tix.query_tasks(), spec_name)
        if not tasks:
            return None, None
        task = _pick_best_task(tasks)
        context = build_build_context(task, spec_name, spec_content)
        meta["task_id"] = task.get("id", "")
    elif stage == Stage.VERIFY:
        full = _filter_full_by_spec(tix.query_full(), spec_name)
        done = full.get("tasks", {}).get("done", [])
        if not done:
            return None, None
        max_diff = config.diff_max_bytes if config else 200_000
        build_diff = get_uncommitted_diff(cwd=repo_root, max_bytes=max_diff)
        context = build_verify_context(
            done, spec_name, spec_content, build_diff=build_diff,
        )
    elif stage == Stage.INVESTIGATE:
        issues = _filter_by_spec(tix.query_issues(), spec_name)
        if not issues:
            return None, None
        # Filter to batch items if batching is active
        batch_ids = list(state.batch_items) if state.batch_items else None
        if batch_ids:
            issues = [i for i in issues if i.get("id") in batch_ids]
            meta["batch_issue_ids"] = batch_ids
        else:
            meta["batch_issue_ids"] = [i.get("id", "") for i in issues]
        pending_tasks = _filter_by_spec(tix.query_tasks(), spec_name)
        context = build_investigate_context(
            issues, spec_name, spec_content, pending_tasks=pending_tasks
        )
    elif stage == Stage.DECOMPOSE:
        # Find killed task from state's decompose_target
        target_id = state.decompose_target
        if not target_id:
            return None, None
        full = _filter_full_by_spec(tix.query_full(), spec_name)
        all_tasks = (
            full.get("tasks", {}).get("pending", [])
            + full.get("tasks", {}).get("done", [])
        )
        task = next((t for t in all_tasks if t.get("id") == target_id), None)
        if not task:
            return None, None
        max_depth = getattr(config, "max_decompose_depth", 3) if config else 3
        context = build_decompose_context(
            task, spec_name, spec_content, max_depth
        )
        meta["task_id"] = target_id
        meta["parent_depth"] = task.get("decompose_depth", 0)
    else:
        return None, None
    
    prompt = load_and_inject(stage_name, context)
    if project_rules:
        prompt = build_prompt_with_rules(prompt, project_rules)
    return prompt, meta


def _reconcile_stage(
    stage: Stage,
    tix: TixProtocol,
    agent_output: str,
    meta: dict,
) -> ReconcileResult:
    """Reconcile agent output for a stage via tix.
    
    Args:
        stage: Which stage just completed.
        tix: Tix harness instance.
        agent_output: Full stdout from the agent.
        meta: Context metadata from prompt building (e.g. task_id).
    
    Returns:
        ReconcileResult summarizing what was done.
    """
    sm = meta.get("stage_metrics")
    spec = meta.get("spec_name", "")
    if stage == Stage.BUILD:
        return reconcile_build(
            tix, agent_output, meta.get("task_id", ""),
            stage_metrics=sm, spec_name=spec,
        )
    elif stage == Stage.VERIFY:
        return reconcile_verify(
            tix, agent_output, stage_metrics=sm, spec_name=spec,
        )
    elif stage == Stage.INVESTIGATE:
        return reconcile_investigate(
            tix, agent_output, meta.get("batch_issue_ids"),
            stage_metrics=sm, spec_name=spec,
        )
    elif stage == Stage.DECOMPOSE:
        return reconcile_decompose(
            tix, agent_output, meta.get("task_id", ""),
            parent_depth=meta.get("parent_depth", 0),
            stage_metrics=sm, spec_name=spec,
        )
    else:
        return ReconcileResult(ok=False, errors=[f"Unknown stage: {stage}"])


def _make_result(
    stage: Stage,
    outcome: StageOutcome,
    duration: float = 0.0,
    exit_code: int = 0,
    error: Optional[str] = None,
    kill_reason: Optional[str] = None,
    cost: float = 0.0,
    tokens_used: int = 0,
    task_id: Optional[str] = None,
) -> StageResult:
    """Create a StageResult with the given parameters."""
    return StageResult(
        stage=stage,
        outcome=outcome,
        exit_code=exit_code,
        duration_seconds=duration,
        error=error,
        kill_reason=kill_reason,
        cost=cost,
        tokens_used=tokens_used,
        task_id=task_id,
    )


def _execute_opencode(
    config: GlobalConfig,
    prompt: str,
    repo_root: Path,
    stage_timeout_ms: int,
    print_output: bool = True,
    stage_name: str = "",
    session_id: Optional[str] = None,
) -> Tuple[int, str, bool, float, int, int, int, int, Optional[str], int]:
    """Execute opencode with real-time streaming output.

    Args:
        session_id: If provided, continues an existing session instead
            of starting a new one. Reuses cached context.

    Returns:
        Tuple of (return_code, output, timed_out, cost, tokens_in,
                  tokens_cached, tokens_out, iterations, session_id,
                  last_context_size).
    """
    model = config.model_for_stage(stage_name) if stage_name else config.model

    if session_id:
        proc = spawn_opencode_continue(
            session_id, prompt, cwd=repo_root, model=model
        )
    else:
        proc = spawn_opencode(
            prompt, cwd=repo_root, timeout=stage_timeout_ms, model=model
        )

    timeout_seconds = stage_timeout_ms // 1000
    result = stream_and_collect(proc, timeout_seconds, print_output=print_output)

    return (result.return_code, result.raw_output, result.timed_out,
            result.metrics.total_cost, result.metrics.total_tokens_in,
            result.metrics.total_tokens_cached,
            result.metrics.total_tokens_out, result.metrics.total_iterations,
            result.session_id, result.metrics.last_context_size)


def _run_stage(
    config: GlobalConfig,
    stage: Stage,
    state: RalphState,
    metrics: Metrics,
    stage_timeout_ms: int,
    repo_root: Path,
    ralph_dir: Path,
    project_rules: Optional[str],
    print_output: bool,
    tix: TixProtocol,
    start_time: float,
    run_id: str = "",
) -> StageResult:
    """Run a stage using tix for ticket data and reconcile after."""
    prompt, meta = _build_stage_prompt_tix(
        stage, tix, state, ralph_dir, project_rules, config,
        repo_root=repo_root,
    )
    if not prompt or meta is None:
        return _make_result(
            stage, StageOutcome.SKIP,
            error=f"No prompt for {stage.name}",
        )

    stage_task_id = meta.get("task_id", "") or None

    try:
        (return_code, stdout_output, timed_out, cost,
         tokens_in, tokens_cached, tokens_out, stage_iters,
         session_id, last_ctx_size) = _execute_opencode(
            config, prompt, repo_root, stage_timeout_ms,
            print_output=print_output,
            stage_name=stage.name.lower(),
        )
    except Exception as e:
        return _make_result(
            stage, StageOutcome.FAILURE,
            time.time() - start_time, error=str(e),
            task_id=stage_task_id,
        )

    tokens = tokens_in + tokens_out
    metrics.total_cost += cost
    metrics.total_tokens_in += tokens_in
    metrics.total_tokens_cached += tokens_cached
    metrics.total_tokens_out += tokens_out

    if timed_out:
        metrics.kills_timeout += 1
        metrics.last_kill_reason = "timeout"
        return _make_result(
            stage, StageOutcome.FAILURE,
            time.time() - start_time,
            error="Stage timed out",
            kill_reason="timeout",
            cost=cost, tokens_used=tokens,
            task_id=stage_task_id,
        )

    # Detect context pressure — compare the *last turn's* context size
    # (actual window occupancy) against the configured window, not the
    # cumulative total_tokens_in which grows without bound.
    kill_pct = getattr(config, "context_kill_pct", 95)
    compact_pct = getattr(config, "context_compact_pct", 85)
    ctx_window = getattr(config, "context_window", 200_000)
    if ctx_window > 0 and last_ctx_size > 0:
        usage_pct = (last_ctx_size / ctx_window) * 100
        if usage_pct >= kill_pct:
            metrics.kills_context += 1
            metrics.last_kill_reason = "context_pressure"
            print(f"  Context pressure: {usage_pct:.0f}% "
                  f"({last_ctx_size:,}/{ctx_window:,} tokens, "
                  f"kill threshold: {kill_pct}%)")
        elif usage_pct >= compact_pct:
            print(f"  Context pressure: {usage_pct:.0f}% "
                  f"({last_ctx_size:,}/{ctx_window:,} tokens, "
                  f"compact threshold: {compact_pct}%)")

    # Build per-task telemetry for reconciliation
    stage_model = config.model_for_stage(stage.name.lower())
    stage_metrics: dict[str, Any] = {
        "cost": round(cost, 6),
        "tokens_in": tokens_in,
        "tokens_cached": tokens_cached,
        "tokens_out": tokens_out,
        "iterations": stage_iters,
        "model": stage_model or "",
    }
    if run_id:
        stage_metrics["run_id"] = run_id
    meta["stage_metrics"] = stage_metrics

    # Reconcile agent output through tix
    reconcile_result = _reconcile_stage(stage, tix, stdout_output, meta)
    _last_reconcile_result["result"] = reconcile_result

    # Log reconciliation summary
    print(f"  Reconcile: {reconcile_result.summary}")
    if reconcile_result.errors:
        for err in reconcile_result.errors:
            print(f"  Error: {err}", file=sys.stderr)

    # Validation retry loop: if tasks were rejected by the harness
    # (not by the LLM), continue the same session with error feedback.
    # This reuses cached tokens instead of tearing down the session.
    max_retries = 2
    validation_errors = [
        e for e in reconcile_result.errors
        if "rejected by validation" in e
    ]
    retry = 0
    while validation_errors and session_id and retry < max_retries:
        retry += 1
        print(f"\n  {Colors.YELLOW}Validation retry {retry}/{max_retries} "
              f"— {len(validation_errors)} task(s) failed validation, "
              f"continuing session{Colors.NC}")

        feedback = _build_validation_feedback(validation_errors)
        try:
            (rc2, out2, to2, c2, ti2, tc2, to_out2, si2,
             session_id, _) = _execute_opencode(
                config, feedback, repo_root, stage_timeout_ms,
                print_output=print_output,
                stage_name=stage.name.lower(),
                session_id=session_id,
            )
        except Exception:
            break

        # Accumulate metrics from retry
        metrics.validation_retries += 1
        cost += c2
        tokens_in += ti2
        tokens_cached += tc2
        tokens_out += to_out2
        tokens = tokens_in + tokens_out
        stage_iters += si2
        metrics.total_cost += c2
        metrics.total_tokens_in += ti2
        metrics.total_tokens_cached += tc2
        metrics.total_tokens_out += to_out2

        if to2:
            break  # Timed out on retry, stop

        # Update meta and re-reconcile
        meta["stage_metrics"]["cost"] = round(cost, 6)
        meta["stage_metrics"]["tokens_in"] = tokens_in
        meta["stage_metrics"]["tokens_cached"] = tokens_cached
        meta["stage_metrics"]["tokens_out"] = tokens_out
        meta["stage_metrics"]["iterations"] = stage_iters
        reconcile_result = _reconcile_stage(stage, tix, out2, meta)
        _last_reconcile_result["result"] = reconcile_result

        print(f"  Reconcile (retry {retry}): {reconcile_result.summary}")
        if reconcile_result.errors:
            for err in reconcile_result.errors:
                print(f"  Error: {err}", file=sys.stderr)

        validation_errors = [
            e for e in reconcile_result.errors
            if "rejected by validation" in e
        ]

    duration = time.time() - start_time

    # Count accepted tasks for session metrics
    metrics.tasks_completed += len(reconcile_result.tasks_accepted)

    if return_code == 0 and reconcile_result.ok:
        return _make_result(
            stage, StageOutcome.SUCCESS, duration,
            cost=cost, tokens_used=tokens,
            task_id=stage_task_id,
        )

    error_msg = f"Stage exited {return_code}"
    if not reconcile_result.ok:
        error_msg += f"; reconcile: {reconcile_result.summary}"

    return _make_result(
        stage, StageOutcome.FAILURE, duration, return_code,
        error=error_msg, cost=cost, tokens_used=tokens,
        task_id=stage_task_id,
    )


def _build_validation_feedback(validation_errors: list[str]) -> str:
    """Build a follow-up prompt with validation error feedback.

    Tells the LLM which tasks failed validation and why, so it can
    fix them in the same session (reusing cached context).
    """
    error_list = "\n".join(f"- {e}" for e in validation_errors)
    return f"""The harness rejected some of your tasks because they failed validation.

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
- `grep -c "class GlobalConfig" app/ralph/config.py` returns 1 (specific pattern in specific file)

Please output a corrected [RALPH_OUTPUT] block with the fixed tasks.
Only include the tasks that failed — do not repeat tasks that already passed.
"""


def _validate_config(
    config: dict, args_spec: Optional[str] = None
) -> Tuple[Optional[Path], Optional[Path], Optional[str]]:
    """Validate and extract paths from config dict.

    Returns:
        Tuple of (repo_root, ralph_dir, error_message).
    """
    repo_root: Optional[Path] = config.get("repo_root")
    ralph_dir: Optional[Path] = config.get("ralph_dir")

    if not ralph_dir or not ralph_dir.exists():
        if args_spec:
            # If spec is provided, initialize directory
            cmd_init()
            repo_root = Path.cwd()
            global_config = GlobalConfig.load()
            ralph_dir = repo_root / global_config.ralph_dir
            config["repo_root"] = repo_root
            config["ralph_dir"] = ralph_dir
        else:
            return (
                None,
                None,
                "Ralph not initialized. Run 'ralph init' or 'ralph plan' first.",
            )
    if not repo_root or not ralph_dir:
        return (
            None,
            None,
            "Invalid configuration: missing repo_root or ralph_dir.",
        )
    return repo_root, ralph_dir, None


def _print_construct_header(
    state: RalphState,
    branch: str,
    rules_source: Optional[str],
    config: GlobalConfig,
    max_iterations: int,
    max_cost: float,
    max_failures: int,
    stage_timeout_ms: int,
    context_limit: int,
    tix: Optional[Tix] = None,
) -> None:
    """Print the construct mode header with full configuration."""
    warn_pct = getattr(config, "context_warn_pct", 70)
    compact_pct = getattr(config, "context_compact_pct", 85)
    kill_pct = getattr(config, "context_kill_pct", 95)

    soft_limit = int(context_limit * warn_pct / 100)
    compact_limit = int(context_limit * compact_pct / 100)
    hard_limit = int(context_limit * kill_pct / 100)

    # Get ticket counts from tix
    pending_count = 0
    issue_count = 0
    if tix:
        try:
            pending_count = len(tix.query_tasks())
            issue_count = len(tix.query_issues())
        except Exception:
            pass

    print(f"{Colors.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
    print(f"Mode:   {Colors.GREEN}construct{Colors.NC} (state machine)")
    print(f"Spec:   {Colors.CYAN}{state.spec}{Colors.NC}")
    print(f"Branch: {branch}")
    if rules_source:
        print(f"Rules:  {Colors.GREEN}{rules_source}{Colors.NC}")
    else:
        print(f"Rules:  {Colors.YELLOW}None{Colors.NC}")
    print(f"Model:  {config.model or 'default'}")
    # Show per-stage overrides if any differ from default
    stage_overrides = []
    for stage_name in ("build", "verify", "investigate", "decompose", "plan"):
        stage_model = config.model_for_stage(stage_name)
        if stage_model and stage_model != config.model:
            stage_overrides.append(f"{stage_name}={stage_model}")
    if stage_overrides:
        print(f"Routes: {', '.join(stage_overrides)}")
    if max_iterations > 0:
        print(f"Max iterations: {max_iterations}")
    if max_cost > 0:
        print(f"Max cost:       ${max_cost}")
    print(f"Max failures:   {max_failures} (circuit breaker)")
    print(f"Timeout:        {stage_timeout_ms}ms per stage")
    print(f"Context:        {context_limit:,} tokens (warn: {soft_limit:,}, compact: {compact_limit:,}, kill: {hard_limit:,})")
    # Guard limits
    guard_parts = []
    if config.max_tokens > 0:
        guard_parts.append(f"tokens: {config.max_tokens:,}")
    if config.max_wall_time_s > 0:
        guard_parts.append(f"wall: {config.max_wall_time_s}s")
    if config.max_api_calls > 0:
        guard_parts.append(f"api: {config.max_api_calls}")
    if guard_parts:
        print(f"Guards:         {', '.join(guard_parts)}")
    print(f"Pending tasks:  {pending_count}")
    print(f"Open issues:    {issue_count}")
    print(f"{Colors.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")


def _run_acceptance_precheck(
    tix: TixProtocol,
    repo_root: Path,
    timeout_seconds: int = 60,
) -> int:
    """Run acceptance criteria for done tasks before spawning VERIFY agent.

    For each done task whose `accept` field looks like a shell command,
    run it in a subprocess. If it exits 0, auto-accept the task via tix.
    Tasks without a runnable accept command are left for the agent.

    Args:
        tix: Tix-compatible instance.
        repo_root: Repository root for subprocess cwd.
        timeout_seconds: Max seconds per acceptance command.

    Returns:
        Number of tasks auto-accepted.
    """
    try:
        done_tasks = tix.query_done_tasks()
    except TixError:
        return 0

    accepted = 0
    for task in done_tasks:
        accept = task.get("accept", "").strip()
        task_id = task.get("id", "")
        if not accept or not task_id:
            continue

        # Heuristic: skip non-command acceptance criteria
        # (e.g., "works correctly" is not runnable)
        if not _looks_like_command(accept):
            continue

        try:
            result = subprocess.run(
                accept,
                shell=True,
                capture_output=True,
                cwd=repo_root,
                timeout=timeout_seconds,
            )
            if result.returncode == 0:
                tix.task_accept(task_id)
                print(f"  Pre-check: {task_id} auto-accepted")
                accepted += 1
        except (subprocess.TimeoutExpired, OSError):
            pass  # Leave for agent

    return accepted


def _looks_like_command(text: str) -> bool:
    """Heuristic: does this acceptance criteria look like a shell command?

    Returns True if the text starts with a known command prefix or contains
    shell-like patterns. Returns False for prose-like descriptions.
    """
    text = text.strip()
    # Common command prefixes
    cmd_prefixes = (
        "make", "pytest", "python", "python3", "go ", "cargo", "npm ", "yarn ",
        "grep ", "test ", "./", "bash ", "sh ", "echo ", "cat ",
        "git ", "curl ", "gcc ", "g++", "clang",
        "cd ", "ls ", "find ", "wc ", "diff ", "head ", "tail ",
        "docker ", "cmake ", "ninja ", "meson ",
    )
    first_line = text.split("\n")[0].strip()
    lower = first_line.lower()

    if any(lower.startswith(p) for p in cmd_prefixes):
        return True

    # Shell operators suggest a command
    if any(op in first_line for op in ("|", "&&", ">>", " > ", " 2>")):
        return True

    # python -c "..." or python3 -m ... patterns
    if "python" in lower and ("-c " in lower or "-m " in lower):
        return True

    # Inline commands: `from X import Y` (backtick-wrapped)
    if first_line.startswith("`") and first_line.endswith("`"):
        return True

    return False


def _run_format_command(
    command: str,
    repo_root: Path,
    timeout_seconds: int = 120,
) -> bool:
    """Run the configured format/lint command after BUILD.

    Executes the command in the repo root. If it modifies files
    (e.g. clang-format -i), those changes are auto-staged.
    If it fails, logs a warning but does not block the pipeline.

    Args:
        command: Shell command to run (e.g. "clang-format -i src/*.c").
        repo_root: Repository root for subprocess cwd.
        timeout_seconds: Max seconds for the command.

    Returns:
        True if the command succeeded (exit 0), False otherwise.
    """
    print(f"  Format: running '{command}'")
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if stderr:
                # Truncate long output
                if len(stderr) > 500:
                    stderr = stderr[:497] + "..."
                print(f"  Format: FAILED (exit {result.returncode})")
                print(f"  {stderr}")
            else:
                print(f"  Format: FAILED (exit {result.returncode})")
            return False
        print("  Format: OK")
        return True
    except subprocess.TimeoutExpired:
        print(f"  Format: TIMEOUT ({timeout_seconds}s)")
        return False
    except OSError as e:
        print(f"  Format: ERROR ({e})")
        return False


def _accumulate_commit_info(
    info: IterationCommitInfo,
    reconcile: ReconcileResult,
    tix: Optional[Tix],
    repo_root: Path,
) -> None:
    """Populate commit info from a reconcile result.

    Resolves task IDs to human-readable names via the plan file,
    and records accept/reject verdicts with reasons.

    Args:
        info: Mutable commit info to accumulate into.
        reconcile: Reconcile result from the latest stage.
        tix: Tix instance for plan file access.
        repo_root: Repository root for plan file path.
    """
    # Collect all task IDs that need name resolution
    all_ids = (
        reconcile.tasks_accepted
        + reconcile.tasks_rejected
        + reconcile.tasks_added
    )
    if not all_ids:
        return

    # Resolve names from plan file
    plan_file = repo_root / ".tix" / "plan.jsonl"
    names = lookup_task_names(plan_file, all_ids)

    # Record verdicts
    for task_id in reconcile.tasks_accepted:
        name = names.get(task_id, task_id)
        info.verdicts.append(
            TaskVerdict(task_id=task_id, name=name, accepted=True)
        )

    for task_id in reconcile.tasks_rejected:
        name = names.get(task_id, task_id)
        reason = _lookup_reject_reason(plan_file, task_id)
        info.verdicts.append(
            TaskVerdict(
                task_id=task_id, name=name, accepted=False,
                reason=reason,
            )
        )

    # Record new tasks
    info.tasks_added.extend(reconcile.tasks_added)
    info.issues_added.extend(reconcile.issues_added)


def _lookup_reject_reason(plan_file: Path, task_id: str) -> str:
    """Find the most recent rejection reason for a task from plan.jsonl.

    Args:
        plan_file: Path to .tix/plan.jsonl.
        task_id: Task ID to look up.

    Returns:
        Rejection reason string, or empty string if not found.
    """
    if not plan_file.exists():
        return ""

    reason = ""
    try:
        for line in plan_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                entry.get("t") == "reject"
                and entry.get("id") == task_id
            ):
                reason = entry.get("reason", "")
    except OSError:
        pass
    return reason


def _create_stage_wrapper(
    repo_root: Path,
    ralph_dir: Path,
    project_rules: Optional[str] = None,
    tix_instance: Optional[Tix] = None,
    run_id: str = "",
    log_dir: Optional[Path] = None,
) -> Callable:
    """Create a stage wrapper function for the state machine."""
    if tix_instance is None:
        raise RuntimeError("Tix is required for construct mode")

    # Mutable container for stage breakdown accumulation
    _stage_breakdowns: dict[str, StageBreakdown] = {}

    # Accumulates reconcile results across stages for descriptive commits.
    # Reset after each commit by the construct loop.
    _commit_info = IterationCommitInfo()

    def get_stage_breakdowns() -> dict[str, StageBreakdown]:
        """Return accumulated stage breakdowns (for run record)."""
        return _stage_breakdowns

    def get_commit_info() -> IterationCommitInfo:
        """Return the accumulated commit info for this cycle."""
        return _commit_info

    def run_stage_wrapper(
        cfg: GlobalConfig,
        stage: Stage,
        st: RalphState,
        met: Metrics,
        timeout_ms: int,
        ctx_limit: int,
    ) -> StageResult:
        print(f"\n{Colors.CYAN}[{stage.name}]{Colors.NC}")

        # Track API call type before execution
        stage_name_lower = stage.name.lower()
        is_local = cfg.is_stage_local(stage_name_lower)
        stage_model = cfg.model_for_stage(stage_name_lower)

        # Pre-check: auto-accept done tasks whose acceptance criteria pass
        precheck_accepted = 0
        if stage == Stage.VERIFY:
            accepted = _run_acceptance_precheck(tix_instance, repo_root)
            if accepted > 0:
                met.tasks_completed += accepted
                precheck_accepted = accepted
                print(f"  Pre-check: {accepted} task(s) auto-accepted")
                # Check if there are still done tasks needing agent review
                try:
                    remaining = tix_instance.query_done_tasks()
                    if not remaining:
                        print("  All done tasks passed pre-check — skipping agent")
                        return _make_result(stage, StageOutcome.SUCCESS)
                except TixError:
                    pass

        iter_start = time.time()
        cost_before = met.total_cost
        tokens_in_before = met.total_tokens_in
        tokens_cached_before = met.total_tokens_cached
        tokens_out_before = met.total_tokens_out
        validation_retries_before = met.validation_retries

        result = _run_stage(
            cfg, stage, st, met, timeout_ms,
            repo_root, ralph_dir, project_rules,
            True, tix_instance, iter_start,
            run_id=run_id,
        )

        iter_duration = time.time() - iter_start

        # Track API call
        if is_local:
            met.api_calls_local += 1
        else:
            met.api_calls_remote += 1

        # Post-BUILD: run format command if configured
        if stage == Stage.BUILD and result.outcome == StageOutcome.SUCCESS:
            fmt_cmd = getattr(cfg, "format_command", "")
            if fmt_cmd:
                _run_format_command(fmt_cmd, repo_root)

        # Post-BUILD: try auto-accepting the task immediately
        post_accepted = 0
        if stage == Stage.BUILD and result.outcome == StageOutcome.SUCCESS:
            post_accepted = _run_acceptance_precheck(tix_instance, repo_root)
            if post_accepted > 0:
                met.tasks_completed += post_accepted
                precheck_accepted += post_accepted
                print(f"  Post-BUILD pre-check: {post_accepted} task(s) auto-accepted")

        # Calculate deltas for this iteration
        cost_delta = met.total_cost - cost_before
        tokens_in_delta = met.total_tokens_in - tokens_in_before
        tokens_cached_delta = met.total_tokens_cached - tokens_cached_before
        tokens_out_delta = met.total_tokens_out - tokens_out_before

        # Capture reconcile result for iteration record
        reconcile = _last_reconcile_result.get("result")
        _last_reconcile_result["result"] = None  # Reset for next iteration

        # Accumulate into commit info for descriptive commit messages
        _commit_info.stages_run.append(stage.name)
        if reconcile:
            _accumulate_commit_info(
                _commit_info, reconcile, tix_instance, repo_root,
            )

        # Emit iteration record to ledger
        validation_retries_delta = met.validation_retries - validation_retries_before
        if run_id and log_dir:
            iter_record = IterationRecord(
                run_id=run_id,
                iteration=met.total_iterations,
                stage=stage.name,
                model=stage_model or "",
                is_local=is_local,
                task_id=result.task_id or "",
                cost=cost_delta,
                tokens=TokenBreakdown(
                    input=tokens_in_delta,
                    cached=tokens_cached_delta,
                    output=tokens_out_delta,
                ),
                duration_s=iter_duration,
                outcome=result.outcome.name.lower(),
                precheck_accepted=precheck_accepted > 0,
                validation_retries=validation_retries_delta,
                kill_reason=getattr(result, "kill_reason", None),
                tasks_added=len(reconcile.tasks_added) if reconcile else 0,
                tasks_accepted=(
                    len(reconcile.tasks_accepted) + precheck_accepted
                    if reconcile else precheck_accepted
                ),
                tasks_rejected=len(reconcile.tasks_rejected) if reconcile else 0,
                issues_added=len(reconcile.issues_added) if reconcile else 0,
            )
            try:
                write_iteration(log_dir, iter_record)
            except OSError:
                pass  # Don't crash on ledger write failure

        # Accumulate stage breakdown
        sname = stage.name
        if sname not in _stage_breakdowns:
            _stage_breakdowns[sname] = StageBreakdown()
        bd = _stage_breakdowns[sname]
        bd.count += 1
        bd.cost += cost_delta
        if is_local:
            bd.api_calls_local += 1
        else:
            bd.api_calls_remote += 1

        return result

    # Attach accessors as attributes
    run_stage_wrapper.get_stage_breakdowns = get_stage_breakdowns  # type: ignore[attr-defined]
    run_stage_wrapper.get_commit_info = get_commit_info  # type: ignore[attr-defined]
    return run_stage_wrapper


def _emit_session_summary(
    metrics: Metrics,
    exit_reason: str,
    spec: str,
    config: GlobalConfig,
    log_dir: Path,
    tix: Optional[Tix] = None,
) -> None:
    """Write session summary JSON to log directory.

    Enriches the summary with per-model and per-stage breakdowns from
    tix, so the JSON is useful for cross-session analysis.
    """
    if not getattr(config, "emit_session_summary", True):
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    ended_at = datetime.now().isoformat()
    summary = SessionSummary.from_metrics(
        metrics=metrics,
        exit_reason=exit_reason,
        spec=spec,
        profile=getattr(config, "profile", "default"),
        ended_at=ended_at,
    )

    summary_dict = summary.to_dict()

    # Enrich with tix-sourced breakdowns
    if tix:
        try:
            summary_dict["models"] = tix.report_models()
        except Exception:
            pass
        try:
            summary_dict["labels"] = tix.report_labels()
        except Exception:
            pass

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_file = log_dir / f"session_{timestamp}.json"
    try:
        with open(summary_file, "w") as f:
            json.dump(summary_dict, f, indent=2)
        print(f"{Colors.CYAN}Session summary: {summary_file}{Colors.NC}")
    except OSError as e:
        print(f"{Colors.YELLOW}Failed to write session summary: {e}{Colors.NC}")


def _build_iteration_header(
    metrics: Metrics,
    max_cost: float,
    config: GlobalConfig,
    session_start_time: float,
) -> str:
    """Build the status suffix for iteration header lines.

    Shows cost, API calls, and elapsed wall time alongside each
    iteration banner.

    Args:
        metrics: Current session metrics.
        max_cost: Cost cap (0 = unlimited).
        config: Global config with guard limits.
        session_start_time: Unix timestamp of session start.

    Returns:
        Formatted string like " | Cost: $0.12 | API: 5r/2l | 12m30s"
    """
    parts = []

    # Cost
    if max_cost > 0:
        parts.append(f"Cost: ${metrics.total_cost:.4f}/${max_cost}")
    else:
        parts.append(f"Cost: ${metrics.total_cost:.4f}")

    # API calls (only if any have been made)
    total_api = metrics.api_calls_remote + metrics.api_calls_local
    if total_api > 0:
        parts.append(f"API: {metrics.api_calls_remote}r/{metrics.api_calls_local}l")

    # Wall time
    elapsed = time.time() - session_start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    parts.append(f"{minutes}m{seconds:02d}s")

    return " | " + " | ".join(parts)


def _print_extended_metrics(metrics: Metrics) -> None:
    """Print API call and token breakdown details.

    Shows remote vs local API calls, cached token ratio,
    and wall time when available.
    """
    total_api = metrics.api_calls_remote + metrics.api_calls_local
    if total_api > 0:
        print(f"API calls:      {total_api} "
              f"({metrics.api_calls_remote} remote, "
              f"{metrics.api_calls_local} local)")
    if metrics.total_tokens_cached > 0:
        cache_pct = (metrics.total_tokens_cached /
                     max(metrics.tokens_used, 1)) * 100
        print(f"Token split:    {metrics.total_tokens_in:,} in / "
              f"{metrics.total_tokens_cached:,} cached ({cache_pct:.0f}%) / "
              f"{metrics.total_tokens_out:,} out")


def _print_final_report(
    metrics: Metrics,
    exit_reason: str,
    iterations: int,
    state: RalphState,
    tix: Optional[Tix] = None,
) -> None:
    """Print final construct session report.

    Uses ``tix report`` for the summary (completion %, avg cost, cycle
    time, retries, kills, top model) and ``tix report models`` for
    per-model breakdown when multiple models were used.
    Falls back to basic Python metrics if tix report is unavailable.
    """
    print()
    _exit_colors = {
        "complete": Colors.GREEN,
        "circuit_breaker": Colors.RED,
        "cost_limit": Colors.YELLOW,
        "max_iterations": Colors.YELLOW,
        "token_limit": Colors.YELLOW,
        "wall_time_limit": Colors.YELLOW,
        "api_call_limit": Colors.YELLOW,
        "progress_stall": Colors.RED,
        "loop_detected": Colors.RED,
        "no_work": Colors.GREEN,
        "git_conflict": Colors.RED,
        "interrupted": Colors.YELLOW,
    }
    _exit_labels = {
        "complete": f"SPEC COMPLETE: {state.spec}",
        "circuit_breaker": "CIRCUIT BREAKER TRIPPED",
        "cost_limit": "COST LIMIT REACHED",
        "max_iterations": "MAX ITERATIONS REACHED",
        "token_limit": "TOKEN BUDGET EXHAUSTED",
        "wall_time_limit": "WALL TIME LIMIT REACHED",
        "api_call_limit": "API CALL LIMIT REACHED",
        "progress_stall": "PROGRESS STALLED — ABORTING",
        "loop_detected": "LOOP DETECTED — ABORTING",
        "no_work": "NO REMAINING WORK",
        "git_conflict": "GIT CONFLICT DETECTED",
        "interrupted": "INTERRUPTED BY USER",
    }
    color = _exit_colors.get(exit_reason, Colors.BLUE)
    label = _exit_labels.get(exit_reason, exit_reason.upper())
    print(f"{color}{'━' * 40}{Colors.NC}")
    print(f"{color}{label}{Colors.NC}")
    print(f"Iterations:     {iterations}")

    # Use tix progress report + Ralph-side velocity/models queries
    tix_report_shown = False
    if tix:
        try:
            report_text = tix.report()
            if report_text.strip():
                print()
                print(report_text)
                tix_report_shown = True
        except Exception:
            pass

        # Ralph-owned velocity summary from TQL
        try:
            velocity = tix.report_velocity()
            if velocity:
                v = velocity[0]
                count = v.get("count", 0)
                if count:
                    total_cost = v.get("sum_meta.cost", 0.0)
                    avg_cost = v.get("avg_meta.cost", 0.0)
                    tok_in = v.get("sum_meta.tokens_in", 0)
                    tok_out = v.get("sum_meta.tokens_out", 0)
                    retries = v.get("sum_meta.retries", 0)
                    kills = v.get("sum_meta.kill_count", 0)
                    print(f"\nCost: ${total_cost:.4f} total, "
                          f"${avg_cost:.4f}/task avg")
                    if tok_in or tok_out:
                        print(f"Tokens: {tok_in} in / {tok_out} out")
                    parts = []
                    if retries:
                        parts.append(f"Retries: {retries}")
                    if kills:
                        parts.append(f"Kills: {kills}")
                    if parts:
                        print(" | ".join(parts))
        except Exception:
            pass

        # Ralph-owned per-model breakdown from TQL
        try:
            models = tix.report_models()
            if models and len(models) > 1:
                print("\nPer-model breakdown:")
                for m in models:
                    name = m.get("meta.model", "?")
                    cnt = m.get("count", 0)
                    cost = m.get("sum_meta.cost", 0.0)
                    print(f"  {name}: {cnt} tasks, ${cost:.4f}")
        except Exception:
            pass

    # Fallback to basic metrics if tix report unavailable
    if not tix_report_shown:
        print(f"Total cost:     ${metrics.total_cost:.4f}")
        print(f"Tokens used:    {metrics.tokens_used:,}")

    # Always show API calls and token breakdown
    _print_extended_metrics(metrics)

    print(f"{Colors.BLUE}{'━' * 40}{Colors.NC}")


def _write_run_record(
    run_id: str,
    log_dir: Path,
    cwd: Path,
    state: RalphState,
    branch: str,
    global_config: GlobalConfig,
    metrics: Metrics,
    exit_reason: str,
    iteration: int,
    git_sha_start: str,
    session_start_time: float,
    stage_wrapper: Callable,
    tix: Optional[TixProtocol] = None,
) -> None:
    """Build and write a RunRecord to the ledger.

    Args:
        run_id: Unique run identifier.
        log_dir: Directory for ledger files.
        cwd: Current working directory.
        state: Current Ralph state.
        branch: Git branch name.
        global_config: Global config for snapshot.
        metrics: Session metrics.
        exit_reason: Why the session ended.
        iteration: Final iteration count.
        git_sha_start: Commit hash at session start.
        session_start_time: Unix timestamp of session start.
        stage_wrapper: Wrapper function with get_stage_breakdowns attribute.
        tix: Optional tix instance for task count queries.
    """
    git_sha_end = get_current_commit(cwd)
    worktree = _get_worktree_root(cwd)
    duration = time.time() - session_start_time

    # Get stage breakdowns from wrapper
    breakdowns: dict[str, StageBreakdown] = {}
    get_bd = getattr(stage_wrapper, "get_stage_breakdowns", None)
    if callable(get_bd):
        result = get_bd()
        if isinstance(result, dict):
            breakdowns = result

    # Query tix for task counts (best-effort)
    tasks_total = 0
    tasks_failed = 0
    retries_task = 0
    if tix:
        try:
            full = tix.query_full()
            pending = full.get("tasks", {}).get("pending", [])
            done = full.get("tasks", {}).get("done", [])
            tombstones = full.get("tombstones", {})
            accepted = tombstones.get("accepted", [])
            rejected = tombstones.get("rejected", [])
            tasks_total = len(pending) + len(done) + len(accepted) + len(rejected)
            tasks_failed = len(rejected)
        except Exception:
            pass

    # Sum retries from module-level reject counter
    from ..reconcile import _reject_counts
    retries_task = sum(_reject_counts.values())

    run_record = RunRecord(
        run_id=run_id,
        spec=state.spec or "",
        branch=branch,
        git_sha_start=git_sha_start,
        git_sha_end=git_sha_end,
        worktree=worktree,
        profile=getattr(global_config, "profile", "default"),
        config_snapshot=config_snapshot(global_config),
        started_at=metrics.started_at or "",
        ended_at=datetime.now().isoformat(),
        duration_s=duration,
        exit_reason=exit_reason,
        iterations=iteration,
        tasks_total=tasks_total,
        tasks_completed=metrics.tasks_completed,
        tasks_failed=tasks_failed,
        cost=metrics.total_cost,
        tokens=TokenBreakdown(
            input=metrics.total_tokens_in,
            cached=metrics.total_tokens_cached,
            output=metrics.total_tokens_out,
        ),
        api_calls_remote=metrics.api_calls_remote,
        api_calls_local=metrics.api_calls_local,
        kills_timeout=metrics.kills_timeout,
        kills_context=metrics.kills_context,
        kills_loop=metrics.kills_loop,
        retries_validation=metrics.validation_retries,
        retries_task=retries_task,
        stages=breakdowns,
    )
    try:
        write_run(log_dir, run_record)
    except OSError:
        pass  # Don't crash on ledger write failure


def _get_spec_from_args(args: argparse.Namespace) -> Optional[str]:
    """Extract spec from args if present."""
    return args.spec if hasattr(args, "spec") else None


def cmd_construct(
    config: dict,
    iterations: int,
    args: argparse.Namespace,
    max_cost: float = 0.0,
    max_failures: int = DEFAULT_MAX_FAILURES,
) -> int:
    """Construct mode - main autonomous development loop.
    
    Args:
        config: Configuration dict with paths.
        iterations: Maximum iterations (0 for unlimited).
        args: Command-line arguments.
        max_cost: Maximum cost limit (0 for unlimited).
        max_failures: Circuit breaker threshold.
    
    Returns:
        Exit code (0 for success, 1 for failure).
    """
    cwd = Path.cwd()
    spec = _get_spec_from_args(args)
    repo_root_opt, ralph_dir_opt, error = _validate_config(config, spec)

    if error or not repo_root_opt or not ralph_dir_opt:
        print(f"{Colors.RED}{error or 'Invalid configuration'}{Colors.NC}")
        return 1

    repo_root, ralph_dir = repo_root_opt, ralph_dir_opt
    
    # Pre-flight check: validate opencode
    opencode_ok, opencode_error = _check_opencode_available()
    if not opencode_ok:
        print(f"{Colors.RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
        print(f"{Colors.RED}OPENCODE NOT AVAILABLE{Colors.NC}")
        print(f"{opencode_error}")
        print(f"{Colors.RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
        return 1
    
    # Load state
    state = load_state(repo_root)
    if spec and not state.spec:
        state.spec = spec
        save_state(state, repo_root)
    
    if not state.spec:
        print(f"{Colors.YELLOW}No spec configured - run 'ralph plan <spec.md>' first{Colors.NC}")
        return 1
    
    # Load global config with per-repo overlay
    repo_config = ralph_dir / "config.toml"
    global_config = GlobalConfig.load(repo_config=repo_config)
    max_iterations = iterations if iterations > 0 else global_config.max_iterations
    stage_timeout_ms = global_config.stage_timeout_ms
    context_limit = global_config.context_window
    
    # Get branch info
    branch = get_current_branch(cwd)
    
    # Load project rules
    project_rules = find_project_rules(cwd)
    rules_source = None
    if project_rules:
        for candidate in ["AGENTS.md", "CLAUDE.md"]:
            if (cwd / candidate).exists():
                rules_source = candidate
                break

    # Initialize tix harness (required)
    try:
        tix_instance = Tix(repo_root)
        if not tix_instance.is_available():
            print(f"{Colors.RED}Tix not available. Install tix first.{Colors.NC}")
            return 1
        print(f"Tix:    {Colors.GREEN}available{Colors.NC} ({tix_instance.bin})")
    except Exception as e:
        print(f"{Colors.RED}Tix init failed: {e}{Colors.NC}")
        return 1

    # Print header
    _print_construct_header(
        state, branch, rules_source, global_config,
        max_iterations, max_cost, max_failures,
        stage_timeout_ms, context_limit, tix_instance,
    )

    # Initialize metrics with start time
    metrics = Metrics()
    metrics.started_at = datetime.now().isoformat()
    metrics.record_progress()

    # Initialize loop detector if configured
    loop_threshold = getattr(global_config, "loop_detection_threshold", 3)
    loop_detector = LoopDetector(threshold=loop_threshold) if loop_threshold > 0 else None

    # Ledger setup — must be before state machine so wrapper can emit records
    run_id = _generate_run_id()
    log_dir = Path(global_config.log_dir)
    git_sha_start = get_current_commit(cwd)
    session_start_time = time.time()

    # Create state machine
    stage_wrapper = _create_stage_wrapper(
        repo_root, ralph_dir, project_rules, tix_instance,
        run_id=run_id, log_dir=log_dir,
    )

    # LLM dedup callback: called after INVESTIGATE to remove duplicate tasks.
    def _dedup_callback() -> int:
        def llm_fn(prompt: str) -> Optional[str]:
            model = global_config.model_for_stage("investigate")
            proc = spawn_opencode(
                prompt, cwd=repo_root,
                timeout=stage_timeout_ms, model=model,
            )
            result = stream_and_collect(
                proc, stage_timeout_ms // 1000, print_output=False
            )
            return result.raw_output if result.return_code == 0 else None

        count = dedup_tasks(tix_instance, llm_fn)
        if count > 0:
            print(f"  Task dedup: removed {count} duplicate(s)")
        return count

    state_machine = ConstructStateMachine(
        config=global_config,
        metrics=metrics,
        stage_timeout_ms=stage_timeout_ms,
        context_limit=context_limit,
        run_stage_fn=stage_wrapper,
        load_state_fn=lambda: load_state(repo_root),
        save_state_fn=lambda st: save_state(st, repo_root),
        tix=tix_instance,
        loop_detector=loop_detector,
        dedup_fn=_dedup_callback,
    )

    # Run construct loop
    iteration = 0
    exit_reason = "unknown"
    
    try:
        while True:
            # Check iteration limit
            if max_iterations > 0 and iteration >= max_iterations:
                exit_reason = "max_iterations"
                break
            
            # Check cost limit
            if max_cost > 0 and metrics.total_cost >= max_cost:
                exit_reason = "cost_limit"
                break

            # Check token budget
            max_tokens = getattr(global_config, "max_tokens", 0)
            if max_tokens > 0 and metrics.tokens_used >= max_tokens:
                exit_reason = "token_limit"
                break

            # Check wall clock limit
            max_wall = getattr(global_config, "max_wall_time_s", 3600)
            if max_wall > 0:
                elapsed = time.time() - session_start_time
                if elapsed >= max_wall:
                    exit_reason = "wall_time_limit"
                    break

            # Check API call limit
            max_api = getattr(global_config, "max_api_calls", 0)
            if max_api > 0 and metrics.api_calls_remote >= max_api:
                exit_reason = "api_call_limit"
                break

            # Check progress stall (hard abort)
            stall_abort = getattr(global_config, "progress_stall_abort_s", 1200)
            if stall_abort > 0 and metrics.last_progress_time > 0:
                stall = metrics.seconds_since_progress()
                if stall >= stall_abort:
                    exit_reason = "progress_stall"
                    break
            
            iteration += 1
            metrics.total_iterations = iteration
            
            # Sync with remote before each iteration
            plan_file = tix_instance.plan_file()
            sync_result = sync_with_remote(branch, plan_file, cwd)
            if sync_result == "conflict":
                print(f"{Colors.RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
                print(f"{Colors.RED}GIT CONFLICT DETECTED{Colors.NC}")
                print(f"Another Ralph instance made conflicting changes.")
                print(f"{Colors.RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
                exit_reason = "git_conflict"
                break
            elif sync_result == "updated":
                print(f"{Colors.CYAN}Synced with remote - reloading state{Colors.NC}")
                state = load_state(repo_root)
            
            # Print iteration header
            header_parts = _build_iteration_header(
                metrics, max_cost, global_config, session_start_time,
            )
            
            print()
            print(f"{Colors.GREEN}╔═══════════════════════════════════════════════════════════════╗{Colors.NC}")
            print(f"{Colors.GREEN}║  ITERATION {iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{header_parts}{Colors.NC}")
            print(f"{Colors.GREEN}╚═══════════════════════════════════════════════════════════════╝{Colors.NC}")
            
            # Run one iteration
            should_continue, spec_complete = state_machine.run_iteration(iteration)
            
            if spec_complete:
                exit_reason = "complete"
                break
            
            if not should_continue:
                exit_reason = "no_work"
                break
            
            # Check for loop detection
            if metrics.kills_loop > 0:
                exit_reason = "loop_detected"
                break
            
            # Commit with descriptive message (code + tix state)
            commit_info = stage_wrapper.get_commit_info()  # type: ignore[attr-defined]
            commit_info.iteration = iteration
            commit_info.spec = load_state(repo_root).spec or ""
            if commit_iteration(commit_info, cwd):
                metrics.commits_made += 1
            commit_info.reset(iteration)
            
            # Push changes with retry
            plan_file = tix_instance.plan_file()
            if not push_with_retry(branch, retries=2, plan_file=plan_file, cwd=cwd):
                print(f"{Colors.YELLOW}Push failed - continuing without push{Colors.NC}")

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted by user{Colors.NC}")
        exit_reason = "interrupted"
    
    finally:
        # Reload final state
        state = load_state(repo_root)
        
        # Print final report
        _print_final_report(metrics, exit_reason, iteration, state, tix_instance)
        
        # Emit session summary
        _emit_session_summary(
            metrics, exit_reason, state.spec or "", global_config, log_dir,
            tix=tix_instance,
        )

        # Write run record to ledger
        _write_run_record(
            run_id, log_dir, cwd, state, branch, global_config,
            metrics, exit_reason, iteration, git_sha_start,
            session_start_time, stage_wrapper, tix=tix_instance,
        )
    
    return 0 if exit_reason in ("complete", "no_work", "max_iterations") else 1
