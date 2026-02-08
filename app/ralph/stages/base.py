"""Stage definitions and state machine for construct mode."""

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ralph.config import GlobalConfig
    from ralph.context import Metrics, LoopDetector
    from ralph.state import RalphState
    from ralph.tix import Tix, TixProtocol

logger = logging.getLogger(__name__)


class Stage(Enum):
    """Stages within construct mode's iteration loop."""

    INVESTIGATE = auto()  # Turn issues into tasks
    BUILD = auto()  # Execute tasks
    VERIFY = auto()  # Verify done tasks against spec
    DECOMPOSE = auto()  # Handle BUILD failures by breaking down task
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
    kill_reason: Optional[str] = None
    kill_log: Optional[str] = None
    task_id: Optional[str] = None
    error: Optional[str] = None


class ConstructStateMachine:
    """State machine for construct mode iterations.

    Ticket data is queried from tix. Orchestration state (stage, batch
    tracking, decompose state) lives in RalphState.

    Uses explicit stage tracking with bounded batching for VERIFY/INVESTIGATE.
    """

    def __init__(
        self,
        config: "GlobalConfig",
        metrics: "Metrics",
        stage_timeout_ms: int,
        context_limit: int,
        run_stage_fn: Callable[
            ["GlobalConfig", Stage, "RalphState", "Metrics", int, int],
            StageResult,
        ],
        load_state_fn: Callable[[], "RalphState"],
        save_state_fn: Callable[["RalphState"], None],
        tix: Optional["TixProtocol"] = None,
        loop_detector: Optional["LoopDetector"] = None,
    ):
        """Initialize the state machine.

        Args:
            config: Global configuration
            metrics: Metrics tracker
            stage_timeout_ms: Timeout per stage in milliseconds
            context_limit: Context window size in tokens
            run_stage_fn: Function to actually run a stage
            load_state_fn: Function to load orchestration state
            save_state_fn: Function to save orchestration state
            tix: Tix-compatible instance for ticket queries
            loop_detector: Optional loop detector
        """
        self.config = config
        self.metrics = metrics
        self.stage_timeout_ms = stage_timeout_ms
        self.context_limit = context_limit
        self.run_stage = run_stage_fn
        self.load_state = load_state_fn
        self.save_state = save_state_fn
        self.tix = tix
        self.loop_detector = loop_detector
        self._last_stage_output: str = ""
        self._batch_failure_count: int = 0
        self._ticket_cache: Optional[dict] = None

    # =========================================================================
    # Ticket queries (via tix, with per-iteration cache)
    # =========================================================================

    def _refresh_ticket_cache(self) -> None:
        """Refresh the cached ticket state from tix.

        Call once at the start of each iteration (or after mutations)
        to avoid redundant subprocess calls. All _has_* and _get_*
        methods read from this cache.
        """
        if not self.tix:
            self._ticket_cache = {}
            return
        try:
            self._ticket_cache = self.tix.query_full()
        except Exception:
            self._ticket_cache = {}

    def _invalidate_ticket_cache(self) -> None:
        """Invalidate the cache so the next query re-fetches from tix."""
        self._ticket_cache = None

    def _get_cached_full(self) -> dict:
        """Get cached full ticket state, refreshing if needed.

        Returns:
            Full ticket state dict from tix.
        """
        if self._ticket_cache is None:
            self._refresh_ticket_cache()
        return self._ticket_cache or {}

    def _has_pending_tasks(self) -> bool:
        """Check if there are pending tasks (from cache)."""
        full = self._get_cached_full()
        pending = full.get("tasks", {}).get("pending", [])
        return len(pending) > 0

    def _has_done_tasks(self) -> bool:
        """Check if there are done tasks (from cache)."""
        full = self._get_cached_full()
        done = full.get("tasks", {}).get("done", [])
        return len(done) > 0

    def _get_done_task_ids(self) -> list[str]:
        """Get IDs of done tasks (from cache)."""
        full = self._get_cached_full()
        done = full.get("tasks", {}).get("done", [])
        return [t.get("id", "") for t in done]

    def _has_issues(self) -> bool:
        """Check if there are open issues (from cache)."""
        full = self._get_cached_full()
        issues = full.get("issues", [])
        return len(issues) > 0

    def _get_issue_ids(self) -> list[str]:
        """Get IDs of open issues (from cache)."""
        full = self._get_cached_full()
        issues = full.get("issues", [])
        return [i.get("id", "") for i in issues]

    def _escalate_stuck_tasks(self) -> int:
        """Detect tasks stuck in reject loops and escalate them.

        A task with retries >= max_retries_per_task is stuck.
        Creates an issue describing the pattern and rejects the task
        so the next INVESTIGATE stage can address the root cause.

        Reads the ``retries`` field (tix native) written by
        ``_increment_reject_count`` in reconcile.py.

        Returns:
            Number of tasks escalated.
        """
        if not self.tix:
            return 0
        max_retries = getattr(self.config, "max_retries_per_task", 3)
        full = self._get_cached_full()
        tasks = full.get("tasks", {}).get("pending", [])

        escalated = 0
        for task in tasks:
            # Check both tix-native "retries" and legacy "reject_count"
            retry_count = task.get("retries", 0) or task.get("reject_count", 0)
            if retry_count < max_retries:
                continue

            task_id = task.get("id", "")
            task_name = task.get("name", "")
            reason = task.get("reject", "unknown")
            logger.warning(
                "Task %s rejected %d times — escalating to issue",
                task_id, retry_count,
            )
            try:
                self.tix.issue_add(
                    f"Task '{task_name}' ({task_id}) has been rejected "
                    f"{retry_count} times. Last reason: {reason}"
                )
                self.tix.task_reject(
                    task_id,
                    f"escalated: rejected {retry_count} times",
                )
            except Exception:
                pass
            escalated += 1

        return escalated

    @staticmethod
    def _token_similarity(a: str, b: str) -> float:
        """Jaccard similarity over word tokens.

        Args:
            a: First normalized string.
            b: Second normalized string.

        Returns:
            Similarity score between 0.0 and 1.0.
        """
        tokens_a = set(a.split())
        tokens_b = set(b.split())
        if not tokens_a and not tokens_b:
            return 1.0
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)

    def _deduplicate_issues(self) -> int:
        """Merge duplicate issues before INVESTIGATE.

        Uses a two-pass strategy:
        1. Exact match on normalized text (lowercase, collapse whitespace).
        2. Fuzzy match via Jaccard token similarity for near-duplicates.

        When duplicates are found, keeps the first and resolves the rest
        via tix.

        Returns:
            Number of duplicate issues resolved.
        """
        if not self.tix:
            return 0
        full = self._get_cached_full()
        issues = full.get("issues", [])
        if len(issues) < 2:
            return 0

        threshold = getattr(
            self.config, "issue_similarity_threshold", 0.8
        )

        # Build normalized descriptions
        entries: list[tuple[str, str, str]] = []  # (id, normalized, raw)
        for issue in issues:
            desc = issue.get("desc", "")
            issue_id = issue.get("id", "")
            normalized = " ".join(desc.lower().split())
            entries.append((issue_id, normalized, desc))

        kept_ids: set[str] = set()
        kept_descs: list[str] = []  # normalized descs of kept issues
        dup_ids: list[str] = []

        for issue_id, normalized, _raw in entries:
            is_dup = False
            # Pass 1: exact match
            if normalized in kept_descs:
                is_dup = True
            # Pass 2: fuzzy match (only if not already exact)
            if not is_dup and threshold < 1.0:
                for kept in kept_descs:
                    if self._token_similarity(normalized, kept) >= threshold:
                        is_dup = True
                        break

            if is_dup:
                dup_ids.append(issue_id)
            else:
                kept_ids.add(issue_id)
                kept_descs.append(normalized)

        if not dup_ids:
            return 0

        try:
            self.tix.issue_done_ids(dup_ids)
            logger.info(
                "Deduplicated %d issue(s): %s", len(dup_ids), dup_ids
            )
        except Exception as e:
            logger.warning("Failed to deduplicate issues: %s", e)
            return 0

        return len(dup_ids)

    # =========================================================================
    # Iteration dispatch
    # =========================================================================

    def run_iteration(self, iteration: int) -> tuple[bool, bool]:
        """Run a single iteration of the construct loop.

        Args:
            iteration: Current iteration number

        Returns:
            Tuple of (should_continue, spec_complete)
        """
        # Refresh ticket cache once per iteration (replaces 8-12 subprocess calls)
        self._refresh_ticket_cache()
        state = self.load_state()

        if not state.spec:
            return False, False

        if state.stage == "COMPLETE":
            return False, True

        # Check for progress stall
        progress_interval = getattr(
            self.config, "progress_check_interval", 0
        )
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
        if state.stage == "INVESTIGATE":
            return self._run_investigate(state)
        if state.stage == "BUILD":
            return self._run_build(state)
        if state.stage == "VERIFY":
            return self._run_verify(state)

        # Unknown or PLAN stage — compute from ticket state
        state.stage = self._compute_initial_stage()
        self.save_state(state)
        return True, False

    def _compute_initial_stage(self) -> str:
        """Compute initial stage from ticket state (migration helper)."""
        if self._has_done_tasks():
            return "VERIFY"
        if self._has_issues():
            return "INVESTIGATE"
        if self._has_pending_tasks():
            return "BUILD"
        return "COMPLETE"

    def _run_decompose(self, state: "RalphState") -> tuple[bool, bool]:
        """Run DECOMPOSE stage. Transitions to BUILD on completion."""
        self._run_stage_with_state(Stage.DECOMPOSE, state)

        state = self.load_state()
        state.transition_to_build()
        self.save_state(state)
        return True, False

    def _run_investigate(self, state: "RalphState") -> tuple[bool, bool]:
        """Run INVESTIGATE stage with bounded batching."""
        deduped = self._deduplicate_issues()
        if deduped > 0:
            self._invalidate_ticket_cache()
        issue_ids = self._get_issue_ids()
        if issue_ids:
            batch_size = self._effective_batch_size(
                self.config.investigate_batch_size
            )

            max_batch_iters = len(issue_ids) + 10
            batch_iter = 0
            while True:
                batch_iter += 1
                if batch_iter > max_batch_iters:
                    state._clear_batch_state()
                    break

                batch = state.get_next_batch(issue_ids, batch_size)
                if not batch:
                    break

                self.save_state(state)
                result = self._run_stage_with_state(
                    Stage.INVESTIGATE, state
                )

                if result.outcome == StageOutcome.FAILURE:
                    if state.mark_batch_failed(max_retries=2):
                        self.save_state(state)
                        continue
                    return self._handle_batch_failure(
                        result, state, "INVESTIGATE"
                    )

                state.mark_batch_complete()
                self._batch_failure_count = 0
                state = self.load_state()
                issue_ids = self._get_issue_ids()
        else:
            state._clear_batch_state()

        # INVESTIGATE -> BUILD
        state.transition_to_build()
        self.save_state(state)
        return True, False

    def _run_build(self, state: "RalphState") -> tuple[bool, bool]:
        """Run BUILD stage. Transitions to VERIFY."""
        escalated = self._escalate_stuck_tasks()
        if escalated > 0:
            self._invalidate_ticket_cache()

        if self._has_pending_tasks():
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
        done_ids = self._get_done_task_ids()
        if done_ids:
            result = self._process_verify_batches(state, done_ids)
            if result is not None:
                return result

        return self._finalize_verify_stage()

    def _process_verify_batches(
        self,
        state: "RalphState",
        done_task_ids: list[str],
    ) -> Optional[tuple[bool, bool]]:
        """Process VERIFY in batches."""
        batch_size = self._effective_batch_size(
            self.config.verify_batch_size
        )

        max_batch_iters = len(done_task_ids) + 10
        batch_iter = 0
        while True:
            batch_iter += 1
            if batch_iter > max_batch_iters:
                state._clear_batch_state()
                return None

            batch = state.get_next_batch(done_task_ids, batch_size)
            if not batch:
                return None

            self.save_state(state)
            result = self._run_stage_with_state(Stage.VERIFY, state)

            if result.outcome == StageOutcome.FAILURE:
                if state.mark_batch_failed(max_retries=2):
                    self.save_state(state)
                    continue
                return self._handle_batch_failure(
                    result, state, "VERIFY"
                )

            state.mark_batch_complete()
            self._batch_failure_count = 0
            state = self.load_state()
            done_task_ids = self._get_done_task_ids()

        return None

    def _finalize_verify_stage(self) -> tuple[bool, bool]:
        """Route after VERIFY based on what work remains."""
        state = self.load_state()

        if self._has_issues():
            state.transition_to_investigate()
            self.save_state(state)
            return True, False

        if self._has_pending_tasks() or self._has_done_tasks():
            state.transition_to_build()
            self.save_state(state)
            return True, False

        state.transition_to_complete()
        self.save_state(state)
        return False, True

    def _run_stage_with_state(
        self, stage: Stage, state: "RalphState"
    ) -> StageResult:
        """Run a stage and return the result."""
        result = self.run_stage(
            self.config,
            stage,
            state,
            self.metrics,
            self.stage_timeout_ms,
            self.context_limit,
        )

        # Invalidate cache after any stage run (agent may have mutated tickets)
        self._invalidate_ticket_cache()

        if self.loop_detector and result.outcome == StageOutcome.SUCCESS:
            # Include ticket state in fingerprint so runs on different
            # tasks/issues don't hash identically (false-positive loop).
            output_repr = self._loop_fingerprint(stage)
            if self.loop_detector.check_output(output_repr):
                self.metrics.kills_loop += 1
                self.metrics.last_kill_reason = "loop_detected"
                return StageResult(
                    stage=stage,
                    outcome=StageOutcome.FAILURE,
                    exit_code=-2,
                    duration_seconds=result.duration_seconds,
                    error="Loop detected",
                    kill_reason="loop_detected",
                )

        if result.outcome == StageOutcome.SUCCESS:
            self.metrics.successes += 1
            self.metrics.record_progress()
        elif result.outcome == StageOutcome.FAILURE:
            self.metrics.failures += 1

        return result

    def _handle_task_failure(self, result: StageResult) -> None:
        """Handle a BUILD task failure.

        If the task is at max decompose depth, create an issue instead
        of decomposing further. Otherwise, transition to DECOMPOSE.
        """
        state = self.load_state()
        target_task_id = result.task_id or "__stage_failure__"
        reason = result.kill_reason or "unknown"

        # Check decompose depth limit before entering DECOMPOSE
        max_depth = getattr(self.config, "max_decompose_depth", 3)
        task_depth = self._get_task_depth(target_task_id)

        if task_depth >= max_depth:
            logger.warning(
                "Task %s at max decompose depth %d/%d — "
                "creating issue instead of decomposing",
                target_task_id, task_depth, max_depth,
            )
            if self.tix:
                try:
                    self.tix.issue_add(
                        f"Task {target_task_id} failed (reason: {reason}) "
                        f"and cannot be decomposed further "
                        f"(depth {task_depth}/{max_depth})"
                    )
                    self.tix.task_reject(
                        target_task_id,
                        f"build failed at max depth: {reason}",
                    )
                except Exception:
                    pass
            # Stay in BUILD — the issue will be picked up by INVESTIGATE
            self.save_state(state)
            return

        state.transition_to_decompose(
            task_id=target_task_id,
            reason=reason,
            log_path=result.kill_log,
        )

        # Reset task status to pending via tix and record kill telemetry
        if result.task_id and self.tix:
            try:
                self.tix.task_reject(
                    result.task_id,
                    f"build failed: {reason}",
                )
            except Exception:
                pass  # Best-effort
            # Write kill_count and kill_reason to tix so reports aggregate them
            self._record_kill(result.task_id, reason)

        self.save_state(state)

    def _get_task_depth(self, task_id: str) -> int:
        """Get the decompose_depth of a task (from cache)."""
        if not self.tix or task_id == "__stage_failure__":
            return 0
        full = self._get_cached_full()
        all_tasks = (
            full.get("tasks", {}).get("pending", [])
            + full.get("tasks", {}).get("done", [])
        )
        task = next(
            (t for t in all_tasks if t.get("id") == task_id), None
        )
        return task.get("decompose_depth", 0) if task else 0

    def _record_kill(self, task_id: str, reason: str) -> None:
        """Increment kill_count and set kill_reason on a ticket.

        Writes to tix native fields so ``tix report velocity`` aggregates
        total kills and ``tix report models`` can correlate kills per model.
        Best-effort: failure does not affect state machine flow.
        """
        if not self.tix or task_id == "__stage_failure__":
            return
        try:
            full = self._get_cached_full()
            all_tasks = (
                full.get("tasks", {}).get("pending", [])
                + full.get("tasks", {}).get("done", [])
            )
            task = next(
                (t for t in all_tasks if t.get("id") == task_id), None
            )
            current = task.get("kill_count", 0) if task else 0
            self.tix.task_update(
                task_id,
                {"kill_count": current + 1, "kill_reason": reason},
            )
        except Exception:
            pass

    def _handle_batch_failure(
        self,
        result: StageResult,
        state: "RalphState",
        stage_name: str,
    ) -> tuple[bool, bool]:
        """Handle a batch failure with deterministic recovery.

        1. If no progress has been made recently, abort.
        2. If batch size > 1, halve it and retry.
        3. If batch size is already 1, skip the failing item.
        """
        self._batch_failure_count += 1
        reason = result.kill_reason or "unknown"
        batch_items = list(state.batch_items)

        logger.info(
            "Batch failure #%d in %s: reason=%s, batch_size=%d",
            self._batch_failure_count,
            stage_name,
            reason,
            len(batch_items),
        )

        if self._should_abort_no_progress():
            logger.error(
                "Aborting: %d consecutive batch failures",
                self._batch_failure_count,
            )
            state = self.load_state()
            state._clear_batch_state()
            self.save_state(state)
            return False, False

        if len(batch_items) > 1:
            state = self.load_state()
            state._clear_batch_state()
            if stage_name == "VERIFY":
                state.transition_to_verify()
            else:
                state.transition_to_investigate()
            self.save_state(state)
            return True, False

        # Batch of 1 still failing: skip via tix
        logger.warning(
            "Skipping failing %s item(s): %s (reason: %s)",
            stage_name,
            batch_items,
            reason,
        )
        state = self.load_state()
        self._skip_batch_items(stage_name, batch_items, reason)
        state._clear_batch_state()
        if stage_name == "VERIFY":
            state.transition_to_verify()
        else:
            state.transition_to_investigate()
        self.save_state(state)
        return True, False

    def _should_abort_no_progress(self) -> bool:
        """Check if we should abort due to lack of progress."""
        max_consecutive = getattr(self.config, "max_failures", 3)
        return self._batch_failure_count >= max_consecutive

    def _effective_batch_size(self, configured_size: int) -> int:
        """Return batch size, reduced after failures."""
        if self._batch_failure_count > 0:
            return max(
                1, configured_size // (2**self._batch_failure_count)
            )
        return configured_size

    def _loop_fingerprint(self, stage: Stage) -> str:
        """Build a fingerprint for loop detection from stage + ticket state.

        Includes pending/done/issue IDs so that runs on different tickets
        in the same stage don't hash identically (which would cause
        false-positive loop detection). Uses cached ticket state.
        """
        full = self._get_cached_full()
        pending_ids = sorted(
            t.get("id", "") for t in full.get("tasks", {}).get("pending", [])
        )
        done_ids = sorted(
            t.get("id", "") for t in full.get("tasks", {}).get("done", [])
        )
        issue_ids = sorted(
            i.get("id", "") for i in full.get("issues", [])
        )
        return (
            f"{stage.name}|p={pending_ids}|d={done_ids}|i={issue_ids}"
        )

    def _skip_batch_items(
        self, stage_name: str, items: list, reason: str
    ) -> None:
        """Skip problematic batch items via tix.

        For INVESTIGATE: resolve the failing issues.
        For VERIFY: reject the tasks back to pending.
        """
        if not self.tix:
            return

        try:
            if stage_name == "INVESTIGATE":
                self.tix.issue_done_ids(items)
            elif stage_name == "VERIFY":
                for task_id in items:
                    self.tix.task_reject(
                        task_id, f"verify batch failed: {reason}"
                    )
                    self._record_kill(task_id, reason)
        except Exception as e:
            logger.warning("Failed to skip batch items: %s", e)
