"""Tests for ralph.reconcile module."""

import json
import pytest
from unittest.mock import MagicMock, patch

from ralph.reconcile import (
    _attach_stage_telemetry,
    _reject_counts,
    extract_structured_output,
    reconcile_build,
    reconcile_verify,
    reconcile_investigate,
    reconcile_decompose,
    reconcile_plan,
    ReconcileResult,
)
from ralph.tix import TixError


@pytest.fixture(autouse=True)
def _reset_reject_counts():
    """Reset module-level _reject_counts between tests."""
    _reject_counts.clear()
    yield
    _reject_counts.clear()


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
        mock_tix.task_update.return_value = {"id": "t-2", "status": "updated"}
        output = '[RALPH_OUTPUT]\n{"results": [{"task_id": "t-1", "passed": true}, {"task_id": "t-2", "passed": false, "reason": "test fails"}]}\n[/RALPH_OUTPUT]'
        result = reconcile_verify(mock_tix, output)
        assert len(result.tasks_accepted) == 1
        assert len(result.tasks_rejected) == 1
        mock_tix.task_reject.assert_called_once_with("t-2", "test fails")
        # retries should be incremented via meta sub-object for ticket_meta persistence
        mock_tix.task_update.assert_called_once_with("t-2", {"meta": {"retries": 1}})

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
        # Tasks must pass strict validation: notes >= 50 chars with file refs
        # and line numbers, accept must be a targeted shell command
        task1 = {
            "name": "Extract config module",
            "notes": "Source: src/config.py lines 1-50. Extract GlobalConfig class to separate module.",
            "accept": "pytest tests/unit/test_config.py passes"
        }
        task2 = {
            "name": "Add validation functions",
            "notes": "Source: src/validation.py lines 10-80. Create validate_task and validate_issue functions.",
            "accept": "test -f src/validation.py && python3 -c 'from validation import validate_task' exits 0"
        }
        import json
        output = f'[RALPH_OUTPUT]\n{json.dumps({"tasks": [task1, task2]})}\n[/RALPH_OUTPUT]'
        result = reconcile_plan(mock_tix, output, "my-spec.md")
        assert result.ok
        assert len(result.tasks_added) == 2
        # Check spec was set via batch add
        batch_call = mock_tix.task_batch_add.call_args[0][0]
        for task_data in batch_call:
            assert task_data["spec"] == "my-spec.md"

    def test_rejects_vague_tasks(self, mock_tix):
        """Tasks with vague acceptance criteria are rejected by strict validation."""
        task = {
            "name": "Fix the bug",
            "notes": "...",
            "accept": "make test"
        }
        import json
        output = f'[RALPH_OUTPUT]\n{json.dumps({"tasks": [task]})}\n[/RALPH_OUTPUT]'
        result = reconcile_plan(mock_tix, output, "my-spec.md")
        # No tasks should be added
        assert len(result.tasks_added) == 0
        # Should have validation errors
        assert any("rejected by validation" in e for e in result.errors)


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


# =============================================================================
# run_id telemetry tracking
# =============================================================================


