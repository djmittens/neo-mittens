"""Stage definitions and state machine for construct mode."""

import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ralph.config import GlobalConfig
    from ralph.context import Metrics, LoopDetector
    from ralph.state import RalphState


class Stage(Enum):
    """Stages within construct mode's iteration loop."""

    INVESTIGATE = auto()  # Turn issues into tasks
    BUILD = auto()  # Execute tasks
    VERIFY = auto()  # Verify done tasks against spec
    DECOMPOSE = auto()  # Handle BUILD failures by breaking down task
    RESCUE = auto()  # Handle stage/batch failures (step-centric recovery)
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
    DECOMPOSE is triggered on task failures, RESCUE on batch/stage failures.

    Uses explicit stage tracking with bounded batching for VERIFY/INVESTIGATE.
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
        loop_detector: Optional["LoopDetector"] = None,
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
            loop_detector: Optional loop detector for runaway prevention
        """
        self.config = config
        self.metrics = metrics
        self.stage_timeout_ms = stage_timeout_ms
        self.context_limit = context_limit
        self.run_stage = run_stage_fn
        self.load_state = load_state_fn
        self.save_state = save_state_fn
        self.loop_detector = loop_detector
        self._last_stage_output: str = ""

    def run_iteration(self, iteration: int) -> tuple[bool, bool]:
        """Run a single iteration of the construct loop.

        Uses explicit stage from state. Each iteration runs only the current stage,
        then transitions to the next.

        Args:
            iteration: Current iteration number

        Returns:
            Tuple of (should_continue, spec_complete)
            - should_continue: True if more iterations needed
            - spec_complete: True if spec is fully implemented
        """
        state = self.load_state()

        # Check for terminal states
        if not state.spec:
            return False, False

        if state.stage == "COMPLETE":
            return False, True

        # Check for progress stall
        progress_interval = getattr(self.config, "progress_check_interval", 0)
        if progress_interval > 0:
            stall_time = self.metrics.seconds_since_progress()
            if stall_time > progress_interval:
                print(
                    f"WARNING: No progress in {int(stall_time)}s "
                    f"(threshold: {progress_interval}s)"
                )

        # Dispatch based on explicit stage
        if state.stage == "DECOMPOSE":
            return self._run_decompose(state)
        elif state.stage == "RESCUE":
            return self._run_rescue(state)
        elif state.stage == "INVESTIGATE":
            return self._run_investigate(state)
        elif state.stage == "BUILD":
            return self._run_build(state)
        elif state.stage == "VERIFY":
            return self._run_verify(state)
        else:
            # Unknown or PLAN stage - compute initial stage
            state.stage = state.compute_initial_stage()
            self.save_state(state)
            return True, False

    def _run_decompose(self, state: "RalphState") -> tuple[bool, bool]:
        """Run DECOMPOSE stage. Transitions to INVESTIGATE on completion."""
        result = self._run_stage_with_state(Stage.DECOMPOSE, state)

        # DECOMPOSE -> INVESTIGATE (rejoin the cycle)
        state = self.load_state()
        state.transition_to_investigate()
        self.save_state(state)
        return True, False

    def _run_rescue(self, state: "RalphState") -> tuple[bool, bool]:
        """Run RESCUE stage for step-centric recovery."""
        result = self._run_stage_with_state(Stage.RESCUE, state)

        # RESCUE -> back to the failed stage
        state = self.load_state()
        failed_stage = state.rescue_stage
        state._clear_rescue_state()
        state._clear_batch_state()

        if failed_stage == "VERIFY":
            state.transition_to_verify()
        elif failed_stage == "INVESTIGATE":
            state.transition_to_investigate()
        else:
            state.transition_to_investigate()

        self.save_state(state)
        return True, False

    def _run_investigate(self, state: "RalphState") -> tuple[bool, bool]:
        """Run INVESTIGATE stage with bounded batching."""
        if state.issues:
            batch_size = self.config.investigate_batch_size
            all_issue_ids = [i.id for i in state.issues]

            # Process in batches
            while True:
                batch = state.get_next_batch(all_issue_ids, batch_size)
                if not batch:
                    break

                self.save_state(state)
                result = self._run_stage_with_state(Stage.INVESTIGATE, state)

                if result.outcome == StageOutcome.FAILURE:
                    if state.mark_batch_failed(max_retries=2):
                        self.save_state(state)
                        continue
                    else:
                        self._handle_batch_failure(result, state, "INVESTIGATE")
                        return True, False

                state.mark_batch_complete()
                state = self.load_state()

        # INVESTIGATE -> BUILD
        state.transition_to_build()
        self.save_state(state)
        return True, False

    def _run_build(self, state: "RalphState") -> tuple[bool, bool]:
        """Run BUILD stage. Transitions to VERIFY."""
        if state.pending:
            result = self._run_stage_with_state(Stage.BUILD, state)

            if result.outcome == StageOutcome.FAILURE:
                self._handle_task_failure(result)
                return True, False

            state = self.load_state()

        # BUILD -> VERIFY
        state.transition_to_verify()
        self.save_state(state)
        return True, False

    def _run_verify(self, state: "RalphState") -> tuple[bool, bool]:
        """Run VERIFY stage with bounded batching."""
        if state.done:
            failed = self._process_verify_batches(state)
            if failed:
                return True, False

        return self._finalize_verify_stage()

    def _process_verify_batches(self, state: "RalphState") -> bool:
        """Process VERIFY in batches. Returns True if batch failure occurred."""
        batch_size = self.config.verify_batch_size
        all_task_ids = [t.id for t in state.done]

        while True:
            batch = state.get_next_batch(all_task_ids, batch_size)
            if not batch:
                return False

            self.save_state(state)
            result = self._run_stage_with_state(Stage.VERIFY, state)

            if result.outcome == StageOutcome.FAILURE:
                if state.mark_batch_failed(max_retries=2):
                    self.save_state(state)
                    continue
                self._handle_batch_failure(result, state, "VERIFY")
                return True

            state.mark_batch_complete()
            state = self.load_state()
            all_task_ids = [t.id for t in state.done]

        return False

    def _finalize_verify_stage(self) -> tuple[bool, bool]:
        """Check if complete or transition to INVESTIGATE."""
        state = self.load_state()
        if not state.done and not state.pending and not state.issues:
            state.transition_to_complete()
            self.save_state(state)
            return False, True

        state.transition_to_investigate()
        self.save_state(state)
        return True, False

    def _run_stage_with_state(self, stage: Stage, state: "RalphState") -> StageResult:
        """Run a stage and return the result."""
        result = self.run_stage(
            self.config,
            stage,
            state,
            self.metrics,
            self.stage_timeout_ms,
            self.context_limit,
        )

        # Check for loop detection if enabled
        if self.loop_detector and result.outcome == StageOutcome.SUCCESS:
            # Use a simple representation of the result for loop detection
            output_repr = f"{stage.name}:{result.exit_code}:{result.duration_seconds:.0f}"
            if self.loop_detector.check_output(output_repr):
                self.metrics.kills_loop += 1
                return StageResult(
                    stage=stage,
                    outcome=StageOutcome.FAILURE,
                    exit_code=-2,
                    duration_seconds=result.duration_seconds,
                    error="Loop detected: repeated identical stage outputs",
                    kill_reason="loop_detected",
                )

        # Record progress on success
        if result.outcome == StageOutcome.SUCCESS:
            self.metrics.record_progress()

        return result

    def _handle_task_failure(self, result: StageResult) -> None:
        """Handle a BUILD task failure by transitioning to DECOMPOSE."""
        state = self.load_state()

        target_task_id = result.task_id or "__stage_failure__"
        state.transition_to_decompose(
            task_id=target_task_id,
            reason=result.kill_reason or "unknown",
            log_path=result.kill_log,
        )

        # Reset task status to pending
        if result.task_id:
            task = state.get_task_by_id(result.task_id)
            if task:
                task.status = "p"
                task.done_at = None

        self.save_state(state)

    def _handle_batch_failure(
        self, result: StageResult, state: "RalphState", stage_name: str
    ) -> None:
        """Handle a batch failure by transitioning to RESCUE."""
        state = self.load_state()

        state.transition_to_rescue(
            stage=stage_name,
            batch_items=state.batch_items,
            reason=result.kill_reason or "unknown",
            log_path=result.kill_log,
        )

        self.save_state(state)

    def _has_killed_tasks(self, state: "RalphState") -> bool:
        """Check if any tasks have kill_reason set."""
        return any(getattr(t, "kill_reason", None) for t in state.tasks)
