"""End-to-end tests for Ralph construct flow.

Tests stage transitions with mocked opencode calls.
Does not consume API tokens by mocking external calls.
"""

from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from ralph.config import GlobalConfig, get_global_config
from ralph.context import Metrics
from ralph.models import Issue, Task
from ralph.stages.base import (
    ConstructStateMachine,
    Stage,
    StageOutcome,
    StageResult,
)
from ralph.state import RalphState, load_state, save_state


@pytest.fixture
def temp_ralph_state(tmp_path: Path) -> tuple[Path, RalphState]:
    """Create a temporary ralph state for testing."""
    ralph_dir = tmp_path / "ralph"
    ralph_dir.mkdir()
    specs_dir = ralph_dir / "specs"
    specs_dir.mkdir()
    plan_file = ralph_dir / "plan.jsonl"

    state = RalphState()
    state.spec = "test.md"
    save_state(state, plan_file)

    spec_file = specs_dir / "test.md"
    spec_file.write_text("# Test Spec\n\n## Requirements\n\n- Test requirement")

    return plan_file, state


@pytest.fixture
def mock_config() -> GlobalConfig:
    """Create a mock global config."""
    return get_global_config()


@pytest.fixture
def mock_metrics() -> Metrics:
    """Create a mock metrics object."""
    return Metrics()


def make_success_result(stage: Stage) -> StageResult:
    """Create a successful stage result."""
    return StageResult(
        stage=stage,
        outcome=StageOutcome.SUCCESS,
        exit_code=0,
        duration_seconds=1.0,
        cost=0.01,
        tokens_used=1000,
    )


def make_failure_result(
    stage: Stage,
    task_id: Optional[str] = None,
    kill_reason: Optional[str] = None,
    kill_log: Optional[str] = None,
) -> StageResult:
    """Create a failed stage result."""
    return StageResult(
        stage=stage,
        outcome=StageOutcome.FAILURE,
        exit_code=1,
        duration_seconds=1.0,
        cost=0.01,
        tokens_used=1000,
        task_id=task_id,
        kill_reason=kill_reason,
        kill_log=kill_log,
    )


class TestStageEnums:
    """Tests for stage and outcome enums."""

    def test_stage_values(self) -> None:
        """Test that all expected stages exist."""
        assert Stage.INVESTIGATE is not None
        assert Stage.BUILD is not None
        assert Stage.VERIFY is not None
        assert Stage.DECOMPOSE is not None
        assert Stage.COMPLETE is not None

    def test_stage_outcome_values(self) -> None:
        """Test that all expected outcomes exist."""
        assert StageOutcome.SUCCESS is not None
        assert StageOutcome.FAILURE is not None
        assert StageOutcome.SKIP is not None


class TestStageResult:
    """Tests for StageResult dataclass."""

    def test_stage_result_creation(self) -> None:
        """Test creating a stage result."""
        result = StageResult(
            stage=Stage.BUILD,
            outcome=StageOutcome.SUCCESS,
            exit_code=0,
            duration_seconds=5.5,
            cost=0.02,
            tokens_used=2000,
        )
        assert result.stage == Stage.BUILD
        assert result.outcome == StageOutcome.SUCCESS
        assert result.exit_code == 0
        assert result.duration_seconds == 5.5
        assert result.cost == 0.02
        assert result.tokens_used == 2000

    def test_stage_result_with_kill_info(self) -> None:
        """Test creating a stage result with kill info."""
        result = StageResult(
            stage=Stage.BUILD,
            outcome=StageOutcome.FAILURE,
            exit_code=1,
            kill_reason="timeout",
            kill_log="/path/to/log",
            task_id="t-abc123",
        )
        assert result.kill_reason == "timeout"
        assert result.kill_log == "/path/to/log"
        assert result.task_id == "t-abc123"


