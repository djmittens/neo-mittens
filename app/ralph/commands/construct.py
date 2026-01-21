"""Ralph construct command.

Construct mode - main autonomous development loop.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from ralph.config import GlobalConfig
from ralph.context import Metrics
from ralph.opencode import spawn_opencode, parse_json_stream, extract_metrics
from ralph.stages.base import (
    ConstructStateMachine,
    Stage,
    StageOutcome,
    StageResult,
)
from ralph.state import RalphState, load_state, save_state
from ralph.utils import Colors

__all__ = ["cmd_construct"]

STAGE_PROMPTS = {
    Stage.INVESTIGATE: "PROMPT_investigate.md",
    Stage.BUILD: "PROMPT_build.md",
    Stage.VERIFY: "PROMPT_verify.md",
    Stage.DECOMPOSE: "PROMPT_decompose.md",
}


def _load_stage_prompt(ralph_dir: Path, stage: Stage) -> Optional[str]:
    """Load the prompt file for a stage.

    Args:
        ralph_dir: Path to ralph directory.
        stage: The stage to load prompt for.

    Returns:
        Prompt content or None if not found.
    """
    prompt_file = STAGE_PROMPTS.get(stage)
    if not prompt_file:
        return None
    prompt_path = ralph_dir / prompt_file
    if not prompt_path.exists():
        return None
    return prompt_path.read_text()


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
    """Run a single stage by spawning opencode.

    Args:
        config: Global configuration.
        stage: The stage to run.
        state: Current Ralph state.
        metrics: Metrics tracker.
        stage_timeout_ms: Timeout in milliseconds.
        context_limit: Context window limit.
        repo_root: Repository root path.
        ralph_dir: Ralph directory path.
        print_output: Whether to print opencode output.

    Returns:
        StageResult with outcome and metrics.
    """
    start_time = time.time()

    prompt = _load_stage_prompt(ralph_dir, stage)
    if not prompt:
        return StageResult(
            stage=stage,
            outcome=StageOutcome.SKIP,
            error=f"No prompt file for stage {stage.name}",
        )

    if stage == Stage.INVESTIGATE and not state.issues:
        return StageResult(stage=stage, outcome=StageOutcome.SKIP)

    if stage == Stage.BUILD and not state.pending:
        return StageResult(stage=stage, outcome=StageOutcome.SKIP)

    if stage == Stage.VERIFY and not state.done:
        return StageResult(stage=stage, outcome=StageOutcome.SKIP)

    try:
        model = config.model if hasattr(config, "model") else None
        proc = spawn_opencode(
            prompt, cwd=repo_root, timeout=stage_timeout_ms, model=model
        )

        stdout_output = ""
        try:
            stdout_bytes, _ = proc.communicate(timeout=stage_timeout_ms // 1000)
            stdout_output = (
                stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise

        if print_output and stdout_output:
            for line in stdout_output.split("\n")[-20:]:
                print(f"  {line}")

        duration = time.time() - start_time

        if proc.returncode == 0:
            return StageResult(
                stage=stage,
                outcome=StageOutcome.SUCCESS,
                exit_code=0,
                duration_seconds=duration,
            )
        else:
            return StageResult(
                stage=stage,
                outcome=StageOutcome.FAILURE,
                exit_code=proc.returncode,
                duration_seconds=duration,
                error=f"Stage exited with code {proc.returncode}",
            )

    except subprocess.TimeoutExpired:
        return StageResult(
            stage=stage,
            outcome=StageOutcome.FAILURE,
            duration_seconds=time.time() - start_time,
            kill_reason="timeout",
            error="Stage timed out",
        )
    except Exception as e:
        return StageResult(
            stage=stage,
            outcome=StageOutcome.FAILURE,
            duration_seconds=time.time() - start_time,
            error=str(e),
        )


def cmd_construct(config: dict, iterations: int, args: argparse.Namespace) -> int:
    """Construct mode - main autonomous development loop.

    Runs the construct state machine: INVESTIGATE -> BUILD -> VERIFY
    in a loop until the spec is complete or max iterations reached.

    Args:
        config: Ralph configuration dict.
        iterations: Maximum iterations (0 = unlimited).
        args: Command-line arguments.

    Returns:
        Exit code (0 for success).
    """
    plan_file: Optional[Path] = config.get("plan_file")
    repo_root: Optional[Path] = config.get("repo_root")
    ralph_dir: Optional[Path] = config.get("ralph_dir")

    if not plan_file or not plan_file.exists():
        print(
            f"{Colors.RED}No plan file found. Run 'ralph init' or 'ralph plan' first.{Colors.NC}"
        )
        return 1

    if not repo_root or not ralph_dir:
        print(
            f"{Colors.RED}Invalid configuration: missing repo_root or ralph_dir.{Colors.NC}"
        )
        return 1

    state = load_state(plan_file)
    if not state.spec:
        print(
            f"{Colors.RED}No spec set. Run 'ralph set-spec <spec.md>' first.{Colors.NC}"
        )
        return 1

    state = load_state(plan_file)
    if not state.spec:
        print(
            f"{Colors.RED}No spec set. Run 'ralph set-spec <spec.md>' first.{Colors.NC}"
        )
        return 1

    print(f"{Colors.CYAN}Ralph Construct Mode{Colors.NC}")
    print(f"  Spec: {state.spec}")
    print(f"  Iterations: {iterations if iterations > 0 else 'unlimited'}")
    print(f"  Pending tasks: {len(state.pending)}")
    print(f"  Open issues: {len(state.issues)}")
    print()

    global_config = GlobalConfig.load()
    metrics = Metrics()

    max_iterations = iterations if iterations > 0 else 1000

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
            cfg,
            stage,
            st,
            met,
            timeout_ms,
            ctx_limit,
            repo_root,
            ralph_dir,
            print_output=True,
        )

    # Wrap state functions to pass plan_file
    def load_state_wrapper() -> RalphState:
        return load_state(plan_file)

    def save_state_wrapper(st: RalphState) -> None:
        save_state(st, plan_file)

    state_machine = ConstructStateMachine(
        config=global_config,
        metrics=metrics,
        stage_timeout_ms=global_config.stage_timeout_ms,
        context_limit=global_config.context_window,
        run_stage_fn=run_stage_wrapper,
        load_state_fn=load_state_wrapper,
        save_state_fn=save_state_wrapper,
    )

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
