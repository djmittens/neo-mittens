import os
import shutil
import pytest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from ralph.config import GlobalConfig
from ralph.models import Task, Issue, RalphPlanConfig
from ralph.state import RalphState
from ralph.opencode import spawn_opencode


@pytest.fixture
def tmp_ralph_dir(tmp_path):
    """Create a temporary directory with a complete Ralph project structure."""
    root = tmp_path / "ralph"
    root.mkdir(parents=True)

    # Create basic directory structure
    for subdir in ["specs", "commands", "stages", "tests", "tui"]:
        (root / subdir).mkdir(parents=True)

    # Create an empty plan.jsonl and config files
    (root / "plan.jsonl").touch()
    config_dir = Path(os.path.expanduser("~")) / ".config" / "ralph"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text("# Test Config")

    return root


@pytest.fixture
def mock_state():
    """Return a RalphState with sample tasks and issues for testing."""
    tasks = [
        Task(
            id=f"t-{uuid.uuid4().hex[:8]}",
            name=f"Test Task {i}",
            spec="test_spec.md",
            notes=f"Test notes for task {i}",
            accept=f"Verification criteria for task {i}",
            priority="medium",
        )
        for i in range(3)
    ]

    issues = [
        Issue(
            id=f"i-{uuid.uuid4().hex[:8]}",
            spec="test_spec.md",
            desc=f"Test issue {i}",
        )
        for i in range(2)
    ]

    return RalphState(
        tasks=tasks,
        issues=issues,
        tombstones={"accepted": [], "rejected": []},
        config=RalphPlanConfig(stage="INVESTIGATE", current_task=tasks[0].id),
    )


@pytest.fixture
def mock_config():
    """Return a GlobalConfig with test values."""
    return GlobalConfig(
        model="gpt-4-turbo-preview",
        context_window=4096,
        timeout_ms=120000,
        max_iterations=3,
        profile="test",
    )


@pytest.fixture
def mock_opencode(monkeypatch):
    """Patch spawn_opencode to return fake output for testing."""

    def mock_spawn_output(*args, **kwargs):
        """Return a mocked subprocess that simulates opencode output."""
        mock_process = MagicMock()
        mock_process.stdout = [
            '{"type": "output", "content": "Mocked OpenCode Output"}',
            '{"type": "metrics", "tokens_used": 1024, "total_cost": 0.05}',
            '{"type": "done"}',
        ]
        mock_process.poll.return_value = 0
        return mock_process

    monkeypatch.setattr("ralph.opencode.spawn_opencode", mock_spawn_output)
    return mock_spawn_output


# Export the fixtures
__all__ = ["tmp_ralph_dir", "mock_state", "mock_config", "mock_opencode"]
