"""Unit tests for harness-level batch failure recovery.

Tests the deterministic batch failure handling in ConstructStateMachine,
which replaced the old RESCUE stage.

Ticket data is provided via MockTix — the state machine queries tix
for routing decisions, not RalphState.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from ralph.commands.construct import (
    _load_spec_content,
    _looks_like_command,
    _pick_best_task,
    _run_acceptance_precheck,
)
from ralph.config import GlobalConfig
from ralph.context import Metrics
from ralph.stages.base import (
    ConstructStateMachine,
    Stage,
    StageOutcome,
    StageResult,
)
from ralph.state import RalphState, load_state, save_state

from ralph.tests.conftest import MockTix as _MockTix


def _write_orch_state(
    repo_root: Path,
    stage: str = "INVESTIGATE",
    spec: str = "test-spec.md",
) -> None:
    """Write orchestration state to .tix/ralph-state.json."""
    state = RalphState(
        spec=spec,
        stage=stage,
    )
    save_state(state, repo_root)


def _make_state_machine(
    repo_root: Path,
    config: GlobalConfig | None = None,
    tix: _MockTix | None = None,
) -> tuple[ConstructStateMachine, list]:
    """Create a state machine with mock stage runner.

    Returns:
        Tuple of (state_machine, stages_run_list).
    """
    config = config or GlobalConfig()
    metrics = Metrics()
    metrics.record_progress()
    stages_run: list[tuple[Stage, int]] = []
    call_count = [0]

    def mock_run_stage(
        cfg, stage, st, met, timeout_ms, ctx_limit
    ) -> StageResult:
        call_count[0] += 1
        stages_run.append((stage, call_count[0]))
        return StageResult(stage=stage, outcome=StageOutcome.SUCCESS)

    sm = ConstructStateMachine(
        config=config,
        metrics=metrics,
        stage_timeout_ms=60000,
        context_limit=100000,
        run_stage_fn=mock_run_stage,
        load_state_fn=lambda: load_state(repo_root),
        save_state_fn=lambda st: save_state(st, repo_root),
        tix=tix,
    )
    return sm, stages_run


class TestBatchFailureRecovery:
    """Tests for _handle_batch_failure deterministic recovery."""

    def test_batch_failure_halves_and_retries(self, tmp_path: Path):
        """When a batch of >1 items fails, halve batch size and retry."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            issues=[{"id": f"i-{i}"} for i in range(4)],
        )
        _write_orch_state(repo_root, stage="INVESTIGATE")

        sm, stages_run = _make_state_machine(repo_root, tix=mock_tix)

        # Set batch state
        state = load_state(repo_root)
        state.batch_items = ["i-0", "i-1", "i-2", "i-3"]
        save_state(state, repo_root)

        result = StageResult(
            stage=Stage.INVESTIGATE,
            outcome=StageOutcome.FAILURE,
            kill_reason="timeout",
        )

        should_continue, spec_complete = sm._handle_batch_failure(
            result, state, "INVESTIGATE"
        )

        assert should_continue is True
        assert spec_complete is False
        assert sm._batch_failure_count == 1

        # State should be cleared for retry
        reloaded = load_state(repo_root)
        assert reloaded.batch_items == []
        assert reloaded.stage == "INVESTIGATE"

    def test_batch_failure_skips_single_item(self, tmp_path: Path):
        """When a batch of 1 item fails, skip it via tix."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            issues=[
                {"id": "i-bad"},
                {"id": "i-good"},
            ],
        )
        _write_orch_state(repo_root, stage="INVESTIGATE")

        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        state = load_state(repo_root)
        state.batch_items = ["i-bad"]
        save_state(state, repo_root)

        result = StageResult(
            stage=Stage.INVESTIGATE,
            outcome=StageOutcome.FAILURE,
            kill_reason="context_limit",
        )

        should_continue, _ = sm._handle_batch_failure(
            result, state, "INVESTIGATE"
        )

        assert should_continue is True
        # Tix should have resolved the bad issue
        assert mock_tix.resolved_ids == [["i-bad"]]
        # Only good issue remains in mock
        assert len(mock_tix._issues) == 1
        assert mock_tix._issues[0]["id"] == "i-good"

    def test_batch_failure_verify_rejects_task(self, tmp_path: Path):
        """When a single verify batch item fails, task is rejected via tix."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            done=[{"id": "t-fail", "name": "Failing task"}],
        )
        _write_orch_state(repo_root, stage="VERIFY")

        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        state = load_state(repo_root)
        state.batch_items = ["t-fail"]
        save_state(state, repo_root)

        result = StageResult(
            stage=Stage.VERIFY,
            outcome=StageOutcome.FAILURE,
            kill_reason="timeout",
        )

        sm._handle_batch_failure(result, state, "VERIFY")

        # Tix should have rejected the task
        assert len(mock_tix.rejected) == 1
        assert mock_tix.rejected[0][0] == "t-fail"
        assert "verify batch failed" in mock_tix.rejected[0][1]

    def test_batch_failure_aborts_after_max_consecutive(
        self, tmp_path: Path
    ):
        """After max_failures consecutive batch failures, abort."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(issues=[{"id": "i-1"}])
        _write_orch_state(repo_root, stage="INVESTIGATE")

        config = GlobalConfig(max_failures=3)
        sm, _ = _make_state_machine(repo_root, config=config, tix=mock_tix)

        state = load_state(repo_root)
        state.batch_items = ["i-1"]
        save_state(state, repo_root)

        result = StageResult(
            stage=Stage.INVESTIGATE,
            outcome=StageOutcome.FAILURE,
            kill_reason="timeout",
        )

        # First two failures should continue (halve / skip)
        sm._handle_batch_failure(result, state, "INVESTIGATE")
        sm._handle_batch_failure(result, state, "INVESTIGATE")

        # Third should abort
        should_continue, spec_complete = sm._handle_batch_failure(
            result, state, "INVESTIGATE"
        )
        assert should_continue is False
        assert spec_complete is False

    def test_effective_batch_size_reduces_after_failure(
        self, tmp_path: Path
    ):
        """Batch size should be reduced after failures."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)
        _write_orch_state(repo_root)

        sm, _ = _make_state_machine(repo_root)

        # No failures: full size
        assert sm._effective_batch_size(8) == 8

        # After 1 failure: halved
        sm._batch_failure_count = 1
        assert sm._effective_batch_size(8) == 4

        # After 2 failures: quartered
        sm._batch_failure_count = 2
        assert sm._effective_batch_size(8) == 2

        # After 3 failures: minimum 1
        sm._batch_failure_count = 3
        assert sm._effective_batch_size(8) == 1

        # Never goes below 1
        sm._batch_failure_count = 10
        assert sm._effective_batch_size(8) == 1

    def test_batch_failure_count_resets_on_success(self, tmp_path: Path):
        """Batch failure count resets after a successful batch."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        # Start with issues so INVESTIGATE has work, then tasks for BUILD
        mock_tix = _MockTix(
            issues=[{"id": "i-1"}],
            tasks=[{"id": "t-1"}],
        )
        _write_orch_state(repo_root, stage="INVESTIGATE")

        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        # Simulate a prior failure
        sm._batch_failure_count = 2

        # Running a successful investigate iteration should reset it
        sm.run_iteration(1)

        assert sm._batch_failure_count == 0


class TestLegacyRescueMigration:
    """Test that old state files with RESCUE stage are migrated."""

    def test_rescue_stage_migrates_to_investigate(self, tmp_path: Path):
        """Loading state with stage=RESCUE migrates to INVESTIGATE."""
        repo_root = tmp_path
        tix_dir = repo_root / ".tix"
        tix_dir.mkdir(parents=True, exist_ok=True)

        state_file = tix_dir / "ralph-state.json"
        state_file.write_text(json.dumps({
            "stage": "RESCUE",
            "spec": "test-spec.md",
        }))

        state = load_state(repo_root)
        assert state.stage == "INVESTIGATE"


def _make_fingerprint_sm(tix: _MockTix) -> ConstructStateMachine:
    """Create a minimal state machine for fingerprint testing."""
    config = GlobalConfig()
    metrics = Metrics()
    metrics.record_progress()
    return ConstructStateMachine(
        config=config,
        metrics=metrics,
        stage_timeout_ms=60000,
        context_limit=100000,
        run_stage_fn=lambda *a: StageResult(
            stage=Stage.BUILD, outcome=StageOutcome.SUCCESS
        ),
        load_state_fn=lambda: RalphState(spec="s.md"),
        save_state_fn=lambda st: None,
        tix=tix,
    )


class TestLoopFingerprint:
    """Tests for ConstructStateMachine._loop_fingerprint."""

    def test_different_tasks_produce_different_fingerprints(self):
        """Two tix states with different pending tasks should not match."""
        sm_a = _make_fingerprint_sm(
            _MockTix(tasks=[{"id": "t-1"}])
        )
        sm_b = _make_fingerprint_sm(
            _MockTix(tasks=[{"id": "t-2"}])
        )
        fp_a = sm_a._loop_fingerprint(Stage.BUILD)
        fp_b = sm_b._loop_fingerprint(Stage.BUILD)
        assert fp_a != fp_b

    def test_same_state_produces_same_fingerprint(self):
        """Identical tix state should produce identical fingerprint."""
        tix = _MockTix(tasks=[{"id": "t-1"}])
        sm = _make_fingerprint_sm(tix)
        fp1 = sm._loop_fingerprint(Stage.BUILD)
        fp2 = sm._loop_fingerprint(Stage.BUILD)
        assert fp1 == fp2

    def test_fingerprint_includes_issues(self):
        """Issues should affect the fingerprint."""
        sm_no = _make_fingerprint_sm(_MockTix())
        sm_yes = _make_fingerprint_sm(
            _MockTix(issues=[{"id": "i-1"}])
        )
        fp_a = sm_no._loop_fingerprint(Stage.INVESTIGATE)
        fp_b = sm_yes._loop_fingerprint(Stage.INVESTIGATE)
        assert fp_a != fp_b

    def test_fingerprint_differs_by_stage(self):
        """Same tix state but different stage enum should differ."""
        tix = _MockTix(done=[{"id": "t-1"}])
        sm = _make_fingerprint_sm(tix)
        fp_build = sm._loop_fingerprint(Stage.BUILD)
        fp_verify = sm._loop_fingerprint(Stage.VERIFY)
        assert fp_build != fp_verify


class TestDecomposeDepthGuard:
    """Tests for decompose depth enforcement in _handle_task_failure."""

    def test_allows_decompose_below_max_depth(self, tmp_path: Path):
        """Task at depth 0 with max_depth 3 should transition to DECOMPOSE."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            tasks=[{"id": "t-1", "decompose_depth": 0}],
        )
        _write_orch_state(repo_root, stage="BUILD")

        config = GlobalConfig()
        config.max_decompose_depth = 3
        sm, _ = _make_state_machine(repo_root, config=config, tix=mock_tix)

        result = StageResult(
            stage=Stage.BUILD,
            outcome=StageOutcome.FAILURE,
            task_id="t-1",
            kill_reason="timeout",
        )
        sm._handle_task_failure(result)

        state = load_state(repo_root)
        assert state.stage == "DECOMPOSE"
        assert state.decompose_target == "t-1"

    def test_blocks_decompose_at_max_depth(self, tmp_path: Path):
        """Task at max depth should NOT decompose — creates issue instead."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            tasks=[{"id": "t-deep", "decompose_depth": 3}],
        )
        _write_orch_state(repo_root, stage="BUILD")

        config = GlobalConfig()
        config.max_decompose_depth = 3
        sm, _ = _make_state_machine(repo_root, config=config, tix=mock_tix)

        result = StageResult(
            stage=Stage.BUILD,
            outcome=StageOutcome.FAILURE,
            task_id="t-deep",
            kill_reason="context_limit",
        )
        sm._handle_task_failure(result)

        # Should stay in BUILD, not transition to DECOMPOSE
        state = load_state(repo_root)
        assert state.stage == "BUILD"
        assert state.decompose_target is None

        # Should have created an issue
        assert len(mock_tix._issues) == 1
        assert "t-deep" in mock_tix._issues[0]["desc"]
        assert "context_limit" in mock_tix._issues[0]["desc"]

        # Should have rejected the task
        assert len(mock_tix.rejected) == 1
        assert mock_tix.rejected[0][0] == "t-deep"

    def test_get_task_depth_returns_zero_for_unknown(self, tmp_path: Path):
        """Unknown task ID returns depth 0."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)
        _write_orch_state(repo_root, stage="BUILD")

        mock_tix = _MockTix(tasks=[{"id": "t-1"}])
        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        assert sm._get_task_depth("t-nonexistent") == 0

    def test_get_task_depth_reads_from_tix(self, tmp_path: Path):
        """Depth is read from the task's decompose_depth field."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)
        _write_orch_state(repo_root, stage="BUILD")

        mock_tix = _MockTix(
            tasks=[{"id": "t-1", "decompose_depth": 2}],
        )
        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        assert sm._get_task_depth("t-1") == 2


class TestPickBestTask:
    """Tests for _pick_best_task priority selection."""

    def test_picks_high_priority_first(self):
        tasks = [
            {"id": "t-low", "name": "Low", "priority": "low"},
            {"id": "t-high", "name": "High", "priority": "high"},
            {"id": "t-med", "name": "Medium", "priority": "medium"},
        ]
        best = _pick_best_task(tasks)
        assert best["id"] == "t-high"

    def test_picks_medium_over_low(self):
        tasks = [
            {"id": "t-low", "name": "Low", "priority": "low"},
            {"id": "t-med", "name": "Medium", "priority": "medium"},
        ]
        best = _pick_best_task(tasks)
        assert best["id"] == "t-med"

    def test_unset_priority_is_lowest(self):
        tasks = [
            {"id": "t-none", "name": "No prio"},
            {"id": "t-low", "name": "Low", "priority": "low"},
        ]
        best = _pick_best_task(tasks)
        assert best["id"] == "t-low"

    def test_prefers_fewer_rejections(self):
        tasks = [
            {"id": "t-retry", "name": "Retried", "priority": "high"},
            {"id": "t-fresh", "name": "Fresh", "priority": "high"},
        ]
        retry_counts = {"t-retry": 2, "t-fresh": 0}
        best = _pick_best_task(tasks, retry_counts=retry_counts)
        assert best["id"] == "t-fresh"

    def test_priority_trumps_reject_count(self):
        tasks = [
            {"id": "t-low-fresh", "name": "Low fresh", "priority": "low"},
            {"id": "t-high-retry", "name": "High retry", "priority": "high"},
        ]
        retry_counts = {"t-low-fresh": 0, "t-high-retry": 2}
        best = _pick_best_task(tasks, retry_counts=retry_counts)
        assert best["id"] == "t-high-retry"

    def test_single_task(self):
        tasks = [{"id": "t-1", "name": "Only one"}]
        best = _pick_best_task(tasks)
        assert best["id"] == "t-1"

    def test_preserves_order_on_tie(self):
        tasks = [
            {"id": "t-first", "name": "First"},
            {"id": "t-second", "name": "Second"},
        ]
        best = _pick_best_task(tasks)
        assert best["id"] == "t-first"

    def test_deprioritizes_unmet_deps(self):
        """Task with deps still in pending list sorts last."""
        tasks = [
            {"id": "t-blocked", "name": "Blocked",
             "priority": "high", "deps": ["t-dep"]},
            {"id": "t-dep", "name": "Dependency", "priority": "medium"},
        ]
        best = _pick_best_task(tasks)
        assert best["id"] == "t-dep"

    def test_met_deps_not_penalized(self):
        """Task whose deps are NOT in pending list is not penalized."""
        tasks = [
            {"id": "t-ready", "name": "Ready",
             "priority": "high", "deps": ["t-done"]},
            {"id": "t-other", "name": "Other", "priority": "medium"},
        ]
        # t-done is not in the pending list, so dep is met
        best = _pick_best_task(tasks)
        assert best["id"] == "t-ready"

    def test_deps_override_priority(self):
        """Unmet deps override higher priority."""
        tasks = [
            {"id": "t-high-blocked", "name": "High blocked",
             "priority": "high", "deps": ["t-low-ready"]},
            {"id": "t-low-ready", "name": "Low ready",
             "priority": "low"},
        ]
        best = _pick_best_task(tasks)
        assert best["id"] == "t-low-ready"

    def test_empty_deps_treated_as_no_deps(self):
        """Task with empty deps list is not penalized."""
        tasks = [
            {"id": "t-empty", "name": "Empty deps",
             "priority": "high", "deps": []},
            {"id": "t-none", "name": "No deps", "priority": "medium"},
        ]
        best = _pick_best_task(tasks)
        assert best["id"] == "t-empty"

    def test_none_deps_treated_as_no_deps(self):
        """Task with deps=None is not penalized."""
        tasks = [
            {"id": "t-null", "name": "Null deps",
             "priority": "high", "deps": None},
            {"id": "t-other", "name": "Other", "priority": "medium"},
        ]
        best = _pick_best_task(tasks)
        assert best["id"] == "t-null"

    def test_multiple_blocked_picks_best_unblocked(self):
        """With multiple blocked tasks, picks best unblocked one."""
        tasks = [
            {"id": "t-a", "name": "A", "priority": "high",
             "deps": ["t-c"]},
            {"id": "t-b", "name": "B", "priority": "low"},
            {"id": "t-c", "name": "C", "priority": "medium",
             "deps": ["t-b"]},
        ]
        # t-b is the only unblocked task
        best = _pick_best_task(tasks)
        assert best["id"] == "t-b"

    def test_all_blocked_picks_best_by_priority(self):
        """When all tasks are blocked, still picks by priority."""
        tasks = [
            {"id": "t-a", "name": "A", "priority": "low",
             "deps": ["t-b"]},
            {"id": "t-b", "name": "B", "priority": "high",
             "deps": ["t-a"]},
        ]
        # Both blocked — pick by priority among blocked
        best = _pick_best_task(tasks)
        assert best["id"] == "t-b"


class TestEscalateStuckTasks:
    """Tests for _escalate_stuck_tasks pattern detection."""

    def test_escalates_task_at_max_retries(self, tmp_path: Path):
        """Task with retries >= max is escalated to issue."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            tasks=[
                {"id": "t-stuck", "name": "Stuck task",
                 "reject": "test fails"},
            ],
        )
        _write_orch_state(repo_root, stage="BUILD")
        config = GlobalConfig()
        config.max_retries_per_task = 3
        sm, _ = _make_state_machine(repo_root, config=config, tix=mock_tix)
        # Populate in-memory retry count
        sm._retry_counts["t-stuck"] = 3

        escalated = sm._escalate_stuck_tasks()
        assert escalated == 1
        # Should have created an issue
        assert len(mock_tix._issues) == 1
        assert "t-stuck" in mock_tix._issues[0]["desc"]
        assert "3 times" in mock_tix._issues[0]["desc"]

    def test_leaves_task_below_threshold(self, tmp_path: Path):
        """Task with retries below max is left alone."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            tasks=[
                {"id": "t-retry", "name": "Retry task",
                 "reject": "test fails"},
            ],
        )
        _write_orch_state(repo_root, stage="BUILD")
        config = GlobalConfig()
        config.max_retries_per_task = 3
        sm, _ = _make_state_machine(repo_root, config=config, tix=mock_tix)
        # Populate in-memory retry count below threshold
        sm._retry_counts["t-retry"] = 1

        escalated = sm._escalate_stuck_tasks()
        assert escalated == 0
        assert len(mock_tix._issues) == 0

    def test_no_retries_field_skipped(self, tmp_path: Path):
        """Tasks without in-memory retries are treated as fresh."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            tasks=[{"id": "t-fresh", "name": "Fresh task"}],
        )
        _write_orch_state(repo_root, stage="BUILD")
        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        escalated = sm._escalate_stuck_tasks()
        assert escalated == 0

    def test_no_tix_returns_zero(self, tmp_path: Path):
        """No tix instance returns 0."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)
        _write_orch_state(repo_root, stage="BUILD")
        sm, _ = _make_state_machine(repo_root, tix=None)

        escalated = sm._escalate_stuck_tasks()
        assert escalated == 0

    def test_mixed_tasks(self, tmp_path: Path):
        """Only stuck tasks are escalated; others untouched."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            tasks=[
                {"id": "t-ok", "name": "OK task"},
                {"id": "t-stuck", "name": "Stuck",
                 "reject": "fails"},
                {"id": "t-retry", "name": "Retry",
                 "reject": "fails"},
            ],
        )
        _write_orch_state(repo_root, stage="BUILD")
        config = GlobalConfig()
        config.max_retries_per_task = 3
        sm, _ = _make_state_machine(repo_root, config=config, tix=mock_tix)
        # Set in-memory retry counts
        sm._retry_counts["t-ok"] = 0
        sm._retry_counts["t-stuck"] = 5
        sm._retry_counts["t-retry"] = 2

        escalated = sm._escalate_stuck_tasks()
        assert escalated == 1
        assert len(mock_tix._issues) == 1
        assert "t-stuck" in mock_tix._issues[0]["desc"]


