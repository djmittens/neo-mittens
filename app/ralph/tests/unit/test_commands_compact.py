import pytest
import os
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import json

from ralph.commands.compact import cmd_compact, is_task_too_old
from ralph.config import GlobalConfig
from ralph.models import Task, Tombstone
from ralph.state import RalphState, save_state, load_state


@pytest.fixture
def mock_state_dir(tmp_path):
    # Create mock tasks and tombstones with a fixed date
    fixed_now = datetime(2026, 2, 1, 12, 0, 0)  # Fixed reference datetime
    old_done_task = Task(
        id="old-done",
        name="Old Completed Task",
        spec="test.md",
        status="DONE",
        done_at=(fixed_now - timedelta(days=40)).isoformat(),
    )
    recent_done_task = Task(
        id="recent-done",
        name="Recent Completed Task",
        spec="test.md",
        status="DONE",
        done_at=(fixed_now - timedelta(days=10)).isoformat(),
    )
    active_task = Task(id="active", name="Active Task", spec="test.md", status="p")

    # Create mock state
    state = RalphState(
        tasks=[old_done_task, recent_done_task, active_task],
        tombstones={
            "accepted": [
                Tombstone(
                    id="tomb1",
                    tombstone_type="accept",
                    done_at=(fixed_now - timedelta(days=40)).isoformat(),
                    reason="test",
                    name=old_done_task.name,
                ),
                Tombstone(
                    id="tomb2",
                    tombstone_type="accept",
                    done_at=(fixed_now - timedelta(days=10)).isoformat(),
                    reason="test",
                    name=recent_done_task.name,
                ),
            ],
            "rejected": [],  # Explicitly add rejected list
        },
    )

    # Save mock state to plan.jsonl in the temp directory
    plan_file = tmp_path / "plan.jsonl"
    save_state(state, plan_file)
    return tmp_path


def test_is_task_too_old():
    # Test the helper function
    now = datetime(2026, 2, 1, 12, 0, 0)
    threshold_date = now - timedelta(days=30)

    # Task less than 30 days old should return False
    recent_task_date = (now - timedelta(days=10)).isoformat()
    assert not is_task_too_old(recent_task_date, threshold_date)

    # Task more than 30 days old should return True
    old_task_date = (now - timedelta(days=40)).isoformat()
    assert is_task_too_old(old_task_date, threshold_date)


def test_compact_command(mock_state_dir, monkeypatch):
    # Use a fixed datetime to make the test deterministic
    fixed_now = datetime(2026, 2, 1, 12, 0, 0)

    # Monkeypatch datetime.now() to return our fixed datetime
    # Inherit from datetime to retain all other methods like fromisoformat
    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    # Monkeypatch datetime module to use our fixed time
    monkeypatch.setattr("ralph.commands.compact.datetime", MockDateTime)

    # Change to the temp directory where plan.jsonl is located
    original_cwd = os.getcwd()
    os.chdir(mock_state_dir)

    try:
        # Create mock config
        config = GlobalConfig(model="test-model", context_window=4000)

        # Create an empty args object
        class Args:
            pass

        args = Args()

        # Capture the state before compaction
        plan_file = mock_state_dir / "plan.jsonl"
        with open(plan_file, "r") as f:
            original_lines = f.readlines()
            print("Original file contents:")
            for line in original_lines:
                print(line.strip())

        # Run compact command
        cmd_compact(config, args)

        # Verify the state was compacted correctly
        # Reload the state to ensure exact contents
        reloaded_state = load_state(plan_file)

        # Manually identify task IDs
        task_ids = [task.id for task in reloaded_state.tasks]
        print("\nTask IDs:", task_ids)

        assert "active" in task_ids  # Active task should be kept
        assert "recent-done" in task_ids  # Recent done task should be kept
        assert "old-done" not in task_ids  # Old done task should be removed
    finally:
        # Restore original working directory
        os.chdir(original_cwd)
