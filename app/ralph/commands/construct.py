"""Ralph construct command.

Construct mode - main autonomous development loop.
"""

import argparse
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

from ..config import GlobalConfig
from ..context import Metrics
from ..opencode import spawn_opencode
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

STAGE_PROMPTS = {
    Stage.INVESTIGATE: "PROMPT_investigate.md",
    Stage.BUILD: "PROMPT_build.md",
    Stage.VERIFY: "PROMPT_verify.md",
    Stage.DECOMPOSE: "PROMPT_decompose.md",
}


def _load_stage_prompt(ralph_dir: Path, stage: Stage) -> Optional[str]:
    """Load the prompt file for a stage."""
    prompt_file = STAGE_PROMPTS.get(stage)
    if not prompt_file:
        return None
    prompt_path = ralph_dir / prompt_file
    if not prompt_path.exists():
        return None
    return prompt_path.read_text()


def _should_skip_stage(stage: Stage, state: RalphState) -> bool:
    """Check if stage should be skipped based on state."""
    if stage == Stage.INVESTIGATE:
        return not state.issues
    if stage == Stage.BUILD:
        return not state.pending
    if stage == Stage.VERIFY:
        return not state.done
    return False


def _make_result(
    stage: Stage,
    outcome: StageOutcome,
    duration: float = 0.0,
    exit_code: int = 0,
    error: Optional[str] = None,
    kill_reason: Optional[str] = None,
) -> StageResult:
    """Create a StageResult with the given parameters."""
    return StageResult(
        stage=stage,
        outcome=outcome,
        exit_code=exit_code,
        duration_seconds=duration,
        error=error,
        kill_reason=kill_reason,
    )


