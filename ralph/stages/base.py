"""Base types and state machine for Ralph construct stages.

This module provides the core types for the construct state machine:
- Stage: Enum of stages in the construct loop
- StageOutcome: Enum of possible stage outcomes
- StageResult: Dataclass representing the result of running a stage
- ConstructStateMachine: State machine for running construct iterations
"""

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ralph.config import GlobalConfig
    from ralph.context import Metrics
    from ralph.state import RalphState


class Stage(Enum):
    """Stages within construct mode's iteration loop."""

    INVESTIGATE = auto()
    BUILD = auto()
    VERIFY = auto()
    DECOMPOSE = auto()
    COMPLETE = auto()


class StageOutcome(Enum):
    """Outcome of running a stage."""

    SUCCESS = auto()
    FAILURE = auto()
    SKIP = auto()


@dataclass
class StageResult:
    """Result of running a single stage.

    Attributes:
        stage: The stage that was run.
        outcome: The outcome of running the stage.
        exit_code: Exit code from the stage (0 for success).
        duration_seconds: How long the stage took to run.
        cost: Cost in dollars for this stage run.
        tokens_used: Number of tokens consumed.
        kill_reason: Reason if the stage was killed ("timeout", "context_limit", "compaction_failed").
        kill_log: Path to log file if stage was killed.
        task_id: ID of the task being executed (for BUILD/DECOMPOSE).
        error: Error message if any.
    """

    stage: Stage
    outcome: StageOutcome
    exit_code: int = 0
    duration_seconds: float = 0.0
    cost: float = 0.0
    tokens_used: int = 0
    kill_reason: Optional[str] = None
    kill_log: Optional[str] = None
    task_id: Optional[str] = None
    error: Optional[str] = None


StageRunnerFn = Callable[
    ["GlobalConfig", Stage, "RalphState", "Metrics", int, int], StageResult
]


class ConstructStateMachine:
    """State machine for construct mode iterations.

    Each iteration runs: INVESTIGATE -> BUILD -> VERIFY
    DECOMPOSE is triggered on failures and runs before the next iteration.

    Attributes:
        config: Global Ralph configuration.
        metrics: Metrics tracker for the construct session.
        stage_timeout_ms: Timeout per stage in milliseconds.
        context_limit: Context window size in tokens.
        run_stage: Function to actually run a stage (injected for testability).
    """

    def __init__(
        self,
        config: "GlobalConfig",
        metrics: "Metrics",
        stage_timeout_ms: int,
        context_limit: int,
        run_stage_fn: StageRunnerFn,
        plan_path: Path,
        load_state_fn: Callable[[Path], "RalphState"],
        save_state_fn: Callable[["RalphState", Path], None],
    ) -> None:
        """Initialize the state machine.

        Args:
            config: Ralph configuration.
            metrics: Metrics tracker.
            stage_timeout_ms: Timeout per stage in milliseconds.
            context_limit: Context window size in tokens.
            run_stage_fn: Function to actually run a stage (injected for testability).
            plan_path: Path to the plan.jsonl file.
            load_state_fn: Function to load state from plan file.
            save_state_fn: Function to save state to plan file.
        """
        self.config = config
        self.metrics = metrics
        self.stage_timeout_ms = stage_timeout_ms
        self.context_limit = context_limit
        self.run_stage = run_stage_fn
        self.plan_path = plan_path
        self.load_state = load_state_fn
        self.save_state = save_state_fn

        self._pending_decompose = False
        self._decompose_task_id: Optional[str] = None
        self._decompose_kill_reason: Optional[str] = None
        self._decompose_kill_log: Optional[str] = None

    def run_iteration(self, iteration: int) -> tuple[bool, bool]:
        """Run a single iteration of the construct loop.

        Per spec: INVESTIGATE -> BUILD -> VERIFY (sequentially)
        DECOMPOSE runs if there's a pending failure from previous stage.

        Args:
            iteration: Current iteration number.

        Returns:
            Tuple of (should_continue, spec_complete):
            - should_continue: True if more iterations needed.
            - spec_complete: True if spec is fully implemented.
        """
        state = self.load_state(self.plan_path)

        if self._pending_decompose:
            result = self._run_stage_with_state(Stage.DECOMPOSE, state)
            self._pending_decompose = False
            self._decompose_task_id = None
            self._decompose_kill_reason = None
            self._decompose_kill_log = None

            if result.outcome == StageOutcome.FAILURE:
                pass

            return True, False

        if any(t.needs_decompose for t in state.tasks if t.status == "p"):
            result = self._run_stage_with_state(Stage.DECOMPOSE, state)

            if result.outcome == StageOutcome.FAILURE:
                pass

            return True, False

        if not state.spec:
            return False, False

        if state.issues:
            result = self._run_stage_with_state(Stage.INVESTIGATE, state)

            if result.outcome == StageOutcome.FAILURE:
                self._handle_failure(result)
                return True, False

            state = self.load_state(self.plan_path)

        if state.pending:
            result = self._run_stage_with_state(Stage.BUILD, state)

            if result.outcome == StageOutcome.FAILURE:
                self._handle_failure(result)
                return True, False

            state = self.load_state(self.plan_path)

        if state.done:
            result = self._run_stage_with_state(Stage.VERIFY, state)

            if result.outcome == StageOutcome.FAILURE:
                self._handle_failure(result)
                return True, False

            state = self.load_state(self.plan_path)

        if not state.pending and not state.done and not state.issues:
            return False, True

        return True, False

    def _run_stage_with_state(self, stage: Stage, state: "RalphState") -> StageResult:
        """Run a stage and return the result.

        Args:
            stage: The stage to run.
            state: Current Ralph state.

        Returns:
            StageResult from running the stage.
        """
        return self.run_stage(
            self.config,
            stage,
            state,
            self.metrics,
            self.stage_timeout_ms,
            self.context_limit,
        )

    def _handle_failure(self, result: StageResult) -> None:
        """Handle a stage failure by queuing DECOMPOSE.

        Args:
            result: The failed stage result.
        """
        self._pending_decompose = True
        self._decompose_task_id = result.task_id
        self._decompose_kill_reason = result.kill_reason
        self._decompose_kill_log = result.kill_log

        if result.task_id:
            state = self.load_state(self.plan_path)
            task = next((t for t in state.tasks if t.id == result.task_id), None)
            if task:
                task.needs_decompose = True
                task.kill_reason = result.kill_reason
                task.kill_log = result.kill_log
                self.save_state(state, self.plan_path)


__all__ = [
    "Stage",
    "StageOutcome",
    "StageResult",
    "ConstructStateMachine",
    "StageRunnerFn",
]
