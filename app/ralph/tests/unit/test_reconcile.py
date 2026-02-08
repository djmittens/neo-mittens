"""Tests for ralph.reconcile module."""

import json
import pytest
from unittest.mock import MagicMock, patch

from ralph.reconcile import (
    extract_structured_output,
    reconcile_build,
    reconcile_verify,
    reconcile_investigate,
    reconcile_decompose,
    reconcile_plan,
    ReconcileResult,
)
from ralph.tix import TixError


@pytest.fixture
def mock_tix():
    """Create a mock Tix instance."""
    tix = MagicMock()
    tix.task_add.return_value = {"id": "t-new123"}
    tix.task_done.return_value = {"id": "t-abc", "status": "done"}
    tix.task_accept.return_value = {"id": "t-abc", "status": "accepted"}
    tix.task_reject.return_value = {"id": "t-abc", "status": "rejected"}
    tix.task_delete.return_value = {"id": "t-abc", "status": "deleted"}
    tix.issue_add.return_value = {"id": "i-new123"}
    tix.issue_done_all.return_value = {"count": 2}
    # task_batch_add returns a list of {"id": ...} for each task added
    tix.task_batch_add.side_effect = lambda tasks: [
        {"id": f"t-batch{i}"} for i in range(len(tasks))
    ]
    return tix


# =============================================================================
# extract_structured_output
# =============================================================================


class TestExtractStructuredOutput:
    def test_with_markers(self):
        output = 'Some text\n[RALPH_OUTPUT]\n{"verdict": "done"}\n[/RALPH_OUTPUT]\nMore text'
        result = extract_structured_output(output)
        assert result == {"verdict": "done"}

    def test_with_markers_complex(self):
        data = {"results": [{"task_id": "t-1", "passed": True}]}
        output = f"[RALPH_OUTPUT]\n{json.dumps(data)}\n[/RALPH_OUTPUT]"
        result = extract_structured_output(output)
        assert result == data

    def test_fallback_last_json(self):
        output = 'Some text\n{"verdict": "done", "summary": "implemented"}'
        result = extract_structured_output(output)
        assert result is not None
        assert result["verdict"] == "done"

    def test_no_json(self):
        output = "Just plain text output with no JSON"
        result = extract_structured_output(output)
        assert result is None

    def test_empty_string(self):
        result = extract_structured_output("")
        assert result is None

    def test_marker_with_whitespace(self):
        output = "[RALPH_OUTPUT]\n  {\"verdict\": \"blocked\", \"reason\": \"missing dep\"}  \n[/RALPH_OUTPUT]"
        result = extract_structured_output(output)
        assert result["verdict"] == "blocked"


# =============================================================================
# reconcile_build
# =============================================================================


class TestReconcileBuild:
    def test_done_verdict(self, mock_tix):
        output = '[RALPH_OUTPUT]\n{"verdict": "done", "summary": "all good"}\n[/RALPH_OUTPUT]'
        result = reconcile_build(mock_tix, output, "t-abc")
        assert result.ok
        mock_tix.task_done.assert_called_once_with("t-abc")

    def test_blocked_verdict(self, mock_tix):
        output = '[RALPH_OUTPUT]\n{"verdict": "blocked", "reason": "dep missing"}\n[/RALPH_OUTPUT]'
        result = reconcile_build(mock_tix, output, "t-abc")
        assert not result.ok
        assert "blocked" in result.errors[0].lower()
        mock_tix.task_done.assert_not_called()

    def test_no_structured_output(self, mock_tix):
        result = reconcile_build(mock_tix, "just text", "t-abc")
        assert not result.ok
        assert "No structured output" in result.errors[0]

    def test_with_issues(self, mock_tix):
        output = '[RALPH_OUTPUT]\n{"verdict": "done", "issues": [{"desc": "memory leak"}]}\n[/RALPH_OUTPUT]'
        result = reconcile_build(mock_tix, output, "t-abc")
        assert result.ok
        mock_tix.issue_add.assert_called_once_with("memory leak")
        assert len(result.issues_added) == 1

    def test_task_done_fails(self, mock_tix):
        mock_tix.task_done.side_effect = TixError("not found")
        output = '[RALPH_OUTPUT]\n{"verdict": "done"}\n[/RALPH_OUTPUT]'
        result = reconcile_build(mock_tix, output, "t-abc")
        assert not result.ok


