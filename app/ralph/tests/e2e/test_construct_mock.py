"""E2E tests for construct flow with mocked opencode.

Split from test_construct_flow.py to keep files under 500 lines.
Run with: pytest ralph/tests/e2e/test_construct_mock.py -v --timeout=60

Ticket data is provided via MockTix for state machine tests.
"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
    return tmp_path


def create_test_state(
    repo_root: Path,
    spec: str = "test-spec.md",
    stage: Stage = Stage.INVESTIGATE,
) -> RalphState:
    """Create an orchestration-only test state."""
    state = RalphState(
        spec=spec,
        stage=stage.name,
    )
    save_state(state, repo_root)
    return state


class TestConstructWithMockOpencode:
    """Tests for construct flow with mocked opencode."""

    def test_construct_with_mock_opencode_success(self, tmp_path: Path):
        """Test construct flow with mocked opencode returning success."""
        repo_root = init_ralph_with_git(tmp_path)
        create_test_state(repo_root, stage=Stage.BUILD)

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
        repo_root = init_ralph_with_git(tmp_path)
        create_test_state(repo_root, stage=Stage.BUILD)

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
        repo_root = init_ralph_with_git(tmp_path)
        create_test_state(repo_root, stage=Stage.BUILD)

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
                load_state_fn=lambda: load_state(repo_root),
                save_state_fn=lambda st: save_state(st, repo_root),
                tix=mock_tix,
            )

            should_continue, spec_complete = sm.run_iteration(1)

            assert "BUILD" in stages_executed
            assert should_continue is True

    def test_mock_opencode_json_output_parsing(self, tmp_path: Path):
        """Test that mocked opencode JSON output is correctly parsed."""
        from ralph.opencode import parse_json_stream, _process_event
        from ralph.context import Metrics

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

        # Process step_finish events through _process_event
        metrics = Metrics()
        for event in parsed_events:
            if event.get("type") == "step_finish":
                _process_event(event, metrics)

        assert metrics.total_cost == pytest.approx(0.08, rel=0.01)
        assert metrics.total_tokens_in == 1800  # 1000+800 (cache reads split out)
        assert metrics.total_tokens_cached == 300  # 200+100 (cache reads)
        assert metrics.total_tokens_out == 800
        assert metrics.total_iterations == 2
# Split from original file
