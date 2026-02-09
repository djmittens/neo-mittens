"""Tests for plan dedup pass (_build_dedup_prompt, _dedup_plan_tasks)."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from ralph.commands.plan import _build_dedup_prompt, _dedup_plan_tasks
from ralph.context import Metrics
from ralph.tests.conftest import MockTix as _MockTix


class TestBuildDedupPrompt:
    """Tests for _build_dedup_prompt."""

    def test_includes_all_task_ids(self):
        tasks = [
            {"id": "t-aaa", "name": "Rename types in gc_mark.c (lines 16-356)", "notes": "Replace old types."},
            {"id": "t-bbb", "name": "Rename types and functions in gc_mark.c:16-356", "notes": "Better notes."},
        ]
        prompt = _build_dedup_prompt(tasks)
        assert "[t-aaa]" in prompt
        assert "[t-bbb]" in prompt

    def test_includes_task_names(self):
        tasks = [
            {"id": "t-111", "name": "Update LSAN suppressions", "notes": "Fix leaks."},
        ]
        prompt = _build_dedup_prompt(tasks)
        assert "Update LSAN suppressions" in prompt

    def test_truncates_long_notes(self):
        long_notes = "x" * 200
        tasks = [{"id": "t-aaa", "name": "Task A", "notes": long_notes}]
        prompt = _build_dedup_prompt(tasks)
        # Notes should be truncated with "..."
        assert "..." in prompt
        assert "x" * 121 not in prompt  # Should not contain full 200 chars

    def test_includes_count(self):
        tasks = [
            {"id": f"t-{i:03d}", "name": f"Task {i}", "notes": f"Notes for task {i}."}
            for i in range(12)
        ]
        prompt = _build_dedup_prompt(tasks)
        assert "12 total" in prompt

    def test_output_format_instructions(self):
        tasks = [{"id": "t-aaa", "name": "Task A", "notes": "Notes."}]
        prompt = _build_dedup_prompt(tasks)
        assert "[RALPH_OUTPUT]" in prompt
        assert '"keep"' in prompt
        assert '"dropped"' in prompt


class TestDedupPlanTasks:
    """Tests for _dedup_plan_tasks."""

    def _mock_opencode_response(self, keep: list[str], dropped: list[str]) -> str:
        """Build a fake opencode JSON event stream with dedup output."""
        data = {"keep": keep, "dropped": dropped}
        return f'[RALPH_OUTPUT]\n{json.dumps(data)}\n[/RALPH_OUTPUT]'

    def test_skips_small_plans(self):
        """Plans with <= 8 tasks skip dedup entirely."""
        tix = _MockTix(tasks=[
            {"id": f"t-{i}", "name": f"Task {i}"} for i in range(5)
        ])
        config = MagicMock()
        dropped = _dedup_plan_tasks(tix, config, Path("/tmp"))
        assert dropped == 0

    @patch("ralph.commands.plan._run_opencode")
    def test_drops_duplicates(self, mock_run):
        """Model identifies duplicates and they get deleted."""
        tasks = [
            {"id": f"t-{i:04x}", "name": f"Task {i}"} for i in range(10)
        ]
        tix = _MockTix(tasks=tasks)

        # Model says to keep first 8, drop last 2
        keep = [f"t-{i:04x}" for i in range(8)]
        dropped = [f"t-{i:04x}" for i in range(8, 10)]
        response = self._mock_opencode_response(keep, dropped)
        mock_run.return_value = (response, Metrics(), None)

        config = MagicMock()
        count = _dedup_plan_tasks(tix, config, Path("/tmp"))
        assert count == 2
        # Verify tasks were actually deleted from MockTix
        remaining_ids = {t["id"] for t in tix.query_tasks()}
        assert "t-0008" not in remaining_ids
        assert "t-0009" not in remaining_ids
        assert "t-0000" in remaining_ids

    @patch("ralph.commands.plan._run_opencode")
    def test_no_output_returns_zero(self, mock_run):
        """If opencode returns None, no tasks are dropped."""
        tasks = [{"id": f"t-{i}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)
        mock_run.return_value = (None, Metrics(), None)

        config = MagicMock()
        count = _dedup_plan_tasks(tix, config, Path("/tmp"))
        assert count == 0

    @patch("ralph.commands.plan._run_opencode")
    def test_unparseable_output_returns_zero(self, mock_run):
        """If structured output can't be parsed, no tasks are dropped."""
        tasks = [{"id": f"t-{i}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)
        mock_run.return_value = ("garbage output", Metrics(), None)

        config = MagicMock()
        count = _dedup_plan_tasks(tix, config, Path("/tmp"))
        assert count == 0

    @patch("ralph.commands.plan._run_opencode")
    def test_safety_rejects_too_aggressive_dedup(self, mock_run):
        """If model wants to drop >50% of tasks, we reject the dedup."""
        tasks = [{"id": f"t-{i:04x}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)

        # Model says keep only 3 out of 10 — suspicious
        keep = [f"t-{i:04x}" for i in range(3)]
        dropped = [f"t-{i:04x}" for i in range(3, 10)]
        response = self._mock_opencode_response(keep, dropped)
        mock_run.return_value = (response, Metrics(), None)

        config = MagicMock()
        count = _dedup_plan_tasks(tix, config, Path("/tmp"))
        assert count == 0  # Safety check should reject

    @patch("ralph.commands.plan._run_opencode")
    def test_empty_keep_list_drops_nothing(self, mock_run):
        """If model returns empty keep list, nothing is dropped."""
        tasks = [{"id": f"t-{i}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)
        response = self._mock_opencode_response([], ["t-0", "t-1"])
        mock_run.return_value = (response, Metrics(), None)

        config = MagicMock()
        count = _dedup_plan_tasks(tix, config, Path("/tmp"))
        assert count == 0

    @patch("ralph.commands.plan._run_opencode")
    def test_contradictory_ids_skipped(self, mock_run):
        """If a task ID appears in both keep and dropped, it's kept."""
        tasks = [{"id": f"t-{i:04x}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)

        # t-0009 appears in both keep and dropped — contradiction
        keep = [f"t-{i:04x}" for i in range(10)]
        dropped = ["t-0009"]
        response = self._mock_opencode_response(keep, dropped)
        mock_run.return_value = (response, Metrics(), None)

        config = MagicMock()
        count = _dedup_plan_tasks(tix, config, Path("/tmp"))
        assert count == 0  # Contradictory, should be skipped

    @patch("ralph.commands.plan._run_opencode")
    def test_unknown_ids_in_dropped_ignored(self, mock_run):
        """Unknown task IDs in dropped list are silently ignored."""
        tasks = [{"id": f"t-{i:04x}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)

        keep = [f"t-{i:04x}" for i in range(9)]
        dropped = ["t-0009", "t-unknown"]  # t-unknown doesn't exist
        response = self._mock_opencode_response(keep, dropped)
        mock_run.return_value = (response, Metrics(), None)

        config = MagicMock()
        count = _dedup_plan_tasks(tix, config, Path("/tmp"))
        assert count == 1  # Only t-0009 should be dropped

    @patch("ralph.commands.plan._run_opencode")
    def test_passes_session_id(self, mock_run):
        """Session ID is forwarded to _run_opencode for context reuse."""
        tasks = [{"id": f"t-{i}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)
        response = self._mock_opencode_response(
            [f"t-{i}" for i in range(10)], []
        )
        mock_run.return_value = (response, Metrics(), None)

        config = MagicMock()
        _dedup_plan_tasks(tix, config, Path("/tmp"), session_id="sess-123")

        # Verify session_id was passed through
        call_args = mock_run.call_args
        assert call_args.kwargs.get("session_id") == "sess-123"
