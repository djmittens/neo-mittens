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
from typing import Optional, Tuple, Callable

from ..config import GlobalConfig
from ..context import Metrics, LoopDetector, SessionSummary, context_pressure
from ..git import (
    get_current_branch,
    has_uncommitted_tix,
    push_with_retry,
    sync_with_remote,
)
from ..opencode import spawn_opencode, stream_and_collect
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
) -> Tuple[Optional[str], Optional[dict]]:
    """Build a prompt for a stage using tix for ticket data.
    
    Returns:
        Tuple of (prompt_string, context_metadata) where context_metadata
        contains stage-specific info needed for reconciliation (e.g. task_id).
        Returns (None, None) if stage cannot be built.
    """
    stage_name = stage.name.lower()
    spec_name = state.spec or ""
    meta: dict = {}
    spec_content = _load_spec_content(ralph_dir, spec_name)
    
    if stage == Stage.BUILD:
        tasks = tix.query_tasks()
        if not tasks:
            return None, None
        task = _pick_best_task(tasks)
        context = build_build_context(task, spec_name, spec_content)
        meta["task_id"] = task.get("id", "")
    elif stage == Stage.VERIFY:
        full = tix.query_full()
        done = full.get("tasks", {}).get("done", [])
        if not done:
            return None, None
        context = build_verify_context(done, spec_name, spec_content)
    elif stage == Stage.INVESTIGATE:
        issues = tix.query_issues()
        if not issues:
            return None, None
        # Filter to batch items if batching is active
        batch_ids = list(state.batch_items) if state.batch_items else None
        if batch_ids:
            issues = [i for i in issues if i.get("id") in batch_ids]
            meta["batch_issue_ids"] = batch_ids
        else:
            meta["batch_issue_ids"] = [i.get("id", "") for i in issues]
        context = build_investigate_context(issues, spec_name, spec_content)
    elif stage == Stage.DECOMPOSE:
        # Find killed task from state's decompose_target
        target_id = state.decompose_target
        if not target_id:
            return None, None
        full = tix.query_full()
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
    if stage == Stage.BUILD:
        return reconcile_build(
            tix, agent_output, meta.get("task_id", ""),
            stage_metrics=sm,
        )
    elif stage == Stage.VERIFY:
        return reconcile_verify(tix, agent_output, stage_metrics=sm)
    elif stage == Stage.INVESTIGATE:
        return reconcile_investigate(
            tix, agent_output, meta.get("batch_issue_ids"),
            stage_metrics=sm,
        )
    elif stage == Stage.DECOMPOSE:
        return reconcile_decompose(
            tix, agent_output, meta.get("task_id", ""),
            parent_depth=meta.get("parent_depth", 0),
            stage_metrics=sm,
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
    )


def _execute_opencode(
    config: GlobalConfig,
    prompt: str,
    repo_root: Path,
    stage_timeout_ms: int,
    print_output: bool = True,
    stage_name: str = "",
) -> Tuple[int, str, bool, float, int, int, int]:
    """Execute opencode with real-time streaming output.
    
    Returns:
        Tuple of (return_code, output, timed_out, cost, tokens_in,
                  tokens_out, iterations).
    """
    model = config.model_for_stage(stage_name) if stage_name else config.model
    proc = spawn_opencode(prompt, cwd=repo_root, timeout=stage_timeout_ms, model=model)
    
    timeout_seconds = stage_timeout_ms // 1000
    return_code, stdout_output, timed_out, metrics = stream_and_collect(
        proc, timeout_seconds, print_output=print_output
    )
    
    return (return_code, stdout_output, timed_out, metrics.total_cost,
            metrics.total_tokens_in, metrics.total_tokens_out,
            metrics.total_iterations)


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
) -> StageResult:
    """Run a stage using tix for ticket data and reconcile after."""
    prompt, meta = _build_stage_prompt_tix(
        stage, tix, state, ralph_dir, project_rules, config
    )
    if not prompt or meta is None:
        return _make_result(
            stage, StageOutcome.SKIP,
            error=f"No prompt for {stage.name}",
        )

    try:
        (return_code, stdout_output, timed_out, cost,
         tokens_in, tokens_out, stage_iters) = _execute_opencode(
            config, prompt, repo_root, stage_timeout_ms,
            print_output=print_output,
            stage_name=stage.name.lower(),
        )
    except Exception as e:
        return _make_result(
            stage, StageOutcome.FAILURE,
            time.time() - start_time, error=str(e),
        )

    tokens = tokens_in + tokens_out
    metrics.total_cost += cost
    metrics.total_tokens_in += tokens_in
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
        )

    # Detect context pressure — if the stage used most of the context window,
    # it likely hit the auto-compact plugin or was constrained. Log it.
    kill_pct = getattr(config, "context_kill_pct", 95)
    compact_pct = getattr(config, "context_compact_pct", 85)
    ctx_window = getattr(config, "context_window", 200_000)
    if ctx_window > 0 and tokens_in > 0:
        usage_pct = (tokens_in / ctx_window) * 100
        if usage_pct >= kill_pct:
            metrics.kills_context += 1
            metrics.last_kill_reason = "context_pressure"
            print(f"  Context pressure: {usage_pct:.0f}% (kill threshold: {kill_pct}%)")
        elif usage_pct >= compact_pct:
            print(f"  Context pressure: {usage_pct:.0f}% (compact threshold: {compact_pct}%)")

    # Build per-task telemetry for reconciliation
    stage_model = config.model_for_stage(stage.name.lower())
    stage_metrics = {
        "cost": round(cost, 6),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "iterations": stage_iters,
        "model": stage_model or "",
    }
    meta["stage_metrics"] = stage_metrics

    # Reconcile agent output through tix
    reconcile_result = _reconcile_stage(stage, tix, stdout_output, meta)
    duration = time.time() - start_time

    # Log reconciliation summary
    print(f"  Reconcile: {reconcile_result.summary}")
    if reconcile_result.errors:
        for err in reconcile_result.errors:
            print(f"  Error: {err}", file=sys.stderr)

    # Count accepted tasks for session metrics
    metrics.tasks_completed += len(reconcile_result.tasks_accepted)

    if return_code == 0 and reconcile_result.ok:
        return _make_result(
            stage, StageOutcome.SUCCESS, duration,
            cost=cost, tokens_used=tokens,
        )

    error_msg = f"Stage exited {return_code}"
    if not reconcile_result.ok:
        error_msg += f"; reconcile: {reconcile_result.summary}"

    return _make_result(
        stage, StageOutcome.FAILURE, duration, return_code,
        error=error_msg, cost=cost, tokens_used=tokens,
    )


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


