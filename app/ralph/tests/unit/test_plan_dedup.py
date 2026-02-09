"""Tests for shared LLM task dedup (reconcile._build_dedup_prompt, dedup_tasks)."""

import json
import pytest
from unittest.mock import MagicMock

from ralph.reconcile import _build_dedup_prompt, dedup_tasks
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


class TestDedupTasks:
    """Tests for the shared dedup_tasks function."""

    def _mock_llm_response(self, keep: list[str], dropped: list[str]):
        """Return an llm_fn that produces a keep/drop response."""
        data = {"keep": keep, "dropped": dropped}
        output = f'[RALPH_OUTPUT]\n{json.dumps(data)}\n[/RALPH_OUTPUT]'
        return lambda prompt: output

    def test_skips_small_task_lists(self):
        """Plans with <= 8 tasks skip dedup entirely."""
        tix = _MockTix(tasks=[
            {"id": f"t-{i}", "name": f"Task {i}"} for i in range(5)
        ])
        llm_fn = MagicMock()
        dropped = dedup_tasks(tix, llm_fn)
        assert dropped == 0
        llm_fn.assert_not_called()

    def test_drops_duplicates(self):
        """Model identifies duplicates and they get deleted."""
        tasks = [
            {"id": f"t-{i:04x}", "name": f"Task {i}"} for i in range(10)
        ]
        tix = _MockTix(tasks=tasks)

        keep = [f"t-{i:04x}" for i in range(8)]
        dropped = [f"t-{i:04x}" for i in range(8, 10)]
        llm_fn = self._mock_llm_response(keep, dropped)

        count = dedup_tasks(tix, llm_fn)
        assert count == 2
        remaining_ids = {t["id"] for t in tix.query_tasks()}
        assert "t-0008" not in remaining_ids
        assert "t-0009" not in remaining_ids
        assert "t-0000" in remaining_ids

    def test_no_output_returns_zero(self):
        """If LLM returns None, no tasks are dropped."""
        tasks = [{"id": f"t-{i}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)

        count = dedup_tasks(tix, lambda prompt: None)
        assert count == 0

    def test_unparseable_output_returns_zero(self):
        """If structured output can't be parsed, no tasks are dropped."""
        tasks = [{"id": f"t-{i}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)

        count = dedup_tasks(tix, lambda prompt: "garbage output")
        assert count == 0

    def test_safety_rejects_too_aggressive_dedup(self):
        """If model wants to drop >50% of tasks, we reject the dedup."""
        tasks = [{"id": f"t-{i:04x}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)

        keep = [f"t-{i:04x}" for i in range(3)]
        dropped = [f"t-{i:04x}" for i in range(3, 10)]
        llm_fn = self._mock_llm_response(keep, dropped)

        count = dedup_tasks(tix, llm_fn)
        assert count == 0  # Safety check should reject

    def test_empty_keep_list_drops_nothing(self):
        """If model returns empty keep list, nothing is dropped."""
        tasks = [{"id": f"t-{i}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)
        llm_fn = self._mock_llm_response([], ["t-0", "t-1"])

        count = dedup_tasks(tix, llm_fn)
        assert count == 0

    def test_contradictory_ids_skipped(self):
        """If a task ID appears in both keep and dropped, it's kept."""
        tasks = [{"id": f"t-{i:04x}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)

        keep = [f"t-{i:04x}" for i in range(10)]
        dropped = ["t-0009"]
        llm_fn = self._mock_llm_response(keep, dropped)

        count = dedup_tasks(tix, llm_fn)
        assert count == 0  # Contradictory, should be skipped

    def test_unknown_ids_in_dropped_ignored(self):
        """Unknown task IDs in dropped list are silently ignored."""
        tasks = [{"id": f"t-{i:04x}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)

        keep = [f"t-{i:04x}" for i in range(9)]
        dropped = ["t-0009", "t-unknown"]
        llm_fn = self._mock_llm_response(keep, dropped)

        count = dedup_tasks(tix, llm_fn)
        assert count == 1  # Only t-0009 should be dropped

    def test_custom_min_tasks(self):
        """Custom min_tasks threshold controls when dedup runs."""
        tasks = [{"id": f"t-{i}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)
        llm_fn = MagicMock()

        # With min_tasks=15, 10 tasks should skip
        count = dedup_tasks(tix, llm_fn, min_tasks=15)
        assert count == 0
        llm_fn.assert_not_called()

    def test_llm_fn_receives_prompt(self):
        """The LLM callable receives the dedup prompt."""
        tasks = [{"id": f"t-{i}", "name": f"Task {i}"} for i in range(10)]
        tix = _MockTix(tasks=tasks)

        captured_prompt = []
        def llm_fn(prompt):
            captured_prompt.append(prompt)
            return None  # No output

        dedup_tasks(tix, llm_fn)
        assert len(captured_prompt) == 1
        assert "[RALPH_OUTPUT]" in captured_prompt[0]
        assert "t-0" in captured_prompt[0]
