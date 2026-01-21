import pytest
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import json

from ralph.commands.compact import cmd_compact, is_task_too_old
from ralph.config import GlobalConfig
from ralph.models import Task, Tombstone
from ralph.state import RalphState, save_state, load_state


@pytest.fixture
def mock_state_file():
    # Create a temporary state file for testing
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as temp_file:
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

        # Save mock state to temp file
        save_state(state, Path(temp_file.name))
        return temp_file.name


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


def test_compact_command(mock_state_file, monkeypatch, tmp_path):
    # Use a fixed datetime to make the test deterministic
    fixed_now = datetime(2026, 2, 1, 12, 0, 0)

    # Monkeypatch datetime.now() to return our fixed datetime
    class MockDateTime:
        @classmethod
        def now(cls):
            return fixed_now

    # Monkeypatch datetime module to use our fixed time
    monkeypatch.setattr("ralph.commands.compact.datetime", MockDateTime)

    # Create mock config
    config = GlobalConfig(model="test-model", context_window=4000)

    # Create an empty args object
    class Args:
        pass

    args = Args()

    # Capture the state before compaction
    with open(mock_state_file, "r") as f:
        original_lines = f.readlines()
        print("Original file contents:")
        for line in original_lines:
            print(line.strip())

    # Run compact command on the mock state file
    cmd_compact(config, args)

    # Verify the state was compacted correctly
    # Reload the state to ensure exact contents
    reloaded_state = load_state(Path(mock_state_file))

    # Manually identify task IDs
    task_ids = [task.id for task in reloaded_state.tasks]
    print("\nTask IDs:", task_ids)

    assert "active" in task_ids  # Active task should be kept
    assert "recent-done" in task_ids  # Recent done task should be kept
    assert "old-done" not in task_ids  # Old done task should be removed
