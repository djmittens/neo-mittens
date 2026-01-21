"""Stage definitions and state machine for construct mode."""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ralph.config import GlobalConfig
    from ralph.context import Metrics
    from ralph.state import RalphState


class Stage(Enum):
    """Stages within construct mode's iteration loop."""

    INVESTIGATE = auto()  # Turn issues into tasks
    BUILD = auto()  # Execute tasks
    VERIFY = auto()  # Verify done tasks against spec
    DECOMPOSE = auto()  # Handle failures by breaking down work
    COMPLETE = auto()  # Spec fully implemented


class StageOutcome(Enum):
    """Outcome of running a stage."""

    SUCCESS = auto()  # Stage completed normally
    FAILURE = auto()  # Stage failed (timeout/context/error)
    SKIP = auto()  # Stage skipped (no work to do)


@dataclass
class StageResult:
    """Result of running a single stage."""

    stage: Stage
    outcome: StageOutcome
    exit_code: int = 0
    duration_seconds: float = 0.0
    cost: float = 0.0
    tokens_used: int = 0
    kill_reason: Optional[str] = None  # "timeout", "context_limit", "compaction_failed"
    kill_log: Optional[str] = None  # Path to log file if killed
    task_id: Optional[str] = None  # Task that was being executed (for BUILD/DECOMPOSE)
    error: Optional[str] = None  # Error message if any


class ConstructStateMachine:
    """State machine for construct mode iterations.

    Each iteration runs: INVESTIGATE -> BUILD -> VERIFY
    DECOMPOSE is triggered on failures and runs before the next iteration.
    """

    def __init__(
        self,
        config: "GlobalConfig",
        metrics: "Metrics",
        stage_timeout_ms: int,
        context_limit: int,
        run_stage_fn: Callable[
            ["GlobalConfig", Stage, "RalphState", "Metrics", int, int], StageResult
        ],
        load_state_fn: Callable[[], "RalphState"],
        save_state_fn: Callable[["RalphState"], None],
    ):
        """Initialize the state machine.

        Args:
            config: Global configuration
            metrics: Metrics tracker
            stage_timeout_ms: Timeout per stage in milliseconds
            context_limit: Context window size in tokens
            run_stage_fn: Function to actually run a stage (injected for testability)
            load_state_fn: Function to load state (injected for testability)
            save_state_fn: Function to save state (injected for testability)
        """
        self.config = config
        self.metrics = metrics
        self.stage_timeout_ms = stage_timeout_ms
        self.context_limit = context_limit
        self.run_stage = run_stage_fn
        self.load_state = load_state_fn
        self.save_state = save_state_fn

        # Track if we need to run DECOMPOSE before next iteration
        self._pending_decompose = False
        self._decompose_task_id: Optional[str] = None
        self._decompose_kill_reason: Optional[str] = None
        self._decompose_kill_log: Optional[str] = None

    def run_iteration(self, iteration: int) -> tuple[bool, bool]:
        """Run a single iteration of the construct loop.

        Per spec: INVESTIGATE -> BUILD -> VERIFY (sequentially)
        DECOMPOSE runs if there's a pending failure from previous stage.

        Args:
            iteration: Current iteration number

        Returns:
            Tuple of (should_continue, spec_complete)
            - should_continue: True if more iterations needed
            - spec_complete: True if spec is fully implemented
        """
        state = self.load_state()

        # If we have a pending decompose from a failure, run it first
        if self._pending_decompose:
            result = self._run_stage_with_state(Stage.DECOMPOSE, state)
            self._clear_decompose_state()

            if result.outcome == StageOutcome.FAILURE:
                pass  # DECOMPOSE itself failed - continue anyway

            # After DECOMPOSE, start fresh iteration
            return True, False

        # Check for tasks with kill_reason in persisted state
        if self._has_killed_tasks(state):
            result = self._run_stage_with_state(Stage.DECOMPOSE, state)
            # After DECOMPOSE, start fresh iteration
            return True, False

        # Check for terminal state - no spec configured
        if not state.spec:
            return False, False

        # Phase 1: INVESTIGATE (if issues exist)
        if state.issues:
            result = self._run_stage_with_state(Stage.INVESTIGATE, state)
            if result.outcome == StageOutcome.FAILURE:
                self._handle_failure(result)
                return True, False
            state = self.load_state()

        # Phase 2: BUILD (execute tasks)
        pending_tasks = [t for t in state.tasks if t.status == "pending"]
        if pending_tasks:
            result = self._run_stage_with_state(Stage.BUILD, state)
            if result.outcome == StageOutcome.FAILURE:
                self._handle_failure(result)
                return True, False
            state = self.load_state()

        # Phase 3: VERIFY (if done tasks exist)
        done_tasks = [t for t in state.tasks if t.status == "done"]
        if done_tasks:
            result = self._run_stage_with_state(Stage.VERIFY, state)
            if result.outcome == StageOutcome.FAILURE:
                self._handle_failure(result)
                return True, False
            state = self.load_state()

        # Check if we're complete
        pending_tasks = [t for t in state.tasks if t.status == "pending"]
        done_tasks = [t for t in state.tasks if t.status == "done"]
        if not pending_tasks and not done_tasks and not state.issues:
            return False, True  # Spec complete!

        # More work to do
        return True, False

    def _run_stage_with_state(self, stage: Stage, state: "RalphState") -> StageResult:
        """Run a stage and return the result."""
        return self.run_stage(
            self.config,
            stage,
            state,
            self.metrics,
            self.stage_timeout_ms,
            self.context_limit,
        )

    def _handle_failure(self, result: StageResult) -> None:
        """Handle a stage failure by queuing DECOMPOSE."""
        self._pending_decompose = True
        self._decompose_task_id = result.task_id
        self._decompose_kill_reason = result.kill_reason
        self._decompose_kill_log = result.kill_log

        # Mark the task with kill_reason in state
        if result.task_id:
            state = self.load_state()
            task = next((t for t in state.tasks if t.id == result.task_id), None)
            if task:
                task.kill_reason = result.kill_reason
                task.kill_log = result.kill_log
                self.save_state(state)

    def _clear_decompose_state(self) -> None:
        """Clear the pending decompose state."""
        self._pending_decompose = False
        self._decompose_task_id = None
        self._decompose_kill_reason = None
        self._decompose_kill_log = None

    def _has_killed_tasks(self, state: "RalphState") -> bool:
        """Check if any tasks have kill_reason set."""
        return any(getattr(t, "kill_reason", None) for t in state.tasks)