class TestIssueDeduplicate:
    """Tests for _deduplicate_issues in ConstructStateMachine."""

    def test_deduplicates_exact_match(self, tmp_path: Path):
        """Identical issue descriptions are deduplicated."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            issues=[
                {"id": "i-1", "desc": "test failure in module X"},
                {"id": "i-2", "desc": "test failure in module X"},
                {"id": "i-3", "desc": "different issue"},
            ],
        )
        _write_orch_state(repo_root, stage="INVESTIGATE")
        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        removed = sm._deduplicate_issues()
        assert removed == 1
        assert mock_tix.resolved_ids == [["i-2"]]
        # 2 issues should remain
        assert len(mock_tix._issues) == 2

    def test_deduplicates_case_insensitive(self, tmp_path: Path):
        """Case-insensitive matching catches duplicates."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            issues=[
                {"id": "i-1", "desc": "Test Failure"},
                {"id": "i-2", "desc": "test failure"},
            ],
        )
        _write_orch_state(repo_root, stage="INVESTIGATE")
        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        removed = sm._deduplicate_issues()
        assert removed == 1

    def test_deduplicates_whitespace_collapse(self, tmp_path: Path):
        """Extra whitespace does not create false unique issues."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            issues=[
                {"id": "i-1", "desc": "test  failure  in  X"},
                {"id": "i-2", "desc": "test failure in X"},
            ],
        )
        _write_orch_state(repo_root, stage="INVESTIGATE")
        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        removed = sm._deduplicate_issues()
        assert removed == 1

    def test_no_duplicates_no_change(self, tmp_path: Path):
        """Unique issues are left untouched."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            issues=[
                {"id": "i-1", "desc": "issue A"},
                {"id": "i-2", "desc": "issue B"},
            ],
        )
        _write_orch_state(repo_root, stage="INVESTIGATE")
        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        removed = sm._deduplicate_issues()
        assert removed == 0
        assert mock_tix.resolved_ids == []

    def test_single_issue_skipped(self, tmp_path: Path):
        """Single issue does not need dedup."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(issues=[{"id": "i-1", "desc": "only one"}])
        _write_orch_state(repo_root, stage="INVESTIGATE")
        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        removed = sm._deduplicate_issues()
        assert removed == 0

    def test_no_tix_returns_zero(self, tmp_path: Path):
        """No tix instance returns 0."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)
        _write_orch_state(repo_root, stage="INVESTIGATE")
        sm, _ = _make_state_machine(repo_root, tix=None)

        removed = sm._deduplicate_issues()
        assert removed == 0

    def test_multiple_duplicates(self, tmp_path: Path):
        """Three identical issues reduce to one."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            issues=[
                {"id": "i-1", "desc": "same issue"},
                {"id": "i-2", "desc": "same issue"},
                {"id": "i-3", "desc": "same issue"},
            ],
        )
        _write_orch_state(repo_root, stage="INVESTIGATE")
        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        removed = sm._deduplicate_issues()
        assert removed == 2
        assert len(mock_tix._issues) == 1
        assert mock_tix._issues[0]["id"] == "i-1"


class TestTokenSimilarity:
    """Tests for _token_similarity Jaccard helper."""

    def test_identical_strings(self):
        assert ConstructStateMachine._token_similarity(
            "test failure in module x", "test failure in module x"
        ) == 1.0

    def test_completely_different(self):
        assert ConstructStateMachine._token_similarity(
            "alpha beta gamma", "delta epsilon zeta"
        ) == 0.0

    def test_partial_overlap(self):
        # "test failure in x" vs "test failure in module x"
        # tokens_a = {test, failure, in, x} (4)
        # tokens_b = {test, failure, in, module, x} (5)
        # intersection = 4, union = 5  =>  0.8
        sim = ConstructStateMachine._token_similarity(
            "test failure in x", "test failure in module x"
        )
        assert sim == pytest.approx(0.8)

    def test_word_reorder(self):
        # Same words, different order => 1.0 (set-based)
        sim = ConstructStateMachine._token_similarity(
            "module x test failure", "test failure module x"
        )
        assert sim == 1.0

    def test_both_empty(self):
        assert ConstructStateMachine._token_similarity("", "") == 1.0

    def test_one_empty(self):
        assert ConstructStateMachine._token_similarity("", "word") == 0.0
        assert ConstructStateMachine._token_similarity("word", "") == 0.0

    def test_single_word_match(self):
        assert ConstructStateMachine._token_similarity(
            "failure", "failure"
        ) == 1.0

    def test_superset_subset(self):
        # {a, b} vs {a, b, c} => 2/3
        sim = ConstructStateMachine._token_similarity("a b", "a b c")
        assert sim == pytest.approx(2.0 / 3.0)


class TestFuzzyIssueDeduplicate:
    """Tests for fuzzy deduplication in _deduplicate_issues."""

    def test_fuzzy_near_duplicate(self, tmp_path: Path):
        """Near-duplicate issues (word reorder) are deduplicated."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            issues=[
                {"id": "i-1", "desc": "test failure in module X"},
                {"id": "i-2", "desc": "test failure in X module"},
            ],
        )
        _write_orch_state(repo_root, stage="INVESTIGATE")
        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        removed = sm._deduplicate_issues()
        assert removed == 1
        assert len(mock_tix._issues) == 1
        assert mock_tix._issues[0]["id"] == "i-1"

    def test_fuzzy_missing_word(self, tmp_path: Path):
        """Issue missing one word still matches at 0.8 threshold."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        # "test failure in x" vs "test failure in module x"
        # Jaccard = 4/5 = 0.8 => dedup at default threshold
        mock_tix = _MockTix(
            issues=[
                {"id": "i-1", "desc": "test failure in module X"},
                {"id": "i-2", "desc": "test failure in X"},
            ],
        )
        _write_orch_state(repo_root, stage="INVESTIGATE")
        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        removed = sm._deduplicate_issues()
        assert removed == 1

    def test_fuzzy_below_threshold_kept(self, tmp_path: Path):
        """Issues below similarity threshold are kept separate."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        # "test failure" vs "build error in module" => 0 overlap
        mock_tix = _MockTix(
            issues=[
                {"id": "i-1", "desc": "test failure"},
                {"id": "i-2", "desc": "build error in module"},
            ],
        )
        _write_orch_state(repo_root, stage="INVESTIGATE")
        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        removed = sm._deduplicate_issues()
        assert removed == 0
        assert len(mock_tix._issues) == 2

    def test_fuzzy_disabled_at_threshold_1(self, tmp_path: Path):
        """Threshold=1.0 disables fuzzy matching (exact only)."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            issues=[
                {"id": "i-1", "desc": "test failure in module X"},
                {"id": "i-2", "desc": "test failure in X module"},
            ],
        )
        _write_orch_state(repo_root, stage="INVESTIGATE")
        config = GlobalConfig()
        config.issue_similarity_threshold = 1.0
        sm, _ = _make_state_machine(repo_root, config=config, tix=mock_tix)

        removed = sm._deduplicate_issues()
        assert removed == 0  # word reorder not caught at threshold 1.0

    def test_fuzzy_with_exact_and_near(self, tmp_path: Path):
        """Mix of exact and near duplicates all resolved."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            issues=[
                {"id": "i-1", "desc": "test failure in module X"},
                {"id": "i-2", "desc": "test failure in module X"},  # exact
                {"id": "i-3", "desc": "test failure in X module"},  # fuzzy
                {"id": "i-4", "desc": "completely different issue"},
            ],
        )
        _write_orch_state(repo_root, stage="INVESTIGATE")
        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        removed = sm._deduplicate_issues()
        assert removed == 2
        remaining = [i["id"] for i in mock_tix._issues]
        assert "i-1" in remaining
        assert "i-4" in remaining

    def test_fuzzy_three_near_duplicates(self, tmp_path: Path):
        """Three near-duplicate issues reduce to one."""
        repo_root = tmp_path
        (repo_root / ".tix").mkdir(parents=True, exist_ok=True)

        mock_tix = _MockTix(
            issues=[
                {"id": "i-1", "desc": "error compiling main module"},
                {"id": "i-2", "desc": "error compiling module main"},
                {"id": "i-3", "desc": "compiling error main module"},
            ],
        )
        _write_orch_state(repo_root, stage="INVESTIGATE")
        sm, _ = _make_state_machine(repo_root, tix=mock_tix)

        removed = sm._deduplicate_issues()
        assert removed == 2
        assert mock_tix._issues[0]["id"] == "i-1"