class TestConstructStateMachine:
    """Tests for the construct state machine."""

    def test_state_machine_initialization(
        self,
        temp_ralph_state: tuple[Path, RalphState],
        mock_config: GlobalConfig,
        mock_metrics: Metrics,
    ) -> None:
        """Test initializing the state machine."""
        plan_file, _ = temp_ralph_state

        def mock_run_stage(*args) -> StageResult:
            return make_success_result(Stage.BUILD)

        sm = ConstructStateMachine(
            config=mock_config,
            metrics=mock_metrics,
            stage_timeout_ms=300000,
            context_limit=200000,
            run_stage_fn=mock_run_stage,
            plan_path=plan_file,
            load_state_fn=load_state,
            save_state_fn=save_state,
        )

        assert sm.config == mock_config
        assert sm.metrics == mock_metrics
        assert sm.stage_timeout_ms == 300000
        assert sm.context_limit == 200000

    def test_no_spec_returns_immediately(
        self,
        tmp_path: Path,
        mock_config: GlobalConfig,
        mock_metrics: Metrics,
    ) -> None:
        """Test that no spec set returns immediately."""
        ralph_dir = tmp_path / "ralph"
        ralph_dir.mkdir()
        plan_file = ralph_dir / "plan.jsonl"

        state = RalphState()
        save_state(state, plan_file)

        run_stage_mock = MagicMock(return_value=make_success_result(Stage.BUILD))

        sm = ConstructStateMachine(
            config=mock_config,
            metrics=mock_metrics,
            stage_timeout_ms=300000,
            context_limit=200000,
            run_stage_fn=run_stage_mock,
            plan_path=plan_file,
            load_state_fn=load_state,
            save_state_fn=save_state,
        )

        should_continue, spec_complete = sm.run_iteration(1)

        assert not should_continue
        assert not spec_complete
        run_stage_mock.assert_not_called()

    def test_pending_tasks_triggers_build(
        self,
        temp_ralph_state: tuple[Path, RalphState],
        mock_config: GlobalConfig,
        mock_metrics: Metrics,
    ) -> None:
        """Test that pending tasks trigger BUILD stage."""
        plan_file, state = temp_ralph_state

        task = Task(
            id="t-test123",
            name="Test task",
            spec="test.md",
            status="p",
        )
        state.add_task(task)
        save_state(state, plan_file)

        run_stage_mock = MagicMock(return_value=make_success_result(Stage.BUILD))

        sm = ConstructStateMachine(
            config=mock_config,
            metrics=mock_metrics,
            stage_timeout_ms=300000,
            context_limit=200000,
            run_stage_fn=run_stage_mock,
            plan_path=plan_file,
            load_state_fn=load_state,
            save_state_fn=save_state,
        )

        sm.run_iteration(1)

        run_stage_mock.assert_called()
        call_args = run_stage_mock.call_args
        assert call_args[0][1] == Stage.BUILD

    def test_issues_triggers_investigate(
        self,
        temp_ralph_state: tuple[Path, RalphState],
        mock_config: GlobalConfig,
        mock_metrics: Metrics,
    ) -> None:
        """Test that issues trigger INVESTIGATE stage."""
        plan_file, state = temp_ralph_state

        issue = Issue(
            id="i-test123",
            desc="Test issue",
            spec="test.md",
        )
        state.add_issue(issue)
        save_state(state, plan_file)

        run_stage_mock = MagicMock(return_value=make_success_result(Stage.INVESTIGATE))

        sm = ConstructStateMachine(
            config=mock_config,
            metrics=mock_metrics,
            stage_timeout_ms=300000,
            context_limit=200000,
            run_stage_fn=run_stage_mock,
            plan_path=plan_file,
            load_state_fn=load_state,
            save_state_fn=save_state,
        )

        sm.run_iteration(1)

        run_stage_mock.assert_called()
        call_args = run_stage_mock.call_args
        assert call_args[0][1] == Stage.INVESTIGATE

    def test_done_tasks_triggers_verify(
        self,
        temp_ralph_state: tuple[Path, RalphState],
        mock_config: GlobalConfig,
        mock_metrics: Metrics,
    ) -> None:
        """Test that done tasks trigger VERIFY stage."""
        plan_file, state = temp_ralph_state

        task = Task(
            id="t-test123",
            name="Test task",
            spec="test.md",
            status="d",
            done_at="abc123",
        )
        state.add_task(task)
        save_state(state, plan_file)

        run_stage_mock = MagicMock(return_value=make_success_result(Stage.VERIFY))

        sm = ConstructStateMachine(
            config=mock_config,
            metrics=mock_metrics,
            stage_timeout_ms=300000,
            context_limit=200000,
            run_stage_fn=run_stage_mock,
            plan_path=plan_file,
            load_state_fn=load_state,
            save_state_fn=save_state,
        )

        sm.run_iteration(1)

        run_stage_mock.assert_called()
        call_args = run_stage_mock.call_args
        assert call_args[0][1] == Stage.VERIFY

    def test_no_work_returns_complete(
        self,
        temp_ralph_state: tuple[Path, RalphState],
        mock_config: GlobalConfig,
        mock_metrics: Metrics,
    ) -> None:
        """Test that no pending/done/issues returns spec complete."""
        plan_file, _ = temp_ralph_state

        run_stage_mock = MagicMock(return_value=make_success_result(Stage.BUILD))

        sm = ConstructStateMachine(
            config=mock_config,
            metrics=mock_metrics,
            stage_timeout_ms=300000,
            context_limit=200000,
            run_stage_fn=run_stage_mock,
            plan_path=plan_file,
            load_state_fn=load_state,
            save_state_fn=save_state,
        )

        should_continue, spec_complete = sm.run_iteration(1)

        assert not should_continue
        assert spec_complete


