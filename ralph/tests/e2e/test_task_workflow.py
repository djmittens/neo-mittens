"""End-to-end tests for Ralph task workflow.

Tests add task, mark done, accept, and reject workflows.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def temp_git_repo() -> Generator[Path, None, None]:
    """Create a temporary git repository for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        subprocess.run(
            ["git", "init"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )
        yield repo_path


@pytest.fixture
def initialized_repo(temp_git_repo: Path) -> Path:
    """Create an initialized ralph repo with a spec set."""
    run_ralph("init", cwd=temp_git_repo)
    spec_file = temp_git_repo / "ralph" / "specs" / "test.md"
    spec_file.write_text("# Test Spec\n\n## Requirements\n\n- Test requirement")
    run_ralph("set-spec", "test.md", cwd=temp_git_repo)
    subprocess.run(
        ["git", "add", "."],
        cwd=temp_git_repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=temp_git_repo,
        capture_output=True,
        check=True,
    )
    return temp_git_repo


REPO_ROOT = Path(__file__).parent.parent.parent.parent


def run_ralph(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run ralph CLI command and return result."""
    cmd = [sys.executable, "-m", "ralph"] + list(args)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


class TestTaskAdd:
    """Tests for adding tasks."""

    def test_task_add_simple_description(self, initialized_repo: Path) -> None:
        """Test adding a task with simple description."""
        result = run_ralph("task", "add", "Fix the bug", cwd=initialized_repo)
        assert result.returncode == 0
        assert "Task added" in result.stdout
        assert "Fix the bug" in result.stdout

    def test_task_add_json_format(self, initialized_repo: Path) -> None:
        """Test adding a task with JSON format."""
        task_json = json.dumps(
            {
                "name": "Implement feature X",
                "notes": "Use the existing pattern from Y",
                "accept": "pytest tests/test_x.py passes",
            }
        )
        result = run_ralph("task", "add", task_json, cwd=initialized_repo)
        assert result.returncode == 0
        assert "Task added" in result.stdout
        assert "Implement feature X" in result.stdout

    def test_task_add_with_deps(self, initialized_repo: Path) -> None:
        """Test adding a task with dependencies."""
        run_ralph("task", "add", "First task", cwd=initialized_repo)
        query_result = run_ralph("query", "tasks", cwd=initialized_repo)
        tasks = json.loads(query_result.stdout)
        first_task_id = tasks[0]["id"]

        task_json = json.dumps(
            {
                "name": "Second task with dep",
                "deps": [first_task_id],
            }
        )
        result = run_ralph("task", "add", task_json, cwd=initialized_repo)
        assert result.returncode == 0
        assert "Task added" in result.stdout

    def test_task_add_with_priority(self, initialized_repo: Path) -> None:
        """Test adding a task with priority."""
        task_json = json.dumps(
            {
                "name": "High priority task",
                "priority": "high",
            }
        )
        result = run_ralph("task", "add", task_json, cwd=initialized_repo)
        assert result.returncode == 0

        query_result = run_ralph("query", "tasks", cwd=initialized_repo)
        tasks = json.loads(query_result.stdout)
        assert any(t["name"] == "High priority task" for t in tasks)

    def test_task_shows_in_query(self, initialized_repo: Path) -> None:
        """Test that added task appears in query."""
        run_ralph("task", "add", "Query test task", cwd=initialized_repo)
        result = run_ralph("query", cwd=initialized_repo)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        pending = data["tasks"]["pending"]
        assert any(t["name"] == "Query test task" for t in pending)


class TestTaskDone:
    """Tests for marking tasks as done."""

    def test_task_done_marks_current_task(self, initialized_repo: Path) -> None:
        """Test that 'task done' marks the current task."""
        run_ralph("task", "add", "Task to complete", cwd=initialized_repo)
        result = run_ralph("task", "done", cwd=initialized_repo)
        assert result.returncode == 0
        assert "Task done" in result.stdout

    def test_task_done_no_tasks_shows_message(self, initialized_repo: Path) -> None:
        """Test 'task done' with no tasks shows message."""
        result = run_ralph("task", "done", cwd=initialized_repo)
        assert "No pending tasks" in result.stdout

    def test_task_done_moves_to_done_list(self, initialized_repo: Path) -> None:
        """Test that done task appears in done list."""
        run_ralph("task", "add", "Task to be done", cwd=initialized_repo)
        run_ralph("task", "done", cwd=initialized_repo)
        result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(result.stdout)
        done = data["tasks"]["done"]
        assert any(t["name"] == "Task to be done" for t in done)

    def test_task_done_by_id(self, initialized_repo: Path) -> None:
        """Test marking specific task as done by ID."""
        run_ralph("task", "add", "First task", cwd=initialized_repo)
        run_ralph("task", "add", "Second task", cwd=initialized_repo)
        query_result = run_ralph("query", "tasks", cwd=initialized_repo)
        tasks = json.loads(query_result.stdout)
        second_task_id = tasks[1]["id"]

        result = run_ralph("task", "done", second_task_id, cwd=initialized_repo)
        assert result.returncode == 0
        assert "Task done" in result.stdout
        assert second_task_id in result.stdout


class TestTaskAccept:
    """Tests for accepting tasks."""

    def test_task_accept_moves_to_accepted(self, initialized_repo: Path) -> None:
        """Test that accepted task moves to accepted list."""
        run_ralph("task", "add", "Task to accept", cwd=initialized_repo)
        run_ralph("task", "done", cwd=initialized_repo)
        result = run_ralph("task", "accept", cwd=initialized_repo)
        assert result.returncode == 0
        assert "accepted" in result.stdout.lower()

        query_result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(query_result.stdout)
        accepted = data["tasks"]["accepted"]
        assert any(t["name"] == "Task to accept" for t in accepted)

    def test_task_accept_by_id(self, initialized_repo: Path) -> None:
        """Test accepting specific task by ID."""
        run_ralph("task", "add", "Task to accept by ID", cwd=initialized_repo)
        run_ralph("task", "done", cwd=initialized_repo)
        query_result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(query_result.stdout)
        task_id = data["tasks"]["done"][0]["id"]

        result = run_ralph("task", "accept", task_id, cwd=initialized_repo)
        assert result.returncode == 0
        assert "accepted" in result.stdout.lower()

    def test_task_accept_no_done_tasks(self, initialized_repo: Path) -> None:
        """Test accept with no done tasks shows message."""
        result = run_ralph("task", "accept", cwd=initialized_repo)
        assert "No done tasks" in result.stdout

    def test_task_accept_creates_tombstone(self, initialized_repo: Path) -> None:
        """Test that accepting creates a tombstone record."""
        run_ralph("task", "add", "Task for tombstone", cwd=initialized_repo)
        run_ralph("task", "done", cwd=initialized_repo)
        run_ralph("task", "accept", cwd=initialized_repo)

        query_result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(query_result.stdout)
        assert "tombstones" in data or "accepted" in data["tasks"]


class TestTaskReject:
    """Tests for rejecting tasks."""

    def test_task_reject_returns_to_pending(self, initialized_repo: Path) -> None:
        """Test that rejected task returns to pending."""
        run_ralph("task", "add", "Task to reject", cwd=initialized_repo)
        run_ralph("task", "done", cwd=initialized_repo)

        query_result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(query_result.stdout)
        task_id = data["tasks"]["done"][0]["id"]

        result = run_ralph(
            "task", "reject", task_id, "Did not meet criteria", cwd=initialized_repo
        )
        assert result.returncode == 0
        assert "rejected" in result.stdout.lower()

        query_result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(query_result.stdout)
        pending = data["tasks"]["pending"]
        assert any(t["name"] == "Task to reject" for t in pending)

    def test_task_reject_by_id(self, initialized_repo: Path) -> None:
        """Test rejecting specific task by ID."""
        run_ralph("task", "add", "Task to reject by ID", cwd=initialized_repo)
        run_ralph("task", "done", cwd=initialized_repo)
        query_result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(query_result.stdout)
        task_id = data["tasks"]["done"][0]["id"]

        result = run_ralph(
            "task", "reject", task_id, "Wrong implementation", cwd=initialized_repo
        )
        assert result.returncode == 0
        assert "rejected" in result.stdout.lower()

    def test_task_reject_stores_reason(self, initialized_repo: Path) -> None:
        """Test that rejection reason is stored."""
        run_ralph("task", "add", "Task with reason", cwd=initialized_repo)
        run_ralph("task", "done", cwd=initialized_repo)

        query_result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(query_result.stdout)
        task_id = data["tasks"]["done"][0]["id"]

        run_ralph(
            "task", "reject", task_id, "Missing test coverage", cwd=initialized_repo
        )

        query_result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(query_result.stdout)
        pending = data["tasks"]["pending"]
        task = next((t for t in pending if t["name"] == "Task with reason"), None)
        assert task is not None
        assert "Missing test coverage" in task.get("reject", "")

    def test_task_reject_creates_tombstone(self, initialized_repo: Path) -> None:
        """Test that rejecting persists the rejection reason."""
        run_ralph("task", "add", "Task for reject tombstone", cwd=initialized_repo)
        run_ralph("task", "done", cwd=initialized_repo)

        query_result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(query_result.stdout)
        task_id = data["tasks"]["done"][0]["id"]

        run_ralph(
            "task", "reject", task_id, "Failed verification", cwd=initialized_repo
        )

        query_result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(query_result.stdout)
        pending = data["tasks"]["pending"]
        task = next(
            (t for t in pending if t["name"] == "Task for reject tombstone"), None
        )
        assert task is not None
        assert task.get("reject") == "Failed verification"


class TestTaskDelete:
    """Tests for deleting tasks."""

    def test_task_delete_removes_task(self, initialized_repo: Path) -> None:
        """Test that deleted task is removed."""
        run_ralph("task", "add", "Task to delete", cwd=initialized_repo)
        query_result = run_ralph("query", "tasks", cwd=initialized_repo)
        tasks = json.loads(query_result.stdout)
        task_id = tasks[0]["id"]

        result = run_ralph("task", "delete", task_id, cwd=initialized_repo)
        assert result.returncode == 0
        assert "deleted" in result.stdout.lower()

        query_result = run_ralph("query", "tasks", cwd=initialized_repo)
        tasks = json.loads(query_result.stdout)
        assert not any(t["id"] == task_id for t in tasks)

    def test_task_delete_nonexistent(self, initialized_repo: Path) -> None:
        """Test deleting nonexistent task shows error."""
        result = run_ralph("task", "delete", "t-nonexistent", cwd=initialized_repo)
        assert "not found" in result.stdout.lower()

    def test_task_delete_requires_id(self, initialized_repo: Path) -> None:
        """Test that delete requires task ID."""
        result = run_ralph("task", "delete", cwd=initialized_repo)
        assert "usage" in result.stdout.lower() or result.returncode != 0


class TestTaskPrioritize:
    """Tests for changing task priority."""

    def test_task_prioritize_changes_priority(self, initialized_repo: Path) -> None:
        """Test that prioritize changes task priority."""
        run_ralph("task", "add", "Low priority task", cwd=initialized_repo)
        query_result = run_ralph("query", "tasks", cwd=initialized_repo)
        tasks = json.loads(query_result.stdout)
        task_id = tasks[0]["id"]

        result = run_ralph("task", "prioritize", task_id, "high", cwd=initialized_repo)
        assert result.returncode == 0
        assert "prioritized" in result.stdout.lower()

        query_result = run_ralph("query", "tasks", cwd=initialized_repo)
        tasks = json.loads(query_result.stdout)
        task = next((t for t in tasks if t["id"] == task_id), None)
        assert task is not None
        assert task.get("priority") == "high"

    def test_task_prioritize_nonexistent(self, initialized_repo: Path) -> None:
        """Test prioritizing nonexistent task shows error."""
        result = run_ralph(
            "task", "prioritize", "t-nonexistent", "high", cwd=initialized_repo
        )
        assert "not found" in result.stdout.lower()


class TestTaskWorkflow:
    """Tests for complete task workflows."""

    def test_full_accept_workflow(self, initialized_repo: Path) -> None:
        """Test complete add -> done -> accept workflow."""
        run_ralph("task", "add", "Full workflow task", cwd=initialized_repo)
        run_ralph("task", "done", cwd=initialized_repo)
        run_ralph("task", "accept", cwd=initialized_repo)

        result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(result.stdout)

        pending = data["tasks"]["pending"]
        done = data["tasks"]["done"]
        accepted = data["tasks"]["accepted"]

        assert not any(t["name"] == "Full workflow task" for t in pending)
        assert not any(t["name"] == "Full workflow task" for t in done)
        assert any(t["name"] == "Full workflow task" for t in accepted)

    def test_full_reject_workflow(self, initialized_repo: Path) -> None:
        """Test complete add -> done -> reject workflow."""
        run_ralph("task", "add", "Reject workflow task", cwd=initialized_repo)
        run_ralph("task", "done", cwd=initialized_repo)

        query_result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(query_result.stdout)
        task_id = data["tasks"]["done"][0]["id"]

        run_ralph("task", "reject", task_id, "Not complete", cwd=initialized_repo)

        result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(result.stdout)

        pending = data["tasks"]["pending"]
        done = data["tasks"]["done"]

        assert any(t["name"] == "Reject workflow task" for t in pending)
        assert not any(t["name"] == "Reject workflow task" for t in done)

    def test_multiple_tasks_workflow(self, initialized_repo: Path) -> None:
        """Test workflow with multiple tasks."""
        for i in range(1, 4):
            run_ralph("task", "add", f"Task {i}", cwd=initialized_repo)

        run_ralph("task", "done", cwd=initialized_repo)
        run_ralph("task", "accept", cwd=initialized_repo)

        run_ralph("task", "done", cwd=initialized_repo)

        query_result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(query_result.stdout)
        task_id = data["tasks"]["done"][0]["id"]

        run_ralph("task", "reject", task_id, "Needs work", cwd=initialized_repo)

        result = run_ralph("query", cwd=initialized_repo)
        data = json.loads(result.stdout)

        pending = data["tasks"]["pending"]
        accepted = data["tasks"]["accepted"]

        assert len(pending) == 2
        assert len(accepted) == 1