class TestLooksLikeCommand:
    """Tests for _looks_like_command heuristic."""

    def test_pytest_command(self):
        assert _looks_like_command("pytest tests/") is True

    def test_make_command(self):
        assert _looks_like_command("make test") is True

    def test_go_test_command(self):
        assert _looks_like_command("go test ./...") is True

    def test_shell_pipe(self):
        assert _looks_like_command("grep -c 'pattern' file | head") is True

    def test_shell_and_operator(self):
        assert _looks_like_command("make build && make test") is True

    def test_redirect(self):
        assert _looks_like_command("echo foo > /dev/null") is True

    def test_relative_path(self):
        assert _looks_like_command("./run_tests.sh") is True

    def test_prose_description(self):
        assert _looks_like_command("works correctly") is False

    def test_prose_sentence(self):
        assert _looks_like_command("All tests should pass") is False

    def test_empty_string(self):
        assert _looks_like_command("") is False

    def test_whitespace_only(self):
        assert _looks_like_command("   ") is False

    def test_npm_command(self):
        assert _looks_like_command("npm test") is True

    def test_cargo_command(self):
        assert _looks_like_command("cargo test") is True


class TestAcceptancePrecheck:
    """Tests for _run_acceptance_precheck deterministic pre-check."""

    def test_auto_accepts_passing_command(self, tmp_path: Path):
        """Task with passing accept command is auto-accepted."""
        mock_tix = _MockTix(
            done=[{"id": "t-1", "name": "Task", "accept": "bash -c 'exit 0'"}],
        )
        accepted = _run_acceptance_precheck(mock_tix, tmp_path)
        assert accepted == 1
        # Task should be removed from done list
        assert len(mock_tix._done) == 0

    def test_skips_failing_command(self, tmp_path: Path):
        """Task with failing accept command is left for agent."""
        mock_tix = _MockTix(
            done=[{"id": "t-1", "name": "Task", "accept": "bash -c 'exit 1'"}],
        )
        accepted = _run_acceptance_precheck(mock_tix, tmp_path)
        assert accepted == 0
        # Task should still be in done list
        assert len(mock_tix._done) == 1

    def test_skips_prose_accept(self, tmp_path: Path):
        """Task with prose accept criteria is left for agent."""
        mock_tix = _MockTix(
            done=[{"id": "t-1", "name": "Task", "accept": "works correctly"}],
        )
        accepted = _run_acceptance_precheck(mock_tix, tmp_path)
        assert accepted == 0

    def test_skips_empty_accept(self, tmp_path: Path):
        """Task with no accept field is left for agent."""
        mock_tix = _MockTix(
            done=[{"id": "t-1", "name": "Task"}],
        )
        accepted = _run_acceptance_precheck(mock_tix, tmp_path)
        assert accepted == 0

    def test_mixed_tasks(self, tmp_path: Path):
        """Mix of passing, failing, and prose tasks."""
        mock_tix = _MockTix(
            done=[
                {"id": "t-pass", "name": "Pass", "accept": "bash -c 'exit 0'"},
                {"id": "t-fail", "name": "Fail", "accept": "bash -c 'exit 1'"},
                {"id": "t-prose", "name": "Prose", "accept": "looks good"},
            ],
        )
        accepted = _run_acceptance_precheck(mock_tix, tmp_path)
        assert accepted == 1
        # Only t-pass should be removed
        remaining_ids = [t["id"] for t in mock_tix._done]
        assert "t-pass" not in remaining_ids
        assert "t-fail" in remaining_ids
        assert "t-prose" in remaining_ids

    def test_returns_zero_on_no_done_tasks(self, tmp_path: Path):
        """Returns 0 when there are no done tasks."""
        mock_tix = _MockTix(done=[])
        accepted = _run_acceptance_precheck(mock_tix, tmp_path)
        assert accepted == 0

    @patch("ralph.commands.construct.subprocess.run")
    def test_handles_timeout(self, mock_subprocess, tmp_path: Path):
        """Timed-out commands are skipped (left for agent)."""
        import subprocess as sp
        mock_subprocess.side_effect = sp.TimeoutExpired("cmd", 60)
        mock_tix = _MockTix(
            done=[{"id": "t-1", "name": "Task", "accept": "make test"}],
        )
        accepted = _run_acceptance_precheck(mock_tix, tmp_path)
        assert accepted == 0


class TestLoadSpecContent:
    """Tests for _load_spec_content helper."""

    def test_loads_existing_spec(self, tmp_path: Path):
        """Reads spec file content from ralph/specs/."""
        ralph_dir = tmp_path / "ralph"
        specs_dir = ralph_dir / "specs"
        specs_dir.mkdir(parents=True)
        (specs_dir / "feat.md").write_text("# Feature\nDo things.")

        content = _load_spec_content(ralph_dir, "feat.md")
        assert content == "# Feature\nDo things."

    def test_returns_empty_for_missing_spec(self, tmp_path: Path):
        """Missing spec file returns empty string."""
        ralph_dir = tmp_path / "ralph"
        (ralph_dir / "specs").mkdir(parents=True)

        content = _load_spec_content(ralph_dir, "nonexistent.md")
        assert content == ""

    def test_returns_empty_for_empty_name(self, tmp_path: Path):
        """Empty spec name returns empty string."""
        content = _load_spec_content(tmp_path, "")
        assert content == ""

    def test_returns_empty_for_missing_dir(self, tmp_path: Path):
        """Missing specs directory returns empty string."""
        content = _load_spec_content(tmp_path / "nope", "feat.md")
        assert content == ""