class TestStageTransitions:
    """Tests for stage transition logic."""

    def test_investigate_before_build(
        self,
        temp_ralph_state: tuple[Path, RalphState],
        mock_config: GlobalConfig,
        mock_metrics: Metrics,
    ) -> None:
        """Test that INVESTIGATE runs before BUILD when issues exist."""
        plan_file, state = temp_ralph_state

        task = Task(id="t-test", name="Task", spec="test.md", status="p")
        issue = Issue(id="i-test", desc="Issue", spec="test.md")
        state.add_task(task)
        state.add_issue(issue)
        save_state(state, plan_file)

        stages_called: list[Stage] = []

        def track_stage(*args) -> StageResult:
            stage = args[1]
            stages_called.append(stage)
            return make_success_result(stage)

        sm = ConstructStateMachine(
            config=mock_config,
            metrics=mock_metrics,
            stage_timeout_ms=300000,
            context_limit=200000,
            run_stage_fn=track_stage,
            plan_path=plan_file,
            load_state_fn=load_state,
            save_state_fn=save_state,
        )

        sm.run_iteration(1)

        assert Stage.INVESTIGATE in stages_called
        if Stage.BUILD in stages_called:
            assert stages_called.index(Stage.INVESTIGATE) < stages_called.index(
                Stage.BUILD
            )

    def test_failure_triggers_decompose(
        self,
        temp_ralph_state: tuple[Path, RalphState],
        mock_config: GlobalConfig,
        mock_metrics: Metrics,
    ) -> None:
        """Test that stage failure triggers DECOMPOSE in next iteration."""
        plan_file, state = temp_ralph_state

        task = Task(id="t-test", name="Task", spec="test.md", status="p")
        state.add_task(task)
        save_state(state, plan_file)

        call_count = 0

        def fail_then_decompose(*args) -> StageResult:
            nonlocal call_count
            call_count += 1
            stage = args[1]
            if call_count == 1 and stage == Stage.BUILD:
                return make_failure_result(
                    stage, task_id="t-test", kill_reason="timeout"
                )
            return make_success_result(stage)

        sm = ConstructStateMachine(
            config=mock_config,
            metrics=mock_metrics,
            stage_timeout_ms=300000,
            context_limit=200000,
            run_stage_fn=fail_then_decompose,
            plan_path=plan_file,
            load_state_fn=load_state,
            save_state_fn=save_state,
        )

        should_continue_1, _ = sm.run_iteration(1)
        assert should_continue_1

        assert sm._pending_decompose

    def test_task_marked_for_decompose_on_failure(
        self,
        temp_ralph_state: tuple[Path, RalphState],
        mock_config: GlobalConfig,
        mock_metrics: Metrics,
    ) -> None:
        """Test that task is marked needs_decompose on failure."""
        plan_file, state = temp_ralph_state

        task = Task(id="t-test", name="Task", spec="test.md", status="p")
        state.add_task(task)
        save_state(state, plan_file)

        def fail_build(*args) -> StageResult:
            stage = args[1]
            if stage == Stage.BUILD:
                return make_failure_result(
                    stage,
                    task_id="t-test",
                    kill_reason="context_limit",
                    kill_log="/tmp/log.txt",
                )
            return make_success_result(stage)

        sm = ConstructStateMachine(
            config=mock_config,
            metrics=mock_metrics,
            stage_timeout_ms=300000,
            context_limit=200000,
            run_stage_fn=fail_build,
            plan_path=plan_file,
            load_state_fn=load_state,
            save_state_fn=save_state,
        )

        sm.run_iteration(1)

        updated_state = load_state(plan_file)
        updated_task = next((t for t in updated_state.tasks if t.id == "t-test"), None)
        assert updated_task is not None
        assert updated_task.needs_decompose is True
        assert updated_task.kill_reason == "context_limit"
        assert updated_task.kill_log == "/tmp/log.txt"


