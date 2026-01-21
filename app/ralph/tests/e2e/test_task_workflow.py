"""E2E tests for ralph task workflow commands (add, done, accept, reject)."""

import json
import os
import subprocess
import sys
from pathlib import Path

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


def load_state_from_file(plan_path: Path) -> dict:
    """Load state from plan.jsonl and return parsed structure."""
    tasks = []
    tombstones_accepted = []
    tombstones_rejected = []
    spec = None

    if plan_path.exists():
        for line in plan_path.read_text().strip().split("\n"):
            if not line.strip():
                continue
            d = json.loads(line)
            t = d.get("t")
            if t == "task":
                tasks.append(d)
            elif t == "accept":
                tombstones_accepted.append(d)
            elif t == "reject":
                tombstones_rejected.append(d)
            elif t == "spec":
                spec = d.get("spec")

    return {
        "spec": spec,
        "tasks": tasks,
        "tombstones_accepted": tombstones_accepted,
        "tombstones_rejected": tombstones_rejected,
    }


def test_add_task(tmp_path: Path):
    """Test that ralph task add creates a new task."""
    plan_path = init_ralph_with_git(tmp_path)

    result = run_ralph("task", "add", "Implement new feature", cwd=tmp_path)

    assert result.returncode == 0, f"Task add failed: {result.stderr}"
    assert "Task added" in result.stdout

    state = load_state_from_file(plan_path)
    assert len(state["tasks"]) == 1
    task = state["tasks"][0]
    assert task["name"] == "Implement new feature"
    assert task["s"] == "p"
    assert task["id"].startswith("t-")


def test_add_task_with_json(tmp_path: Path):
    """Test that ralph task add accepts JSON format."""
    plan_path = init_ralph_with_git(tmp_path)

    task_json = json.dumps(
        {
            "name": "Complex task",
            "notes": "Implementation notes here",
            "accept": "pytest tests/ passes",
            "priority": "high",
        }
    )
    result = run_ralph("task", "add", task_json, cwd=tmp_path)

    assert result.returncode == 0, f"Task add failed: {result.stderr}"

    state = load_state_from_file(plan_path)
    assert len(state["tasks"]) == 1
    task = state["tasks"][0]
    assert task["name"] == "Complex task"
    assert task["notes"] == "Implementation notes here"
    assert task["accept"] == "pytest tests/ passes"
    assert task["priority"] == "high"


def test_mark_task_done(tmp_path: Path):
    """Test that ralph task done marks a task as done."""
    plan_path = init_ralph_with_git(tmp_path)

    run_ralph("task", "add", "Task to complete", cwd=tmp_path)
    state = load_state_from_file(plan_path)
    task_id = state["tasks"][0]["id"]

    result = run_ralph("task", "done", task_id, cwd=tmp_path)

    assert result.returncode == 0, f"Task done failed: {result.stderr}"
    assert "Task done" in result.stdout

    state = load_state_from_file(plan_path)
    assert len(state["tasks"]) == 1
    task = state["tasks"][0]
    assert task["s"] == "d"
    assert task.get("done_at") is not None


def test_mark_task_done_auto_select(tmp_path: Path):
    """Test that ralph task done auto-selects next pending task."""
    plan_path = init_ralph_with_git(tmp_path)

    run_ralph("task", "add", "First task", cwd=tmp_path)

    result = run_ralph("task", "done", cwd=tmp_path)

    assert result.returncode == 0, f"Task done failed: {result.stderr}"
    assert "Task done" in result.stdout

    state = load_state_from_file(plan_path)
    assert state["tasks"][0]["s"] == "d"


def test_accept_task(tmp_path: Path):
    """Test that ralph task accept creates tombstone and removes task."""
    plan_path = init_ralph_with_git(tmp_path)

    run_ralph("task", "add", "Task to accept", cwd=tmp_path)
    state = load_state_from_file(plan_path)
    task_id = state["tasks"][0]["id"]

    run_ralph("task", "done", task_id, cwd=tmp_path)

    result = run_ralph("task", "accept", task_id, cwd=tmp_path)

    assert result.returncode == 0, f"Task accept failed: {result.stderr}"
    assert "accepted" in result.stdout.lower()

    state = load_state_from_file(plan_path)
    assert len(state["tasks"]) == 0
    assert len(state["tombstones_accepted"]) == 1
    assert state["tombstones_accepted"][0]["id"] == task_id