class TestRunIdTelemetry:
    """Verify run_id flows from stage_metrics into tix task meta."""

    def test_build_attaches_run_id(self, mock_tix):
        """reconcile_build writes run_id to task meta when present."""
        output = '[RALPH_OUTPUT]\n{"verdict": "done"}\n[/RALPH_OUTPUT]'
        metrics = {
            "cost": 0.5, "tokens_in": 1000, "tokens_out": 200,
            "iterations": 1, "model": "opus", "run_id": "20260208_120000_abc123",
        }
        result = reconcile_build(mock_tix, output, "t-abc", stage_metrics=metrics)
        assert result.ok
        # task_update should include run_id in meta
        mock_tix.task_update.assert_called_once()
        call_args = mock_tix.task_update.call_args[0]
        assert call_args[0] == "t-abc"
        meta = call_args[1]["meta"]
        assert meta["run_id"] == "20260208_120000_abc123"

    def test_build_without_run_id(self, mock_tix):
        """reconcile_build works fine when run_id is absent."""
        output = '[RALPH_OUTPUT]\n{"verdict": "done"}\n[/RALPH_OUTPUT]'
        metrics = {
            "cost": 0.5, "tokens_in": 1000, "tokens_out": 200,
            "iterations": 1, "model": "opus",
        }
        result = reconcile_build(mock_tix, output, "t-abc", stage_metrics=metrics)
        assert result.ok
        call_args = mock_tix.task_update.call_args[0]
        meta = call_args[1]["meta"]
        assert "run_id" not in meta

    def test_attach_stage_telemetry_includes_run_id(self, mock_tix):
        """_attach_stage_telemetry writes run_id to each task's meta."""
        metrics = {
            "cost": 1.0, "tokens_in": 2000, "tokens_out": 500,
            "iterations": 2, "model": "sonnet",
            "run_id": "20260208_130000_def456",
        }
        _attach_stage_telemetry(mock_tix, ["t-1", "t-2"], metrics, "verify")
        assert mock_tix.task_update.call_count == 2
        for call in mock_tix.task_update.call_args_list:
            meta = call[0][1]["meta"]
            assert meta["run_id"] == "20260208_130000_def456"

    def test_attach_stage_telemetry_without_run_id(self, mock_tix):
        """_attach_stage_telemetry omits run_id when not in metrics."""
        metrics = {
            "cost": 1.0, "tokens_in": 2000, "tokens_out": 500,
            "iterations": 2, "model": "sonnet",
        }
        _attach_stage_telemetry(mock_tix, ["t-1"], metrics, "build")
        meta = mock_tix.task_update.call_args[0][1]["meta"]
        assert "run_id" not in meta

    def test_attach_stage_telemetry_empty_task_list(self, mock_tix):
        """_attach_stage_telemetry is a no-op with empty task list."""
        metrics = {"cost": 1.0, "run_id": "20260208_140000_ghi789"}
        _attach_stage_telemetry(mock_tix, [], metrics, "verify")
        mock_tix.task_update.assert_not_called()

    def test_verify_attaches_run_id_to_verified_tasks(self, mock_tix):
        """reconcile_verify passes run_id through to verified tasks."""
        mock_tix.task_update.return_value = {}
        output = '[RALPH_OUTPUT]\n{"results": [{"task_id": "t-1", "passed": true}]}\n[/RALPH_OUTPUT]'
        metrics = {
            "cost": 0.3, "tokens_in": 500, "tokens_out": 100,
            "iterations": 1, "model": "opus",
            "run_id": "20260208_150000_jkl012",
        }
        result = reconcile_verify(mock_tix, output, stage_metrics=metrics)
        assert result.ok
        # Find the _attach_stage_telemetry call (not the retries call)
        update_calls = mock_tix.task_update.call_args_list
        telemetry_call = [c for c in update_calls if "run_id" in c[0][1].get("meta", {})]
        assert len(telemetry_call) == 1
        assert telemetry_call[0][0][1]["meta"]["run_id"] == "20260208_150000_jkl012"


# =============================================================================
# _reject_counts accumulation
# =============================================================================


