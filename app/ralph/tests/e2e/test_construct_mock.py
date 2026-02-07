"""E2E tests for construct flow with mocked opencode.

Split from test_construct_flow.py to keep files under 500 lines.
Run with: pytest ralph/tests/e2e/test_construct_mock.py -v --timeout=60

Ticket data is provided via MockTix for state machine tests.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    """Controllable mock Tix for construct mock tests."""

    def __init__(
        self,
        tasks: list | None = None,
        done: list | None = None,
        issues: list | None = None,
    ):
        self._tasks = list(tasks or [])
        self._done = list(done or [])
        self._issues = list(issues or [])

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


def _write_plan_with_tickets(
    plan_path: Path,
    stage: str = "BUILD",
    spec: str = "test-spec.md",
    task_lines: list[dict] | None = None,
) -> None:
    """Write plan.jsonl with orchestration + ticket lines."""
    state = RalphState(
        config=RalphPlanConfig(),
        spec=spec,
        stage=stage,
    )
    save_state(state, plan_path)
    with open(plan_path, "a") as f:
        for t in (task_lines or []):
            f.write(json.dumps(t) + "\n")


class TestConstructWithMockOpencode:
    """Tests for construct flow with mocked opencode."""

    def test_construct_with_mock_opencode_success(self, tmp_path: Path):
        """Test construct flow with mocked opencode returning success."""
        plan_path = init_ralph_with_git(tmp_path)
        create_test_state(plan_path, stage=Stage.BUILD)

        # Write a ticket line so plan.jsonl has task data for tix
        _write_plan_with_tickets(
            plan_path,
            stage="BUILD",
            task_lines=[{
                "t": "task", "id": "t-test01", "name": "Test task",
                "spec": "test-spec.md", "s": "p",
            }],
        )

        mock_popen = MagicMock()
        mock_popen.returncode = 0
        mock_popen.communicate.return_value = (
            b'{"type": "step_finish", "part": {"cost": 0.01}}\n',
            b"",
        )
        mock_popen.wait.return_value = 0

        with patch(
            "ralph.opencode.subprocess.Popen", return_value=mock_popen
        ):
            from ralph.opencode import spawn_opencode

            proc = spawn_opencode("test prompt", tmp_path, 60000)
            stdout, _ = proc.communicate()

            assert proc.returncode == 0

    def test_construct_with_mock_opencode_failure(self, tmp_path: Path):
        """Test construct flow with mocked opencode returning failure."""
        plan_path = init_ralph_with_git(tmp_path)
        create_test_state(plan_path, stage=Stage.BUILD)

        mock_popen = MagicMock()
        mock_popen.returncode = 1
        mock_popen.communicate.return_value = (
            b'{"type": "error", "message": "Task failed"}\n',
            b"",
        )
        mock_popen.wait.return_value = 1

        with patch(
            "ralph.opencode.subprocess.Popen", return_value=mock_popen
        ):
            from ralph.opencode import spawn_opencode

            proc = spawn_opencode("test prompt", tmp_path, 60000)
            stdout, _ = proc.communicate()

            assert proc.returncode == 1

    def test_state_machine_with_mock_opencode(self, tmp_path: Path):
        """Test state machine stages work with mocked opencode."""
        plan_path = init_ralph_with_git(tmp_path)
        create_test_state(plan_path, stage=Stage.BUILD)

        mock_tix = _MockTix(
            tasks=[{"id": "t-test01", "name": "Test task"}],
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

        with patch(
            "ralph.opencode.subprocess.Popen", return_value=mock_popen
        ):
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

            assert "BUILD" in stages_executed
            assert should_continue is True

    def test_mock_opencode_json_output_parsing(self, tmp_path: Path):
        """Test that mocked opencode JSON output is correctly parsed."""
        from ralph.opencode import parse_json_stream, extract_metrics

        mock_output = (
            '{"type": "step_start", "step": 1}\n'
            '{"type": "step_finish", "part": {"cost": 0.05, '
            '"tokens": {"input": 1000, "output": 500, '
            '"cache": {"read": 200}}}}\n'
            '{"type": "step_finish", "part": {"cost": 0.03, '
            '"tokens": {"input": 800, "output": 300, '
            '"cache": {"read": 100}}}}\n'
            '{"type": "run_complete", "status": "success"}\n'
        )

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
# Split from original file
