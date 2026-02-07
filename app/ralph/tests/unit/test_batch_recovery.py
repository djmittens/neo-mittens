"""Unit tests for harness-level batch failure recovery.

Tests the deterministic batch failure handling in ConstructStateMachine,
which replaced the old RESCUE stage.

Ticket data is provided via MockTix — the state machine queries tix
for routing decisions, not RalphState.
"""

import json
import pytest
from pathlib import Path

from ralph.config import GlobalConfig
from ralph.context import Metrics
from ralph.models import RalphPlanConfig
from ralph.stages.base import (
    ConstructStateMachine,
    Stage,
    StageOutcome,
    StageResult,
)
from ralph.state import RalphState, load_state, save_state


class _MockTix:
    """Controllable mock for Tix that returns configured ticket data."""

    def __init__(
        self,
        tasks: list | None = None,
        done: list | None = None,
        issues: list | None = None,
    ):
        self._tasks = tasks or []
        self._done = done or []
        self._issues = issues or []
        self.rejected: list[tuple[str, str]] = []
        self.resolved_ids: list[list[str]] = []

    def query_tasks(self) -> list[dict]:
        """Return pending tasks."""
        return self._tasks

    def query_done_tasks(self) -> list[dict]:
        """Return done tasks."""
        return self._done

    def query_issues(self) -> list[dict]:
        """Return open issues."""
        return self._issues

    def task_reject(self, task_id: str, reason: str) -> dict:
        """Record a task rejection."""
        self.rejected.append((task_id, reason))
        return {"id": task_id, "status": "p"}

    def issue_done_ids(self, ids: list[str]) -> dict:
        """Record issue resolution and remove from internal list."""
        self.resolved_ids.append(ids)
        self._issues = [i for i in self._issues if i.get("id") not in ids]
        return {"count": len(ids)}


def _write_orch_state(
    plan_path: Path,
    stage: str = "INVESTIGATE",
    spec: str = "test-spec.md",
) -> None:
    """Write an orchestration-only state to plan.jsonl."""
    state = RalphState(
        config=RalphPlanConfig(),
        spec=spec,
        stage=stage,
    )
    save_state(state, plan_path)


def _write_plan_with_tickets(
    plan_path: Path,
    stage: str = "INVESTIGATE",
    spec: str = "test-spec.md",
    task_lines: list[dict] | None = None,
    issue_lines: list[dict] | None = None,
) -> None:
    """Write plan.jsonl with orchestration + ticket lines."""
    orch_state = RalphState(
        config=RalphPlanConfig(),
        spec=spec,
        stage=stage,
    )
    save_state(orch_state, plan_path)

    # Append ticket lines
    with open(plan_path, "a") as f:
        for t in (task_lines or []):
            f.write(json.dumps(t) + "\n")
        for i in (issue_lines or []):
            f.write(json.dumps(i) + "\n")


def _make_state_machine(
    plan_path: Path,
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
        load_state_fn=lambda: load_state(plan_path),
        save_state_fn=lambda st: save_state(st, plan_path),
        tix=tix,
    )
    return sm, stages_run


class TestBatchFailureRecovery:
    """Tests for _handle_batch_failure deterministic recovery."""

    def test_batch_failure_halves_and_retries(self, tmp_path: Path):
        """When a batch of >1 items fails, halve batch size and retry."""
        plan_path = tmp_path / "ralph" / "plan.jsonl"
        plan_path.parent.mkdir(parents=True)

        mock_tix = _MockTix(
            issues=[{"id": f"i-{i}"} for i in range(4)],
        )
        _write_orch_state(plan_path, stage="INVESTIGATE")

        sm, stages_run = _make_state_machine(plan_path, tix=mock_tix)

        # Set batch state
        state = load_state(plan_path)
        state.batch_items = ["i-0", "i-1", "i-2", "i-3"]
        save_state(state, plan_path)

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
        reloaded = load_state(plan_path)
        assert reloaded.batch_items == []
        assert reloaded.stage == "INVESTIGATE"

    def test_batch_failure_skips_single_item(self, tmp_path: Path):
        """When a batch of 1 item fails, skip it via tix."""
        plan_path = tmp_path / "ralph" / "plan.jsonl"
        plan_path.parent.mkdir(parents=True)

        mock_tix = _MockTix(
            issues=[
                {"id": "i-bad"},
                {"id": "i-good"},
            ],
        )
        _write_orch_state(plan_path, stage="INVESTIGATE")

        sm, _ = _make_state_machine(plan_path, tix=mock_tix)

        state = load_state(plan_path)
        state.batch_items = ["i-bad"]
        save_state(state, plan_path)

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
        plan_path = tmp_path / "ralph" / "plan.jsonl"
        plan_path.parent.mkdir(parents=True)

        mock_tix = _MockTix(
            done=[{"id": "t-fail", "name": "Failing task"}],
        )
        _write_orch_state(plan_path, stage="VERIFY")

        sm, _ = _make_state_machine(plan_path, tix=mock_tix)

        state = load_state(plan_path)
        state.batch_items = ["t-fail"]
        save_state(state, plan_path)

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
        plan_path = tmp_path / "ralph" / "plan.jsonl"
        plan_path.parent.mkdir(parents=True)

        mock_tix = _MockTix(issues=[{"id": "i-1"}])
        _write_orch_state(plan_path, stage="INVESTIGATE")

        config = GlobalConfig(max_failures=3)
        sm, _ = _make_state_machine(plan_path, config=config, tix=mock_tix)

        state = load_state(plan_path)
        state.batch_items = ["i-1"]
        save_state(state, plan_path)

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
        plan_path = tmp_path / "ralph" / "plan.jsonl"
        plan_path.parent.mkdir(parents=True)
        _write_orch_state(plan_path)

        sm, _ = _make_state_machine(plan_path)

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
        plan_path = tmp_path / "ralph" / "plan.jsonl"
        plan_path.parent.mkdir(parents=True)

        # Start with issues so INVESTIGATE has work, then tasks for BUILD
        mock_tix = _MockTix(
            issues=[{"id": "i-1"}],
            tasks=[{"id": "t-1"}],
        )
        _write_orch_state(plan_path, stage="INVESTIGATE")

        sm, _ = _make_state_machine(plan_path, tix=mock_tix)

        # Simulate a prior failure
        sm._batch_failure_count = 2

        # Running a successful investigate iteration should reset it
        sm.run_iteration(1)

        assert sm._batch_failure_count == 0


class TestLegacyRescueMigration:
    """Test that old plan.jsonl files with RESCUE stage are migrated."""

    def test_rescue_stage_migrates_to_investigate(self, tmp_path: Path):
        """Loading plan.jsonl with stage=RESCUE migrates to INVESTIGATE."""
        plan_path = tmp_path / "plan.jsonl"

        lines = [
            json.dumps({"t": "spec", "spec": "test-spec.md"}),
            json.dumps({
                "t": "stage",
                "stage": "RESCUE",
                "rescue_stage": "VERIFY",
                "rescue_batch": ["t-1"],
                "rescue_reason": "timeout",
            }),
        ]
        plan_path.write_text("\n".join(lines))

        state = load_state(plan_path)
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
