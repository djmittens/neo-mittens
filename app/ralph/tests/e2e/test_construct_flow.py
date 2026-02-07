"""E2E tests for ralph construct flow with stage transitions.

Run with: pytest ralph/tests/e2e/test_construct_flow.py -v --timeout=60
See also: test_construct_mock.py for mocked opencode tests.

Note: File split to keep under 500 line limit.

Ticket data is provided via MockTix — the state machine queries tix
for routing decisions, not RalphState.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

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

APP_DIR = Path(__file__).parent.parent.parent.parent


class _MockTix:
    """Controllable mock Tix for construct flow tests."""

    def __init__(
        self,
        tasks: list | None = None,
        done: list | None = None,
        issues: list | None = None,
    ):
        self._tasks = list(tasks or [])
        self._done = list(done or [])
        self._issues = list(issues or [])
        self.rejected: list[tuple[str, str]] = []

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
        """Record issue resolution."""
        self._issues = [i for i in self._issues if i.get("id") not in ids]
        return {"count": len(ids)}


def run_ralph(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run ralph as subprocess in specified directory."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(APP_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "ralph", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=30,
    )


def init_ralph_with_git(tmp_path: Path) -> Path:
    """Initialize ralph structure and git repository."""
    run_ralph("init", cwd=tmp_path)
    subprocess.run(
        ["git", "init"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "add", "."], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    return tmp_path / "ralph" / "plan.jsonl"


def create_test_state(
    plan_path: Path,
    spec: str = "test-spec.md",
    stage: Stage = Stage.INVESTIGATE,
) -> RalphState:
    """Create an orchestration-only test state."""
    state = RalphState(
        config=RalphPlanConfig(),
        spec=spec,
        stage=stage.name,
    )
    save_state(state, plan_path)
    return state


class TestConstructStageTransitions:
    """Tests for construct mode stage transitions."""

    def test_investigate_to_build_transition(self, tmp_path: Path):
        """Test BUILD stage runs when pending tasks exist."""
        plan_path = init_ralph_with_git(tmp_path)
        create_test_state(plan_path, stage=Stage.BUILD)

        mock_tix = _MockTix(tasks=[{"id": "t-test01", "name": "Test task"}])
        stages_run = []

        def mock_run_stage(
            config, stage, st, metrics, timeout_ms, ctx_limit
        ) -> StageResult:
            stages_run.append(stage)
            return StageResult(stage=stage, outcome=StageOutcome.SUCCESS)

        config = GlobalConfig.load()
        metrics = Metrics()

        sm = ConstructStateMachine(
            config=config,
            metrics=metrics,
            stage_timeout_ms=60000,
            context_limit=100000,
            run_stage_fn=mock_run_stage,
            load_state_fn=lambda: load_state(plan_path),
            save_state_fn=lambda st: save_state(st, plan_path),
            tix=mock_tix,
        )

        should_continue, spec_complete = sm.run_iteration(1)

        assert should_continue is True
        assert spec_complete is False
        assert Stage.BUILD in stages_run

    def test_build_to_verify_transition(self, tmp_path: Path):
        """Test transition from BUILD to VERIFY stage."""
        plan_path = init_ralph_with_git(tmp_path)
        create_test_state(plan_path, stage=Stage.VERIFY)

        # Start with a done task, mock run clears it
        mock_tix = _MockTix(
            done=[{"id": "t-test01", "name": "Test task"}],
        )
        stages_run = []

        def mock_run_stage(
            config, stage, st, metrics, timeout_ms, ctx_limit
        ) -> StageResult:
            stages_run.append(stage)
            if stage == Stage.VERIFY:
                # Simulate: after verify, task is accepted (no more done)
                mock_tix._done = []
                state = load_state(plan_path)
                state.batch_completed.append("t-test01")
                save_state(state, plan_path)
            return StageResult(stage=stage, outcome=StageOutcome.SUCCESS)

        config = GlobalConfig.load()
        metrics = Metrics()

        sm = ConstructStateMachine(
            config=config,
            metrics=metrics,
            stage_timeout_ms=60000,
            context_limit=100000,
            run_stage_fn=mock_run_stage,
            load_state_fn=lambda: load_state(plan_path),
            save_state_fn=lambda st: save_state(st, plan_path),
            tix=mock_tix,
        )

        should_continue, spec_complete = sm.run_iteration(1)

        assert Stage.VERIFY in stages_run

    def test_failure_triggers_decompose(self, tmp_path: Path):
        """Test that stage failure triggers DECOMPOSE in next iteration."""
        plan_path = init_ralph_with_git(tmp_path)
        create_test_state(plan_path, stage=Stage.BUILD)

        mock_tix = _MockTix(tasks=[{"id": "t-test01", "name": "Test task"}])
        stages_run = []
        call_count = [0]

        def mock_run_stage(
            config, stage, st, metrics, timeout_ms, ctx_limit
        ) -> StageResult:
            stages_run.append(stage)
            call_count[0] += 1
            if stage == Stage.BUILD and call_count[0] == 1:
                return StageResult(
                    stage=stage,
                    outcome=StageOutcome.FAILURE,
                    task_id="t-test01",
                    kill_reason="timeout",
                )
            return StageResult(stage=stage, outcome=StageOutcome.SUCCESS)

        config = GlobalConfig.load()
        metrics = Metrics()

        sm = ConstructStateMachine(
            config=config,
            metrics=metrics,
            stage_timeout_ms=60000,
            context_limit=100000,
            run_stage_fn=mock_run_stage,
            load_state_fn=lambda: load_state(plan_path),
            save_state_fn=lambda st: save_state(st, plan_path),
            tix=mock_tix,
        )

        should_continue, spec_complete = sm.run_iteration(1)
        assert should_continue is True

        should_continue, spec_complete = sm.run_iteration(2)

        assert Stage.DECOMPOSE in stages_run

    def test_complete_when_no_pending_tasks(self, tmp_path: Path):
        """Test spec completion when no pending or done tasks remain."""
        plan_path = init_ralph_with_git(tmp_path)
        create_test_state(plan_path, stage=Stage.VERIFY)

        # No tasks, no issues — should complete
        mock_tix = _MockTix()

        def mock_run_stage(
            config, stage, st, metrics, timeout_ms, ctx_limit
        ) -> StageResult:
            return StageResult(stage=stage, outcome=StageOutcome.SUCCESS)

        config = GlobalConfig.load()
        metrics = Metrics()

        sm = ConstructStateMachine(
            config=config,
            metrics=metrics,
            stage_timeout_ms=60000,
            context_limit=100000,
            run_stage_fn=mock_run_stage,
            load_state_fn=lambda: load_state(plan_path),
            save_state_fn=lambda st: save_state(st, plan_path),
            tix=mock_tix,
        )

        should_continue, spec_complete = sm.run_iteration(1)

        assert should_continue is False
        assert spec_complete is True

    def test_full_cycle_build_verify_investigate(self, tmp_path: Path):
        """Test full cycle: BUILD -> VERIFY -> INVESTIGATE -> BUILD.

        The flow is: BUILD -> VERIFY -> (if issues) INVESTIGATE -> BUILD.
        """
        plan_path = init_ralph_with_git(tmp_path)
        create_test_state(plan_path, stage=Stage.BUILD)

        mock_tix = _MockTix(tasks=[{"id": "t-test01", "name": "Test task"}])
        stages_run = []

        def mock_run_stage(
            config, stage, st, metrics, timeout_ms, ctx_limit
        ) -> StageResult:
            stages_run.append(stage)

            if stage == Stage.BUILD:
                # Task moves from pending to done
                mock_tix._tasks = []
                mock_tix._done = [{"id": "t-test01", "name": "Test task"}]

            if stage == Stage.VERIFY:
                # Verify rejects, creates issue
                mock_tix._done = []
                mock_tix._tasks = [{"id": "t-test01", "name": "Test task"}]
                mock_tix._issues = [{"id": "i-test01"}]
                state = load_state(plan_path)
                state.batch_completed.append("t-test01")
                save_state(state, plan_path)

            if stage == Stage.INVESTIGATE:
                # Investigate resolves issue
                mock_tix._issues = []
                state = load_state(plan_path)
                state.batch_completed.append("i-test01")
                save_state(state, plan_path)

            return StageResult(stage=stage, outcome=StageOutcome.SUCCESS)

        config = GlobalConfig.load()
        metrics = Metrics()

        sm = ConstructStateMachine(
            config=config,
            metrics=metrics,
            stage_timeout_ms=60000,
            context_limit=100000,
            run_stage_fn=mock_run_stage,
            load_state_fn=lambda: load_state(plan_path),
            save_state_fn=lambda st: save_state(st, plan_path),
            tix=mock_tix,
        )

        # Iteration 1: BUILD (marks task done)
        sm.run_iteration(1)
        # Iteration 2: VERIFY (rejects task, creates issue)
        sm.run_iteration(2)
        # Iteration 3: INVESTIGATE (issues exist, processes them)
        sm.run_iteration(3)

        assert stages_run == [Stage.BUILD, Stage.VERIFY, Stage.INVESTIGATE]

    def test_verify_skips_investigate_when_no_issues(self, tmp_path: Path):
        """When VERIFY passes everything and no issues, go to COMPLETE."""
        plan_path = init_ralph_with_git(tmp_path)
        create_test_state(plan_path, stage=Stage.VERIFY)

        mock_tix = _MockTix(
            done=[{"id": "t-test01", "name": "Test task"}],
        )
        stages_run = []

        def mock_run_stage(
            config, stage, st, metrics, timeout_ms, ctx_limit
        ) -> StageResult:
            stages_run.append(stage)
            if stage == Stage.VERIFY:
                # Accept task, no issues
                mock_tix._done = []
                state = load_state(plan_path)
                state.batch_completed.append("t-test01")
                save_state(state, plan_path)
            return StageResult(stage=stage, outcome=StageOutcome.SUCCESS)

        config = GlobalConfig.load()
        metrics = Metrics()

        sm = ConstructStateMachine(
            config=config,
            metrics=metrics,
            stage_timeout_ms=60000,
            context_limit=100000,
            run_stage_fn=mock_run_stage,
            load_state_fn=lambda: load_state(plan_path),
            save_state_fn=lambda st: save_state(st, plan_path),
            tix=mock_tix,
        )

        should_continue, spec_complete = sm.run_iteration(1)

        # VERIFY ran, then finalize should go to COMPLETE
        assert Stage.VERIFY in stages_run
        assert Stage.INVESTIGATE not in stages_run
        assert spec_complete is True


# TestConstructWithMockOpencode moved to test_construct_mock.py
