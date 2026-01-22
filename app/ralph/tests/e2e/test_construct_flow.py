"""E2E tests for ralph construct flow with stage transitions."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ralph.config import GlobalConfig
from ralph.context import Metrics
from ralph.models import Task
from ralph.stages.base import (
    ConstructStateMachine,
    Stage,
    StageOutcome,
    StageResult,
)
from ralph.state import RalphState, load_state, save_state
from ralph.models import RalphPlanConfig

APP_DIR = Path(__file__).parent.parent.parent.parent


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
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    return tmp_path / "ralph" / "plan.jsonl"


def create_test_state(
    plan_path: Path,
    spec: str = "test-spec.md",
    tasks: list[Task] | None = None,
    stage: Stage = Stage.INVESTIGATE,
    issues: list | None = None,
) -> RalphState:
    """Create a test state with given parameters."""
    if tasks is None:
        tasks = []
    if issues is None:
        issues = []

    state = RalphState(
        tasks=tasks,
        issues=issues,
        tombstones={"accepted": [], "rejected": []},
        config=RalphPlanConfig(),
        spec=spec,
        current_task_id=tasks[0].id if tasks else None,
        stage=stage.name,
    )
    save_state(state, plan_path)
    return state


class TestConstructStageTransitions:
    """Tests for construct mode stage transitions."""

    def test_investigate_to_build_transition(self, tmp_path: Path):
        """Test transition from INVESTIGATE to BUILD stage.

        Start at BUILD with pending task, verify BUILD stage runs.
        """
        plan_path = init_ralph_with_git(tmp_path)

        pending_task = Task(
            id="t-test01",
            name="Test task",
            spec="test-spec.md",
            notes="Test notes",
            accept="echo ok",
            status="p",
        )

        create_test_state(
            plan_path,
            spec="test-spec.md",
            tasks=[pending_task],
            stage=Stage.BUILD,
        )

        stages_run = []

        def mock_run_stage(
            config, stage, st, metrics, timeout_ms, ctx_limit
        ) -> StageResult:
            stages_run.append(stage)
            return StageResult(stage=stage, outcome=StageOutcome.SUCCESS)

        def load_state_fn() -> RalphState:
            return load_state(plan_path)

        def save_state_fn(st: RalphState) -> None:
            save_state(st, plan_path)

        config = GlobalConfig.load()
        metrics = Metrics()

        sm = ConstructStateMachine(
            config=config,
            metrics=metrics,
            stage_timeout_ms=60000,
            context_limit=100000,
            run_stage_fn=mock_run_stage,
            load_state_fn=load_state_fn,
            save_state_fn=save_state_fn,
        )

        should_continue, spec_complete = sm.run_iteration(1)

        assert should_continue is True
        assert spec_complete is False
        assert Stage.BUILD in stages_run

    def test_build_to_verify_transition(self, tmp_path: Path):
        """Test transition from BUILD to VERIFY stage.

        Start at VERIFY with done task, verify VERIFY stage runs.
        The mock stage clears the task to simulate successful verification.
        """
        plan_path = init_ralph_with_git(tmp_path)

        done_task = Task(
            id="t-test01",
            name="Test task",
            spec="test-spec.md",
            notes="Test notes",
            accept="echo ok",
            status="d",
        )

        create_test_state(
            plan_path,
            spec="test-spec.md",
            tasks=[done_task],
            stage=Stage.VERIFY,
        )

        stages_run = []

        def mock_run_stage(
            config, stage, st, metrics, timeout_ms, ctx_limit
        ) -> StageResult:
            stages_run.append(stage)
            if stage == Stage.VERIFY:
                current_state = load_state(plan_path)
                current_state.tasks = []
                current_state.batch_completed.append("t-test01")
                save_state(current_state, plan_path)
            return StageResult(stage=stage, outcome=StageOutcome.SUCCESS)

        def load_state_fn() -> RalphState:
            return load_state(plan_path)

        def save_state_fn(st: RalphState) -> None:
            save_state(st, plan_path)

        config = GlobalConfig.load()
        metrics = Metrics()

        sm = ConstructStateMachine(
            config=config,
            metrics=metrics,
            stage_timeout_ms=60000,
            context_limit=100000,
            run_stage_fn=mock_run_stage,
            load_state_fn=load_state_fn,
            save_state_fn=save_state_fn,
        )

        should_continue, spec_complete = sm.run_iteration(1)

        assert Stage.VERIFY in stages_run

    def test_failure_triggers_decompose(self, tmp_path: Path):
        """Test that stage failure triggers DECOMPOSE in next iteration."""
        plan_path = init_ralph_with_git(tmp_path)

        pending_task = Task(
            id="t-test01",
            name="Test task",
            spec="test-spec.md",
            notes="Test notes",
            accept="echo ok",
            status="p",
        )

        create_test_state(
            plan_path,
            spec="test-spec.md",
            tasks=[pending_task],
            stage=Stage.BUILD,
        )

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

        def load_state_fn() -> RalphState:
            return load_state(plan_path)

        def save_state_fn(st: RalphState) -> None:
            save_state(st, plan_path)

        config = GlobalConfig.load()
        metrics = Metrics()

        sm = ConstructStateMachine(
            config=config,
            metrics=metrics,
            stage_timeout_ms=60000,
            context_limit=100000,
            run_stage_fn=mock_run_stage,
            load_state_fn=load_state_fn,
            save_state_fn=save_state_fn,
        )

        should_continue, spec_complete = sm.run_iteration(1)
        assert should_continue is True

        should_continue, spec_complete = sm.run_iteration(2)

        assert Stage.DECOMPOSE in stages_run

    def test_complete_when_no_pending_tasks(self, tmp_path: Path):
        """Test spec completion when no pending or done tasks remain."""
        plan_path = init_ralph_with_git(tmp_path)

        create_test_state(
            plan_path,
            spec="test-spec.md",
            tasks=[],
            stage=Stage.VERIFY,
        )

        def mock_run_stage(
            config, stage, st, metrics, timeout_ms, ctx_limit
        ) -> StageResult:
            return StageResult(stage=stage, outcome=StageOutcome.SUCCESS)

        def load_state_fn() -> RalphState:
            return load_state(plan_path)

        def save_state_fn(st: RalphState) -> None:
            save_state(st, plan_path)

        config = GlobalConfig.load()
        metrics = Metrics()

        sm = ConstructStateMachine(
            config=config,
            metrics=metrics,
            stage_timeout_ms=60000,
            context_limit=100000,
            run_stage_fn=mock_run_stage,
            load_state_fn=load_state_fn,
            save_state_fn=save_state_fn,
        )

        should_continue, spec_complete = sm.run_iteration(1)

        assert should_continue is False
        assert spec_complete is True

    def test_full_cycle_investigate_build_verify(self, tmp_path: Path):
        """Test full cycle: INVESTIGATE -> BUILD -> VERIFY via multiple iterations."""
        plan_path = init_ralph_with_git(tmp_path)

        from ralph.models import Issue

        pending_task = Task(
            id="t-test01",
            name="Test task",
            spec="test-spec.md",
            notes="Test notes",
            accept="echo ok",
            status="p",
        )

        test_issue = Issue(
            id="i-test01",
            desc="Test issue",
            spec="test-spec.md",
        )

        create_test_state(
            plan_path,
            spec="test-spec.md",
            tasks=[pending_task],
            stage=Stage.INVESTIGATE,
            issues=[test_issue],
        )

        stages_run = []

        def mock_run_stage(
            config, stage, st, metrics, timeout_ms, ctx_limit
        ) -> StageResult:
            stages_run.append(stage)

            if stage == Stage.INVESTIGATE:
                current_state = load_state(plan_path)
                current_state.issues = []
                current_state.batch_completed.append("i-test01")
                save_state(current_state, plan_path)

            if stage == Stage.BUILD:
                current_state = load_state(plan_path)
                if current_state.tasks:
                    current_state.tasks[0].status = "d"
                    save_state(current_state, plan_path)

            if stage == Stage.VERIFY:
                current_state = load_state(plan_path)
                current_state.tasks = []
                current_state.batch_completed.append("t-test01")
                save_state(current_state, plan_path)

            return StageResult(stage=stage, outcome=StageOutcome.SUCCESS)

        def load_state_fn() -> RalphState:
            return load_state(plan_path)

        def save_state_fn(st: RalphState) -> None:
            save_state(st, plan_path)

        config = GlobalConfig.load()
        metrics = Metrics()

        sm = ConstructStateMachine(
            config=config,
            metrics=metrics,
            stage_timeout_ms=60000,
            context_limit=100000,
            run_stage_fn=mock_run_stage,
            load_state_fn=load_state_fn,
            save_state_fn=save_state_fn,
        )

        sm.run_iteration(1)
        sm.run_iteration(2)
        sm.run_iteration(3)

        assert Stage.INVESTIGATE in stages_run
        assert Stage.BUILD in stages_run
        assert Stage.VERIFY in stages_run


class TestConstructWithMockOpencode:
    """Tests for construct flow with mocked opencode."""

    def test_construct_with_mock_opencode_success(self, tmp_path: Path):
        """Test construct flow with mocked opencode returning success."""
        plan_path = init_ralph_with_git(tmp_path)

        pending_task = Task(
            id="t-test01",
            name="Test task",
            spec="test-spec.md",
            notes="Test notes",
            accept="echo ok",
            status="p",
        )
        create_test_state(
            plan_path,
            spec="test-spec.md",
            tasks=[pending_task],
        )

        mock_popen = MagicMock()
        mock_popen.returncode = 0
        mock_popen.communicate.return_value = (
            b'{"type": "step_finish", "part": {"cost": 0.01}}\n',
            b"",
        )
        mock_popen.wait.return_value = 0

        with patch("ralph.opencode.subprocess.Popen", return_value=mock_popen):
            from ralph.opencode import spawn_opencode

            proc = spawn_opencode("test prompt", tmp_path, 60000)
            stdout, _ = proc.communicate()

            assert proc.returncode == 0

    def test_construct_with_mock_opencode_failure(self, tmp_path: Path):
        """Test construct flow with mocked opencode returning failure."""
        plan_path = init_ralph_with_git(tmp_path)

        pending_task = Task(
            id="t-test01",
            name="Test task",
            spec="test-spec.md",
            notes="Test notes",
            accept="echo ok",
            status="p",
        )
        create_test_state(
            plan_path,
            spec="test-spec.md",
            tasks=[pending_task],
        )

        mock_popen = MagicMock()
        mock_popen.returncode = 1
        mock_popen.communicate.return_value = (
            b'{"type": "error", "message": "Task failed"}\n',
            b"",
        )
        mock_popen.wait.return_value = 1

        with patch("ralph.opencode.subprocess.Popen", return_value=mock_popen):
            from ralph.opencode import spawn_opencode

            proc = spawn_opencode("test prompt", tmp_path, 60000)
            stdout, _ = proc.communicate()

            assert proc.returncode == 1

    def test_state_machine_with_mock_opencode(self, tmp_path: Path):
        """Test state machine stages work with mocked opencode integration."""
        plan_path = init_ralph_with_git(tmp_path)

        pending_task = Task(
            id="t-test01",
            name="Test task",
            spec="test-spec.md",
            notes="Test notes",
            accept="echo ok",
            status="p",
        )
        create_test_state(
            plan_path,
            spec="test-spec.md",
            tasks=[pending_task],
            stage=Stage.BUILD,
        )

        mock_popen = MagicMock()
        mock_popen.returncode = 0
        mock_popen.communicate.return_value = (
            b'{"type": "step_finish", "part": {"cost": 0.01}}\n',
            b"",
        )

        stages_executed = []

        def mock_run_stage(
            config, stage, st, metrics, timeout_ms, ctx_limit
        ) -> StageResult:
            stages_executed.append(stage.name)
            return StageResult(stage=stage, outcome=StageOutcome.SUCCESS)

        def load_state_fn() -> RalphState:
            return load_state(plan_path)

        def save_state_fn(st: RalphState) -> None:
            save_state(st, plan_path)

        with patch("ralph.opencode.subprocess.Popen", return_value=mock_popen):
            config = GlobalConfig.load()
            metrics = Metrics()

            sm = ConstructStateMachine(
                config=config,
                metrics=metrics,
                stage_timeout_ms=60000,
                context_limit=100000,
                run_stage_fn=mock_run_stage,
                load_state_fn=load_state_fn,
                save_state_fn=save_state_fn,
            )

            should_continue, spec_complete = sm.run_iteration(1)

            assert "BUILD" in stages_executed
            assert should_continue is True

    def test_mock_opencode_json_output_parsing(self, tmp_path: Path):
        """Test that mocked opencode JSON output is correctly parsed."""
        from ralph.opencode import parse_json_stream, extract_metrics

        mock_output = """{"type": "step_start", "step": 1}
{"type": "step_finish", "part": {"cost": 0.05, "tokens": {"input": 1000, "output": 500, "cache": {"read": 200}}}}
{"type": "step_finish", "part": {"cost": 0.03, "tokens": {"input": 800, "output": 300, "cache": {"read": 100}}}}
{"type": "run_complete", "status": "success"}
"""

        parsed_events = list(parse_json_stream(mock_output))

        assert len(parsed_events) == 4
        assert parsed_events[0]["type"] == "step_start"
        assert parsed_events[1]["type"] == "step_finish"
        assert parsed_events[3]["type"] == "run_complete"

        metrics = extract_metrics(mock_output)

        assert metrics.total_cost == pytest.approx(0.08, rel=0.01)
        assert metrics.total_tokens_in == 2100
        assert metrics.total_tokens_out == 800
        assert metrics.total_iterations == 2