class TestMetricsTracking:
    """Tests for metrics tracking during construct."""

    def test_metrics_object_used(
        self,
        temp_ralph_state: tuple[Path, RalphState],
        mock_config: GlobalConfig,
        mock_metrics: Metrics,
    ) -> None:
        """Test that metrics object is passed to stage runner."""
        plan_file, state = temp_ralph_state

        task = Task(id="t-test", name="Task", spec="test.md", status="p")
        state.add_task(task)
        save_state(state, plan_file)

        captured_metrics = None

        def capture_metrics(*args) -> StageResult:
            nonlocal captured_metrics
            captured_metrics = args[3]
            return make_success_result(Stage.BUILD)

        sm = ConstructStateMachine(
            config=mock_config,
            metrics=mock_metrics,
            stage_timeout_ms=300000,
            context_limit=200000,
            run_stage_fn=capture_metrics,
            plan_path=plan_file,
            load_state_fn=load_state,
            save_state_fn=save_state,
        )

        sm.run_iteration(1)

        assert captured_metrics is mock_metrics


class TestIterationControl:
    """Tests for iteration control logic."""

    def test_continue_on_pending_work(
        self,
        temp_ralph_state: tuple[Path, RalphState],
        mock_config: GlobalConfig,
        mock_metrics: Metrics,
    ) -> None:
        """Test that should_continue is True when work remains."""
        plan_file, state = temp_ralph_state

        task = Task(id="t-test", name="Task", spec="test.md", status="p")
        state.add_task(task)
        save_state(state, plan_file)

        run_stage_mock = MagicMock(return_value=make_success_result(Stage.BUILD))

        sm = ConstructStateMachine(
            config=mock_config,
            metrics=mock_metrics,
            stage_timeout_ms=300000,
            context_limit=200000,
            run_stage_fn=run_stage_mock,
            plan_path=plan_file,
            load_state_fn=load_state,
            save_state_fn=save_state,
        )

        should_continue, _ = sm.run_iteration(1)

        assert should_continue is True

    def test_stop_when_complete(
        self,
        temp_ralph_state: tuple[Path, RalphState],
        mock_config: GlobalConfig,
        mock_metrics: Metrics,
    ) -> None:
        """Test that should_continue is False when spec complete."""
        plan_file, _ = temp_ralph_state

        run_stage_mock = MagicMock(return_value=make_success_result(Stage.BUILD))

        sm = ConstructStateMachine(
            config=mock_config,
            metrics=mock_metrics,
            stage_timeout_ms=300000,
            context_limit=200000,
            run_stage_fn=run_stage_mock,
            plan_path=plan_file,
            load_state_fn=load_state,
            save_state_fn=save_state,
        )

        should_continue, spec_complete = sm.run_iteration(1)

        assert should_continue is False
        assert spec_complete is True