def test_accept_all_done_tasks(tmp_path: Path):
    """Test that ralph task accept without ID accepts all done tasks."""
    plan_path = init_ralph_with_git(tmp_path)

    run_ralph("task", "add", "Task 1", cwd=tmp_path)
    run_ralph("task", "add", "Task 2", cwd=tmp_path)
    state = load_state_from_file(plan_path)
    task1_id = state["tasks"][0]["id"]
    task2_id = state["tasks"][1]["id"]

    run_ralph("task", "done", task1_id, cwd=tmp_path)
    run_ralph("task", "done", task2_id, cwd=tmp_path)

    result = run_ralph("task", "accept", cwd=tmp_path)

    assert result.returncode == 0, f"Task accept failed: {result.stderr}"
    assert "2 tasks" in result.stdout.lower() or "accepted" in result.stdout.lower()

    state = load_state_from_file(plan_path)
    assert len(state["tasks"]) == 0
    assert len(state["tombstones_accepted"]) == 2


def test_reject_task(tmp_path: Path):
    """Test that ralph task reject creates tombstone and resets task to pending."""
    plan_path = init_ralph_with_git(tmp_path)

    run_ralph("task", "add", "Task to reject", cwd=tmp_path)
    state = load_state_from_file(plan_path)
    task_id = state["tasks"][0]["id"]

    run_ralph("task", "done", task_id, cwd=tmp_path)

    result = run_ralph("task", "reject", task_id, "Tests failed", cwd=tmp_path)

    assert result.returncode == 0, f"Task reject failed: {result.stderr}"
    assert "rejected" in result.stdout.lower()

    state = load_state_from_file(plan_path)
    assert len(state["tasks"]) == 1
    task = state["tasks"][0]
    assert task["s"] == "p"
    assert task.get("reject") == "Tests failed"
    assert len(state["tombstones_rejected"]) == 1
    assert state["tombstones_rejected"][0]["id"] == task_id
    assert state["tombstones_rejected"][0]["reason"] == "Tests failed"


def test_reject_task_auto_select(tmp_path: Path):
    """Test that ralph task reject auto-selects first done task."""
    plan_path = init_ralph_with_git(tmp_path)

    run_ralph("task", "add", "Task to reject", cwd=tmp_path)
    run_ralph("task", "done", cwd=tmp_path)

    result = run_ralph("task", "reject", cwd=tmp_path)

    assert result.returncode == 0, f"Task reject failed: {result.stderr}"

    state = load_state_from_file(plan_path)
    assert state["tasks"][0]["s"] == "p"
    assert len(state["tombstones_rejected"]) == 1


def test_task_workflow_full_cycle(tmp_path: Path):
    """Test complete workflow: add -> done -> reject -> done -> accept."""
    plan_path = init_ralph_with_git(tmp_path)

    result = run_ralph("task", "add", "Full cycle task", cwd=tmp_path)
    assert result.returncode == 0

    state = load_state_from_file(plan_path)
    task_id = state["tasks"][0]["id"]

    result = run_ralph("task", "done", task_id, cwd=tmp_path)
    assert result.returncode == 0
    state = load_state_from_file(plan_path)
    assert state["tasks"][0]["s"] == "d"

    result = run_ralph("task", "reject", task_id, "First attempt failed", cwd=tmp_path)
    assert result.returncode == 0
    state = load_state_from_file(plan_path)
    assert state["tasks"][0]["s"] == "p"
    assert len(state["tombstones_rejected"]) == 1

    result = run_ralph("task", "done", task_id, cwd=tmp_path)
    assert result.returncode == 0
    state = load_state_from_file(plan_path)
    assert state["tasks"][0]["s"] == "d"

    result = run_ralph("task", "accept", task_id, cwd=tmp_path)
    assert result.returncode == 0
    state = load_state_from_file(plan_path)
    assert len(state["tasks"]) == 0
    assert len(state["tombstones_accepted"]) == 1
    assert len(state["tombstones_rejected"]) == 1