# =============================================================================
# reconcile_verify
# =============================================================================


class TestReconcileVerify:
    def test_all_pass(self, mock_tix):
        output = '[RALPH_OUTPUT]\n{"results": [{"task_id": "t-1", "passed": true}, {"task_id": "t-2", "passed": true}], "spec_complete": true}\n[/RALPH_OUTPUT]'
        result = reconcile_verify(mock_tix, output)
        assert result.ok
        assert len(result.tasks_accepted) == 2

    def test_mixed_results(self, mock_tix):
        mock_tix.query_full.return_value = {
            "tasks": {"pending": [], "done": [{"id": "t-2", "reject_count": 0}]},
        }
        mock_tix.task_update.return_value = {"id": "t-2", "status": "updated"}
        output = '[RALPH_OUTPUT]\n{"results": [{"task_id": "t-1", "passed": true}, {"task_id": "t-2", "passed": false, "reason": "test fails"}]}\n[/RALPH_OUTPUT]'
        result = reconcile_verify(mock_tix, output)
        assert len(result.tasks_accepted) == 1
        assert len(result.tasks_rejected) == 1
        mock_tix.task_reject.assert_called_once_with("t-2", "test fails")
        # reject_count should be incremented
        mock_tix.task_update.assert_called_once_with("t-2", {"reject_count": 1})

    def test_with_new_tasks(self, mock_tix):
        output = '[RALPH_OUTPUT]\n{"results": [], "new_tasks": [{"name": "Fix X", "notes": "...", "accept": "..."}]}\n[/RALPH_OUTPUT]'
        result = reconcile_verify(mock_tix, output)
        assert len(result.tasks_added) == 1

    def test_no_output(self, mock_tix):
        result = reconcile_verify(mock_tix, "no json here")
        assert not result.ok

    def test_with_issues(self, mock_tix):
        """VERIFY can surface cross-cutting issues for INVESTIGATE."""
        output = '[RALPH_OUTPUT]\n{"results": [{"task_id": "t-1", "passed": false, "reason": "libfoo missing"}], "issues": [{"desc": "libfoo.so not installed in test env", "priority": "high"}]}\n[/RALPH_OUTPUT]'
        result = reconcile_verify(mock_tix, output)
        assert len(result.tasks_rejected) == 1
        assert len(result.issues_added) == 1
        mock_tix.issue_add.assert_called_once_with("libfoo.so not installed in test env")

    def test_issues_empty_list(self, mock_tix):
        """Empty issues list is fine — no issue_add calls."""
        output = '[RALPH_OUTPUT]\n{"results": [{"task_id": "t-1", "passed": true}], "issues": []}\n[/RALPH_OUTPUT]'
        result = reconcile_verify(mock_tix, output)
        assert result.ok
        assert len(result.issues_added) == 0
        mock_tix.issue_add.assert_not_called()

    def test_issues_omitted(self, mock_tix):
        """Missing issues key is fine — backwards compatible."""
        output = '[RALPH_OUTPUT]\n{"results": [{"task_id": "t-1", "passed": true}]}\n[/RALPH_OUTPUT]'
        result = reconcile_verify(mock_tix, output)
        assert result.ok
        assert len(result.issues_added) == 0
        mock_tix.issue_add.assert_not_called()


# =============================================================================
# reconcile_investigate
# =============================================================================