class TestRejectCounts:
    """Verify _reject_counts module-level dict accumulates correctly."""

    def test_single_rejection_sets_retries_to_one(self, mock_tix):
        """First rejection of a task writes retries=1 to meta."""
        mock_tix.task_update.return_value = {}
        output = '[RALPH_OUTPUT]\n{"results": [{"task_id": "t-1", "passed": false, "reason": "test fails"}]}\n[/RALPH_OUTPUT]'
        reconcile_verify(mock_tix, output)
        # _reject_counts should have t-1 -> 1
        assert _reject_counts.get("t-1") == 1
        # task_update for retries should write 1
        retries_calls = [
            c for c in mock_tix.task_update.call_args_list
            if c[0][1].get("meta", {}).get("retries") is not None
        ]
        assert len(retries_calls) == 1
        assert retries_calls[0][0][1]["meta"]["retries"] == 1

    def test_double_rejection_increments_retries(self, mock_tix):
        """Rejecting the same task twice writes retries=2 on second call."""
        mock_tix.task_update.return_value = {}
        output = '[RALPH_OUTPUT]\n{"results": [{"task_id": "t-1", "passed": false, "reason": "still fails"}]}\n[/RALPH_OUTPUT]'
        reconcile_verify(mock_tix, output)
        reconcile_verify(mock_tix, output)
        assert _reject_counts["t-1"] == 2
        # Find the second retries call for t-1
        retries_calls = [
            c for c in mock_tix.task_update.call_args_list
            if c[0][0] == "t-1" and c[0][1].get("meta", {}).get("retries") is not None
        ]
        assert retries_calls[-1][0][1]["meta"]["retries"] == 2

    def test_different_tasks_track_independently(self, mock_tix):
        """Different task IDs have independent reject counters."""
        mock_tix.task_update.return_value = {}
        output_a = '[RALPH_OUTPUT]\n{"results": [{"task_id": "t-a", "passed": false, "reason": "fail"}]}\n[/RALPH_OUTPUT]'
        output_b = '[RALPH_OUTPUT]\n{"results": [{"task_id": "t-b", "passed": false, "reason": "fail"}]}\n[/RALPH_OUTPUT]'
        reconcile_verify(mock_tix, output_a)
        reconcile_verify(mock_tix, output_a)
        reconcile_verify(mock_tix, output_b)
        assert _reject_counts["t-a"] == 2
        assert _reject_counts["t-b"] == 1

    def test_reset_fixture_clears_counts(self, mock_tix):
        """Verify the autouse fixture resets _reject_counts per test."""
        # _reject_counts should be empty at start of each test
        assert len(_reject_counts) == 0


# =============================================================================
# tokens_cached in telemetry
# =============================================================================


class TestTokensCachedTelemetry:
    """Verify tokens_cached flows through telemetry attachment."""

    def test_attach_stage_telemetry_includes_tokens_cached(self, mock_tix):
        """_attach_stage_telemetry splits tokens_cached across tasks."""
        metrics = {
            "cost": 1.0, "tokens_in": 2000, "tokens_cached": 800,
            "tokens_out": 500, "iterations": 2, "model": "opus",
        }
        _attach_stage_telemetry(mock_tix, ["t-1", "t-2"], metrics, "verify")
        assert mock_tix.task_update.call_count == 2
        for call in mock_tix.task_update.call_args_list:
            meta = call[0][1]["meta"]
            assert meta["tokens_cached"] == 400  # 800 // 2

    def test_attach_stage_telemetry_omits_zero_tokens_cached(self, mock_tix):
        """_attach_stage_telemetry omits tokens_cached when 0."""
        metrics = {
            "cost": 1.0, "tokens_in": 2000, "tokens_cached": 0,
            "tokens_out": 500, "iterations": 2,
        }
        _attach_stage_telemetry(mock_tix, ["t-1"], metrics, "build")
        meta = mock_tix.task_update.call_args[0][1]["meta"]
        assert "tokens_cached" not in meta

    def test_build_inline_includes_tokens_cached(self, mock_tix):
        """reconcile_build inline telemetry includes tokens_cached."""
        output = '[RALPH_OUTPUT]\n{"verdict": "done"}\n[/RALPH_OUTPUT]'
        metrics = {
            "cost": 0.5, "tokens_in": 1000, "tokens_cached": 300,
            "tokens_out": 200, "iterations": 1, "model": "opus",
        }
        result = reconcile_build(mock_tix, output, "t-abc", stage_metrics=metrics)
        assert result.ok
        call_args = mock_tix.task_update.call_args[0]
        meta = call_args[1]["meta"]
        assert meta["tokens_cached"] == 300

    def test_build_inline_omits_missing_tokens_cached(self, mock_tix):
        """reconcile_build inline telemetry omits tokens_cached when absent."""
        output = '[RALPH_OUTPUT]\n{"verdict": "done"}\n[/RALPH_OUTPUT]'
        metrics = {
            "cost": 0.5, "tokens_in": 1000, "tokens_out": 200,
            "iterations": 1, "model": "opus",
        }
        result = reconcile_build(mock_tix, output, "t-abc", stage_metrics=metrics)
        assert result.ok
        call_args = mock_tix.task_update.call_args[0]
        meta = call_args[1]["meta"]
        assert "tokens_cached" not in meta