def _execute_opencode(
    config: GlobalConfig, prompt: str, repo_root: Path, stage_timeout_ms: int
) -> Tuple[int, str, bool]:
    """Execute opencode and return (return_code, output, timed_out)."""
    model = config.model if hasattr(config, "model") else None
    proc = spawn_opencode(prompt, cwd=repo_root, timeout=stage_timeout_ms, model=model)
    try:
        stdout_bytes, _ = proc.communicate(timeout=stage_timeout_ms // 1000)
        stdout_output = (
            stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        )
        return proc.returncode, stdout_output, False
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return -1, "", True


def _run_stage(
    config: GlobalConfig,
    stage: Stage,
    state: RalphState,
    metrics: Metrics,
    stage_timeout_ms: int,
    context_limit: int,
    repo_root: Path,
    ralph_dir: Path,
    print_output: bool = True,
) -> StageResult:
    """Run a single stage by spawning opencode."""
    start_time = time.time()

    prompt = _load_stage_prompt(ralph_dir, stage)
    if not prompt:
        return _make_result(
            stage, StageOutcome.SKIP, error=f"No prompt file for stage {stage.name}"
        )

    if _should_skip_stage(stage, state):
        return _make_result(stage, StageOutcome.SKIP)

    try:
        return_code, stdout_output, timed_out = _execute_opencode(
            config, prompt, repo_root, stage_timeout_ms
        )
    except Exception as e:
        return _make_result(
            stage, StageOutcome.FAILURE, time.time() - start_time, error=str(e)
        )

    if timed_out:
        return _make_result(
            stage,
            StageOutcome.FAILURE,
            time.time() - start_time,
            error="Stage timed out",
            kill_reason="timeout",
        )

    if print_output and stdout_output:
        for line in stdout_output.split("\n")[-20:]:
            print(f"  {line}")

    duration = time.time() - start_time
    if return_code == 0:
        return _make_result(stage, StageOutcome.SUCCESS, duration)
    return _make_result(
        stage,
        StageOutcome.FAILURE,
        duration,
        return_code,
        error=f"Stage exited with code {return_code}",
    )


def _validate_config(
    config: dict, args_spec: Optional[str] = None
) -> Tuple[Optional[Path], Optional[Path], Optional[Path], Optional[str]]:
    """Validate and extract paths from config dict.

    Returns:
        Tuple of (plan_file, repo_root, ralph_dir, error_message).
    """
    plan_file: Optional[Path] = config.get("plan_file")
    repo_root: Optional[Path] = config.get("repo_root")
    ralph_dir: Optional[Path] = config.get("ralph_dir")

    if not plan_file or not plan_file.exists():
        if args_spec:
            # If spec is provided, initialize directory and create state with spec
            cmd_init()
            # After init, compute paths from current directory
            repo_root = Path.cwd()
            global_config = GlobalConfig.load()
            ralph_dir = repo_root / global_config.ralph_dir
            plan_file = ralph_dir / "plan.jsonl"
            # Update config dict for caller
            config["plan_file"] = plan_file
            config["repo_root"] = repo_root
            config["ralph_dir"] = ralph_dir
        else:
            return (
                None,
                None,
                None,
                "No plan file found. Run 'ralph init' or 'ralph plan' first.",
            )
    if not repo_root or not ralph_dir:
        return (
            None,
            None,
            None,
            "Invalid configuration: missing repo_root or ralph_dir.",
        )
    return plan_file, repo_root, ralph_dir, None


def _print_construct_header(state: RalphState, iterations: int) -> None:
    """Print the construct mode header."""
    print(f"{Colors.CYAN}Ralph Construct Mode{Colors.NC}")
    print(f"  Spec: {state.spec}")
    print(f"  Iterations: {iterations if iterations > 0 else 'unlimited'}")
    print(f"  Pending tasks: {len(state.pending)}")
    print(f"  Open issues: {len(state.issues)}")
    print()


def _run_iterations(state_machine: ConstructStateMachine, max_iterations: int) -> int:
    """Run construct iterations and return exit code."""
    try:
        for i in range(1, max_iterations + 1):
            print(f"\n{Colors.BLUE}=== Iteration {i} ==={Colors.NC}")
            should_continue, spec_complete = state_machine.run_iteration(i)
            if spec_complete:
                print(f"\n{Colors.GREEN}Spec complete!{Colors.NC}")
                return 0
            if not should_continue:
                print(f"\n{Colors.YELLOW}No more work to do.{Colors.NC}")
                return 0
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted.{Colors.NC}")
        return 130

    print(f"\n{Colors.YELLOW}Max iterations ({max_iterations}) reached.{Colors.NC}")
    return 0


def _get_spec_from_args(args: argparse.Namespace) -> Optional[str]:
    """Extract spec from args if present."""
    return args.spec if hasattr(args, "spec") else None


def _setup_state_with_spec(
    state: RalphState, spec: Optional[str], plan_file: Path
) -> None:
    """Set spec on state if provided and not already set."""
    if spec and not state.spec:
        state.spec = spec
        save_state(state, plan_file)


def _create_stage_wrapper(repo_root: Path, ralph_dir: Path):
    """Create a stage wrapper function for the state machine."""

    def run_stage_wrapper(
        cfg: GlobalConfig,
        stage: Stage,
        st: RalphState,
        met: Metrics,
        timeout_ms: int,
        ctx_limit: int,
    ) -> StageResult:
        print(f"\n{Colors.CYAN}[{stage.name}]{Colors.NC}")
        return _run_stage(
            cfg, stage, st, met, timeout_ms, ctx_limit, repo_root, ralph_dir
        )

    return run_stage_wrapper


def cmd_construct(config: dict, iterations: int, args: argparse.Namespace) -> int:
    """Construct mode - main autonomous development loop."""
    spec = _get_spec_from_args(args)
    plan_file_opt, repo_root_opt, ralph_dir_opt, error = _validate_config(config, spec)

    if error or not plan_file_opt or not repo_root_opt or not ralph_dir_opt:
        print(f"{Colors.RED}{error or 'Invalid configuration'}{Colors.NC}")
        return 1

    plan_file, repo_root, ralph_dir = plan_file_opt, repo_root_opt, ralph_dir_opt
    state = load_state(plan_file)
    _setup_state_with_spec(state, spec, plan_file)
    _print_construct_header(state, iterations)

    global_config = GlobalConfig.load()
    max_iterations = iterations if iterations > 0 else 1000

    state_machine = ConstructStateMachine(
        config=global_config,
        metrics=Metrics(),
        stage_timeout_ms=global_config.stage_timeout_ms,
        context_limit=global_config.context_window,
        run_stage_fn=_create_stage_wrapper(repo_root, ralph_dir),
        load_state_fn=lambda: load_state(plan_file),
        save_state_fn=lambda st: save_state(st, plan_file),
    )

    return _run_iterations(state_machine, max_iterations)


# Auto-init implemented