class TestReconcileInvestigate:
    def test_creates_tasks_and_clears_batch(self, mock_tix):
        """With batch_issue_ids, only those issues are cleared."""
        mock_tix.issue_done_ids.return_value = {"count": 2}
        output = '[RALPH_OUTPUT]\n{"tasks": [{"name": "Fix bug", "notes": "...", "accept": "..."}], "out_of_scope": ["i-1"]}\n[/RALPH_OUTPUT]'
        result = reconcile_investigate(mock_tix, output, batch_issue_ids=["i-1", "i-2"])
        assert result.ok
        assert len(result.tasks_added) == 1
        assert result.issues_cleared == 2
        mock_tix.issue_done_ids.assert_called_once_with(["i-1", "i-2"])
        mock_tix.issue_done_all.assert_not_called()

    def test_clears_all_without_batch(self, mock_tix):
        """Without batch_issue_ids, falls back to clearing all (legacy)."""
        output = '[RALPH_OUTPUT]\n{"tasks": [{"name": "Fix bug", "notes": "...", "accept": "..."}], "out_of_scope": ["i-1"]}\n[/RALPH_OUTPUT]'
        result = reconcile_investigate(mock_tix, output)
        assert result.ok
        assert len(result.tasks_added) == 1
        mock_tix.issue_done_all.assert_called_once()

    def test_empty_tasks(self, mock_tix):
        """All out of scope — no tasks created but issues still cleared."""
        mock_tix.issue_done_ids.return_value = {"count": 2}
        output = '[RALPH_OUTPUT]\n{"tasks": [], "out_of_scope": ["i-1", "i-2"]}\n[/RALPH_OUTPUT]'
        result = reconcile_investigate(mock_tix, output, batch_issue_ids=["i-1", "i-2"])
        assert result.ok
        assert result.issues_cleared == 2
        mock_tix.issue_done_ids.assert_called_once_with(["i-1", "i-2"])


# =============================================================================
# reconcile_decompose
# =============================================================================


class TestReconcileDecompose:
    def test_creates_subtasks_and_deletes(self, mock_tix):
        output = '[RALPH_OUTPUT]\n{"subtasks": [{"name": "Part 1", "notes": "...", "accept": "..."}, {"name": "Part 2", "notes": "...", "accept": "..."}]}\n[/RALPH_OUTPUT]'
        result = reconcile_decompose(mock_tix, output, "t-original")
        assert result.ok
        assert len(result.tasks_added) == 2
        assert "t-original" in result.tasks_deleted
        # Check parent was set
        calls = mock_tix.task_add.call_args_list
        for call in calls:
            assert call[0][0]["parent"] == "t-original"

    def test_no_subtasks(self, mock_tix):
        output = '[RALPH_OUTPUT]\n{"subtasks": []}\n[/RALPH_OUTPUT]'
        result = reconcile_decompose(mock_tix, output, "t-original")
        assert not result.ok
        mock_tix.task_delete.assert_not_called()

    def test_increments_decompose_depth(self, mock_tix):
        """Subtasks get parent_depth + 1 on their decompose_depth."""
        output = '[RALPH_OUTPUT]\n{"subtasks": [{"name": "Sub 1", "notes": "n", "accept": "a"}]}\n[/RALPH_OUTPUT]'
        result = reconcile_decompose(mock_tix, output, "t-parent", parent_depth=2)
        assert result.ok
        call_data = mock_tix.task_add.call_args[0][0]
        assert call_data["decompose_depth"] == 3
        assert call_data["parent"] == "t-parent"

    def test_depth_defaults_to_one_when_no_parent_depth(self, mock_tix):
        """When parent_depth is not specified, subtasks get depth 1."""
        output = '[RALPH_OUTPUT]\n{"subtasks": [{"name": "Sub task", "notes": "notes", "accept": "a"}]}\n[/RALPH_OUTPUT]'
        result = reconcile_decompose(mock_tix, output, "t-root")
        assert result.ok
        call_data = mock_tix.task_add.call_args[0][0]
        assert call_data["decompose_depth"] == 1


# =============================================================================
# reconcile_plan
# =============================================================================


class TestReconcilePlan:
    def test_creates_tasks(self, mock_tix):
        output = '[RALPH_OUTPUT]\n{"tasks": [{"name": "Task 1", "notes": "...", "accept": "..."}, {"name": "Task 2", "notes": "...", "accept": "..."}]}\n[/RALPH_OUTPUT]'
        result = reconcile_plan(mock_tix, output, "my-spec.md")
        assert result.ok
        assert len(result.tasks_added) == 2
        # Check spec was set via batch add
        batch_call = mock_tix.task_batch_add.call_args[0][0]
        for task_data in batch_call:
            assert task_data["spec"] == "my-spec.md"


# =============================================================================
# ReconcileResult
# =============================================================================


class TestReconcileResult:
    def test_summary_empty(self):
        r = ReconcileResult()
        assert r.summary == "no changes"

    def test_summary_with_actions(self):
        r = ReconcileResult(
            tasks_added=["t-1", "t-2"],
            tasks_accepted=["t-3"],
            errors=["something failed"],
        )
        assert "2 tasks added" in r.summary
        assert "1 accepted" in r.summary
        assert "1 errors" in r.summary
