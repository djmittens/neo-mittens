import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from ralph.config import GlobalConfig
from ralph.state import RalphState


@pytest.fixture
def tmp_ralph_dir(tmp_path):
    """Create a temporary directory with a complete Ralph project structure."""
    root = tmp_path / "ralph"
    root.mkdir(parents=True)

    # Create basic directory structure
    for subdir in ["specs", "commands", "stages", "tests", "tui"]:
        (root / subdir).mkdir(parents=True)

    # Create .tix directory for tix ticket data
    tix_dir = tmp_path / ".tix"
    tix_dir.mkdir(parents=True)

    config_dir = Path(os.path.expanduser("~")) / ".config" / "ralph"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text("# Test Config")

    return root


@pytest.fixture
def mock_state():
    """Return a RalphState with orchestration fields for testing.

    Ticket data (tasks, issues, tombstones) is now owned by tix,
    so this fixture only sets orchestration state.
    """
    return RalphState(
        spec="test_spec.md",
        stage="INVESTIGATE",
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


class MockTix:
    """Controllable mock for Tix that satisfies TixProtocol.

    Provides in-memory ticket storage with tracking attributes for
    assertions. Used across unit and e2e tests.
    """

    def __init__(
        self,
        tasks: list | None = None,
        done: list | None = None,
        issues: list | None = None,
    ):
        self._tasks: list[dict] = list(tasks or [])
        self._done: list[dict] = list(done or [])
        self._issues: list[dict] = list(issues or [])
        self.rejected: list[tuple[str, str]] = []
        self.resolved_ids: list[list[str]] = []

    # -- Query operations ----------------------------------------------------

    def query_tasks(self) -> list[dict]:
        """Return pending tasks."""
        return self._tasks

    def query_done_tasks(self) -> list[dict]:
        """Return done tasks."""
        return self._done

    def query_issues(self) -> list[dict]:
        """Return open issues."""
        return self._issues

    def query_full(self) -> dict:
        """Return full state dict."""
        return {
            "tasks": {"pending": self._tasks, "done": self._done},
            "issues": self._issues,
        }

    # -- Task mutations ------------------------------------------------------

    def task_add(self, task_json: dict) -> dict:
        """Add a task (returns synthetic id)."""
        task_id = f"t-mock-{len(self._tasks)}"
        self._tasks.append({"id": task_id, **task_json, "s": "p"})
        return {"id": task_id, "name": task_json.get("name", "")}

    def task_batch_add(self, tasks: list[dict]) -> list[dict]:
        """Batch add tasks."""
        results = []
        for t in tasks:
            results.append(self.task_add(t))
        return results

    def task_done(self, task_id: str | None = None) -> dict:
        """Mark a task as done."""
        tid = task_id or (self._tasks[0]["id"] if self._tasks else "")
        return {"id": tid, "status": "done", "done_at": "mock-commit"}

    def task_accept(self, task_id: str | None = None) -> dict:
        """Accept a done task."""
        tid = task_id or (self._done[0]["id"] if self._done else "")
        self._done = [t for t in self._done if t.get("id") != tid]
        return {"id": tid, "status": "accepted"}

    def task_reject(self, task_id: str, reason: str) -> dict:
        """Reject a done task and record it."""
        self.rejected.append((task_id, reason))
        return {"id": task_id, "status": "p"}

    def task_delete(self, task_id: str) -> dict:
        """Delete a task."""
        self._tasks = [t for t in self._tasks if t.get("id") != task_id]
        return {"id": task_id, "status": "deleted"}

    def task_update(self, task_id: str, fields: dict) -> dict:
        """Update fields on a task."""
        for t in self._tasks + self._done:
            if t.get("id") == task_id:
                t.update(fields)
                return {"id": task_id, "status": "updated"}
        return {"id": task_id, "status": "not_found"}

    def task_prioritize(self, task_id: str, priority: str) -> dict:
        """Change task priority."""
        return {"id": task_id, "priority": priority}

    # -- Issue mutations -----------------------------------------------------

    def issue_add(self, desc: str, spec: str = "") -> dict:
        """Add an issue."""
        issue_id = f"i-auto-{len(self._issues)}"
        issue: dict = {"id": issue_id, "desc": desc}
        if spec:
            issue["spec"] = spec
        self._issues.append(issue)
        return {"id": issue_id}

    def issue_done(self) -> dict:
        """Resolve first issue."""
        if self._issues:
            removed = self._issues.pop(0)
            return {"id": removed["id"]}
        return {"id": ""}

    def issue_done_all(self) -> dict:
        """Resolve all issues."""
        count = len(self._issues)
        self._issues.clear()
        return {"count": count}

    def issue_done_ids(self, ids: list[str]) -> dict:
        """Resolve specific issues by ID."""
        self.resolved_ids.append(ids)
        self._issues = [i for i in self._issues if i.get("id") not in ids]
        return {"count": len(ids)}


# Export the fixtures
__all__ = ["tmp_ralph_dir", "mock_state", "mock_config", "mock_opencode", "MockTix"]