def _create_stage_wrapper(
    repo_root: Path,
    ralph_dir: Path,
    project_rules: Optional[str] = None,
    tix_instance: Optional[Tix] = None,
) -> Callable:
    """Create a stage wrapper function for the state machine."""
    if tix_instance is None:
        raise RuntimeError("Tix is required for construct mode")

    def run_stage_wrapper(
        cfg: GlobalConfig,
        stage: Stage,
        st: RalphState,
        met: Metrics,
        timeout_ms: int,
        ctx_limit: int,
    ) -> StageResult:
        print(f"\n{Colors.CYAN}[{stage.name}]{Colors.NC}")

        # Pre-check: auto-accept done tasks whose acceptance criteria pass
        if stage == Stage.VERIFY:
            accepted = _run_acceptance_precheck(tix_instance, repo_root)
            if accepted > 0:
                met.tasks_completed += accepted
                print(f"  Pre-check: {accepted} task(s) auto-accepted")
                # Check if there are still done tasks needing agent review
                try:
                    remaining = tix_instance.query_done_tasks()
                    if not remaining:
                        print("  All done tasks passed pre-check — skipping agent")
                        return _make_result(stage, StageOutcome.SUCCESS)
                except TixError:
                    pass

        result = _run_stage(
            cfg, stage, st, met, timeout_ms,
            repo_root, ralph_dir, project_rules,
            True, tix_instance, time.time(),
        )

        # Post-BUILD: try auto-accepting the task immediately
        # Saves a full VERIFY round trip if acceptance criteria are runnable
        if stage == Stage.BUILD and result.outcome == StageOutcome.SUCCESS:
            post_accepted = _run_acceptance_precheck(tix_instance, repo_root)
            if post_accepted > 0:
                met.tasks_completed += post_accepted
                print(f"  Post-BUILD pre-check: {post_accepted} task(s) auto-accepted")

        return result

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
    }
    _exit_labels = {
        "complete": f"SPEC COMPLETE: {state.spec}",
        "circuit_breaker": "CIRCUIT BREAKER TRIPPED",
        "cost_limit": "COST LIMIT REACHED",
        "max_iterations": "MAX ITERATIONS REACHED",
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

    print(f"{Colors.BLUE}{'━' * 40}{Colors.NC}")


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
    
    # Load global config
    global_config = GlobalConfig.load()
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

    # Create state machine
    state_machine = ConstructStateMachine(
        config=global_config,
        metrics=metrics,
        stage_timeout_ms=stage_timeout_ms,
        context_limit=context_limit,
        run_stage_fn=_create_stage_wrapper(
            repo_root, ralph_dir, project_rules, tix_instance
        ),
        load_state_fn=lambda: load_state(repo_root),
        save_state_fn=lambda st: save_state(st, repo_root),
        tix=tix_instance,
        loop_detector=loop_detector,
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
            if max_cost > 0:
                cost_display = f" | Cost: ${metrics.total_cost:.4f}/${max_cost}"
            else:
                cost_display = f" | Cost: ${metrics.total_cost:.4f}"
            
            print()
            print(f"{Colors.GREEN}╔═══════════════════════════════════════════════════════════════╗{Colors.NC}")
            print(f"{Colors.GREEN}║  ITERATION {iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{cost_display}{Colors.NC}")
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
            
            # Commit any tix plan changes
            plan_file = tix_instance.plan_file()
            state_file = cwd / ".tix" / "ralph-state.json"
            if has_uncommitted_tix(plan_file, state_file, cwd):
                files_to_add = [str(plan_file)]
                if state_file.exists():
                    files_to_add.append(str(state_file))
                subprocess.run(
                    ["git", "add"] + files_to_add,
                    cwd=cwd,
                    capture_output=True,
                )
                commit_result = subprocess.run(
                    ["git", "commit", "-m", f"ralph: iteration {iteration}"],
                    cwd=cwd,
                    capture_output=True,
                )
                if commit_result.returncode == 0:
                    metrics.commits_made += 1
            
            # Push changes with retry
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
        log_dir = Path(global_config.log_dir)
        _emit_session_summary(
            metrics, exit_reason, state.spec or "", global_config, log_dir,
            tix=tix_instance,
        )
    
    return 0 if exit_reason in ("complete", "no_work", "max_iterations") else 1
