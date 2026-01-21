"""Unit tests for ralph.state module."""

import json
from pathlib import Path
from typing import Generator

import pytest

from ralph.models import Issue, RalphPlanConfig, Task, Tombstone
from ralph.state import RalphState, load_state, save_state, validate_state


class TestRalphStateProperties:
    """Tests for RalphState computed properties."""

    def test_pending_returns_only_pending_tasks(self) -> None:
        """Test that pending property returns only status='p' tasks."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Pending", spec="spec.md", status="p"),
            Task(id="t-2", name="Done", spec="spec.md", status="d"),
            Task(id="t-3", name="Accepted", spec="spec.md", status="a"),
            Task(id="t-4", name="Also pending", spec="spec.md", status="p"),
        ]
        pending = state.pending
        assert len(pending) == 2
        assert all(t.status == "p" for t in pending)
        assert {t.id for t in pending} == {"t-1", "t-4"}

    def test_pending_returns_empty_list_when_no_pending(self) -> None:
        """Test pending returns empty list when no pending tasks."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Done", spec="spec.md", status="d"),
        ]
        assert state.pending == []

    def test_done_returns_only_done_tasks(self) -> None:
        """Test that done property returns only status='d' tasks."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Pending", spec="spec.md", status="p"),
            Task(id="t-2", name="Done", spec="spec.md", status="d"),
            Task(id="t-3", name="Also done", spec="spec.md", status="d"),
        ]
        done = state.done
        assert len(done) == 2
        assert all(t.status == "d" for t in done)
        assert {t.id for t in done} == {"t-2", "t-3"}

    def test_done_ids_returns_set_of_ids(self) -> None:
        """Test done_ids returns set of done task IDs."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Pending", spec="spec.md", status="p"),
            Task(id="t-2", name="Done", spec="spec.md", status="d"),
            Task(id="t-3", name="Also done", spec="spec.md", status="d"),
        ]
        assert state.done_ids == {"t-2", "t-3"}

    def test_accepted_returns_only_accepted_tasks(self) -> None:
        """Test that accepted property returns only status='a' tasks."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Pending", spec="spec.md", status="p"),
            Task(id="t-2", name="Accepted", spec="spec.md", status="a"),
            Task(id="t-3", name="Done", spec="spec.md", status="d"),
        ]
        accepted = state.accepted
        assert len(accepted) == 1
        assert accepted[0].id == "t-2"

    def test_accepted_ids_returns_set_of_ids(self) -> None:
        """Test accepted_ids returns set of accepted task IDs."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Accepted", spec="spec.md", status="a"),
            Task(id="t-2", name="Also accepted", spec="spec.md", status="a"),
        ]
        assert state.accepted_ids == {"t-1", "t-2"}

    def test_task_ids_returns_all_task_ids(self) -> None:
        """Test task_ids returns all task IDs regardless of status."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Pending", spec="spec.md", status="p"),
            Task(id="t-2", name="Done", spec="spec.md", status="d"),
            Task(id="t-3", name="Accepted", spec="spec.md", status="a"),
        ]
        assert state.task_ids == {"t-1", "t-2", "t-3"}


class TestRalphStateLookups:
    """Tests for RalphState lookup methods."""

    def test_get_task_by_id_returns_correct_task(self) -> None:
        """Test get_task_by_id returns the correct task."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="First", spec="spec.md"),
            Task(id="t-2", name="Second", spec="spec.md"),
        ]
        task = state.get_task_by_id("t-2")
        assert task is not None
        assert task.id == "t-2"
        assert task.name == "Second"

    def test_get_task_by_id_returns_none_for_nonexistent(self) -> None:
        """Test get_task_by_id returns None for non-existent ID."""
        state = RalphState()
        state.tasks = [Task(id="t-1", name="First", spec="spec.md")]
        assert state.get_task_by_id("t-nonexistent") is None

    def test_get_issue_by_id_returns_correct_issue(self) -> None:
        """Test get_issue_by_id returns the correct issue."""
        state = RalphState()
        state.issues = [
            Issue(id="i-1", desc="First issue", spec="spec.md"),
            Issue(id="i-2", desc="Second issue", spec="spec.md"),
        ]
        issue = state.get_issue_by_id("i-2")
        assert issue is not None
        assert issue.id == "i-2"
        assert issue.desc == "Second issue"

    def test_get_issue_by_id_returns_none_for_nonexistent(self) -> None:
        """Test get_issue_by_id returns None for non-existent ID."""
        state = RalphState()
        state.issues = [Issue(id="i-1", desc="First", spec="spec.md")]
        assert state.get_issue_by_id("i-nonexistent") is None


class TestRalphStateTaskSorting:
    """Tests for task sorting and selection logic."""

    def test_get_sorted_pending_sorts_by_priority(self) -> None:
        """Test get_sorted_pending sorts by priority (high > medium > low)."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Low", spec="spec.md", status="p", priority="low"),
            Task(id="t-2", name="High", spec="spec.md", status="p", priority="high"),
            Task(
                id="t-3", name="Medium", spec="spec.md", status="p", priority="medium"
            ),
        ]
        sorted_tasks = state.get_sorted_pending()
        assert len(sorted_tasks) == 3
        assert sorted_tasks[0].priority == "high"
        assert sorted_tasks[1].priority == "medium"
        assert sorted_tasks[2].priority == "low"

    def test_get_sorted_pending_uses_id_as_tiebreaker(self) -> None:
        """Test get_sorted_pending uses task ID as tiebreaker."""
        state = RalphState()
        state.tasks = [
            Task(id="t-zzz", name="Last", spec="spec.md", status="p", priority="high"),
            Task(id="t-aaa", name="First", spec="spec.md", status="p", priority="high"),
            Task(
                id="t-mmm", name="Middle", spec="spec.md", status="p", priority="high"
            ),
        ]
        sorted_tasks = state.get_sorted_pending()
        assert [t.id for t in sorted_tasks] == ["t-aaa", "t-mmm", "t-zzz"]

    def test_get_sorted_pending_excludes_unsatisfied_deps(self) -> None:
        """Test get_sorted_pending excludes tasks with unsatisfied deps."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="No deps", spec="spec.md", status="p"),
            Task(id="t-2", name="Has dep", spec="spec.md", status="p", deps=["t-3"]),
            Task(id="t-3", name="Pending dep", spec="spec.md", status="p"),
        ]
        sorted_tasks = state.get_sorted_pending()
        task_ids = {t.id for t in sorted_tasks}
        assert "t-1" in task_ids
        assert "t-3" in task_ids
        assert "t-2" not in task_ids

    def test_get_sorted_pending_includes_tasks_with_satisfied_deps(self) -> None:
        """Test get_sorted_pending includes tasks with all deps done."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Done dep", spec="spec.md", status="d"),
            Task(id="t-2", name="Has dep", spec="spec.md", status="p", deps=["t-1"]),
        ]
        sorted_tasks = state.get_sorted_pending()
        assert len(sorted_tasks) == 1
        assert sorted_tasks[0].id == "t-2"

    def test_get_sorted_pending_includes_tasks_with_no_deps(self) -> None:
        """Test get_sorted_pending includes tasks without deps."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="No deps", spec="spec.md", status="p"),
        ]
        sorted_tasks = state.get_sorted_pending()
        assert len(sorted_tasks) == 1
        assert sorted_tasks[0].id == "t-1"

    def test_get_sorted_pending_returns_empty_when_no_pending(self) -> None:
        """Test get_sorted_pending returns empty list when no pending tasks."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Done", spec="spec.md", status="d"),
        ]
        assert state.get_sorted_pending() == []

    def test_get_sorted_pending_none_priority_sorts_last(self) -> None:
        """Test None priority sorts after low priority."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="None", spec="spec.md", status="p", priority=None),
            Task(id="t-2", name="Low", spec="spec.md", status="p", priority="low"),
        ]
        sorted_tasks = state.get_sorted_pending()
        assert sorted_tasks[0].priority == "low"
        assert sorted_tasks[1].priority is None

    def test_get_next_task_returns_highest_priority(self) -> None:
        """Test get_next_task returns highest priority runnable task."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Low", spec="spec.md", status="p", priority="low"),
            Task(id="t-2", name="High", spec="spec.md", status="p", priority="high"),
        ]
        next_task = state.get_next_task()
        assert next_task is not None
        assert next_task.id == "t-2"

    def test_get_next_task_returns_none_when_no_runnable(self) -> None:
        """Test get_next_task returns None when no runnable tasks."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Has dep", spec="spec.md", status="p", deps=["t-2"]),
        ]
        assert state.get_next_task() is None

    def test_get_task_needing_decompose_returns_task(self) -> None:
        """Test get_task_needing_decompose returns task with needs_decompose=True."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Normal", spec="spec.md", status="p"),
            Task(
                id="t-2",
                name="Needs decompose",
                spec="spec.md",
                status="p",
                needs_decompose=True,
            ),
        ]
        task = state.get_task_needing_decompose()
        assert task is not None
        assert task.id == "t-2"

    def test_get_task_needing_decompose_returns_none(self) -> None:
        """Test get_task_needing_decompose returns None when no task needs decomposition."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Normal", spec="spec.md", status="p"),
        ]
        assert state.get_task_needing_decompose() is None


class TestRalphStateStage:
    """Tests for stage detection logic."""

    def test_get_stage_returns_plan_when_no_tasks_or_issues(self) -> None:
        """Test get_stage returns PLAN when no tasks and no issues."""
        state = RalphState()
        assert state.get_stage() == "PLAN"

    def test_get_stage_returns_investigate_when_issues_exist(self) -> None:
        """Test get_stage returns INVESTIGATE when issues exist."""
        state = RalphState()
        state.issues = [Issue(id="i-1", desc="Issue", spec="spec.md")]
        assert state.get_stage() == "INVESTIGATE"

    def test_get_stage_returns_decompose_when_task_needs_decomposition(self) -> None:
        """Test get_stage returns DECOMPOSE when task needs decomposition."""
        state = RalphState()
        state.tasks = [
            Task(
                id="t-1",
                name="Needs decompose",
                spec="spec.md",
                status="p",
                needs_decompose=True,
            ),
        ]
        assert state.get_stage() == "DECOMPOSE"

    def test_get_stage_returns_build_for_pending_task(self) -> None:
        """Test get_stage returns BUILD for runnable pending task."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Pending", spec="spec.md", status="p"),
        ]
        assert state.get_stage() == "BUILD"

    def test_get_stage_returns_complete_when_all_done(self) -> None:
        """Test get_stage returns COMPLETE when all tasks are done."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Done", spec="spec.md", status="d"),
        ]
        assert state.get_stage() == "COMPLETE"

    def test_get_stage_returns_build_when_all_accepted(self) -> None:
        """Test get_stage returns BUILD when all tasks are accepted (no more pending work)."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Accepted", spec="spec.md", status="a"),
        ]
        assert state.get_stage() == "BUILD"


class TestRalphStateGetNext:
    """Tests for get_next() action selection."""

    def test_get_next_returns_plan_action(self) -> None:
        """Test get_next returns PLAN action with reason."""
        state = RalphState()
        next_action = state.get_next()
        assert next_action["action"] == "PLAN"
        assert "reason" in next_action

    def test_get_next_returns_investigate_action_with_issue(self) -> None:
        """Test get_next returns INVESTIGATE action with issue dict."""
        state = RalphState()
        state.issues = [Issue(id="i-1", desc="Test issue", spec="spec.md")]
        next_action = state.get_next()
        assert next_action["action"] == "INVESTIGATE"
        assert "issue" in next_action
        assert next_action["issue"]["id"] == "i-1"

    def test_get_next_returns_decompose_action_with_task(self) -> None:
        """Test get_next returns DECOMPOSE action with task dict."""
        state = RalphState()
        state.tasks = [
            Task(
                id="t-1",
                name="Decompose",
                spec="spec.md",
                status="p",
                needs_decompose=True,
            ),
        ]
        next_action = state.get_next()
        assert next_action["action"] == "DECOMPOSE"
        assert "task" in next_action
        assert next_action["task"]["id"] == "t-1"

    def test_get_next_returns_build_action_with_task(self) -> None:
        """Test get_next returns BUILD action with task dict."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Build", spec="spec.md", status="p"),
        ]
        next_action = state.get_next()
        assert next_action["action"] == "BUILD"
        assert "task" in next_action
        assert next_action["task"]["id"] == "t-1"

    def test_get_next_returns_complete_action_when_all_done(self) -> None:
        """Test get_next returns COMPLETE action when all tasks are done."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Done", spec="spec.md", status="d"),
        ]
        next_action = state.get_next()
        assert next_action["action"] == "COMPLETE"
        assert "reason" in next_action

    def test_get_next_returns_build_when_all_accepted(self) -> None:
        """Test get_next returns BUILD when all tasks are accepted (no pending work)."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Accepted", spec="spec.md", status="a"),
        ]
        next_action = state.get_next()
        assert next_action["action"] == "BUILD"


class TestRalphStateSerialization:
    """Tests for to_dict() serialization."""

    def test_to_dict_includes_all_fields(self) -> None:
        """Test to_dict includes all expected fields."""
        state = RalphState(spec="test.md")
        state.tasks = [Task(id="t-1", name="Task", spec="test.md", status="p")]
        state.issues = [Issue(id="i-1", desc="Issue", spec="test.md")]
        d = state.to_dict()
        assert "spec" in d
        assert "tasks" in d
        assert "issues" in d
        assert "stage" in d
        assert "next" in d

    def test_to_dict_separates_pending_done_tasks(self) -> None:
        """Test to_dict separates pending and done tasks."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Pending", spec="spec.md", status="p"),
            Task(id="t-2", name="Done", spec="spec.md", status="d"),
        ]
        d = state.to_dict()
        assert "pending" in d["tasks"]
        assert "done" in d["tasks"]
        assert len(d["tasks"]["pending"]) == 1
        assert len(d["tasks"]["done"]) == 1

    def test_to_dict_includes_computed_stage_and_next(self) -> None:
        """Test to_dict includes computed stage and next."""
        state = RalphState()
        d = state.to_dict()
        assert d["stage"] == "PLAN"
        assert d["next"]["action"] == "PLAN"


class TestRalphStateMutation:
    """Tests for add/remove methods."""

    def test_add_task_appends_to_list(self) -> None:
        """Test add_task appends task to tasks list."""
        state = RalphState()
        task = Task(id="t-1", name="New task", spec="spec.md")
        state.add_task(task)
        assert len(state.tasks) == 1
        assert state.tasks[0].id == "t-1"

    def test_add_issue_appends_to_list(self) -> None:
        """Test add_issue appends issue to issues list."""
        state = RalphState()
        issue = Issue(id="i-1", desc="New issue", spec="spec.md")
        state.add_issue(issue)
        assert len(state.issues) == 1
        assert state.issues[0].id == "i-1"

    def test_add_tombstone_appends_to_list(self) -> None:
        """Test add_tombstone appends tombstone to tombstones list."""
        state = RalphState()
        tombstone = Tombstone(id="t-1", done_at="commit", reason="reason")
        state.add_tombstone(tombstone)
        assert len(state.tombstones) == 1
        assert state.tombstones[0].id == "t-1"

    def test_remove_issue_removes_by_id_returns_true(self) -> None:
        """Test remove_issue removes issue by ID and returns True."""
        state = RalphState()
        state.issues = [
            Issue(id="i-1", desc="First", spec="spec.md"),
            Issue(id="i-2", desc="Second", spec="spec.md"),
        ]
        result = state.remove_issue("i-1")
        assert result is True
        assert len(state.issues) == 1
        assert state.issues[0].id == "i-2"

    def test_remove_issue_returns_false_for_nonexistent(self) -> None:
        """Test remove_issue returns False for non-existent ID."""
        state = RalphState()
        state.issues = [Issue(id="i-1", desc="First", spec="spec.md")]
        result = state.remove_issue("i-nonexistent")
        assert result is False
        assert len(state.issues) == 1


class TestLoadState:
    """Tests for load_state() function."""

    def test_load_state_returns_empty_when_file_not_exists(self, temp_dir: str) -> None:
        """Test load_state returns empty state when file doesn't exist."""
        path = Path(temp_dir) / "nonexistent.jsonl"
        state = load_state(path)
        assert len(state.tasks) == 0
        assert len(state.issues) == 0
        assert state.spec is None

    def test_load_state_handles_empty_file(self, temp_dir: str) -> None:
        """Test load_state handles empty file."""
        path = Path(temp_dir) / "empty.jsonl"
        path.write_text("")
        state = load_state(path)
        assert len(state.tasks) == 0

    def test_load_state_handles_file_with_only_empty_lines(self, temp_dir: str) -> None:
        """Test load_state handles file with only empty lines."""
        path = Path(temp_dir) / "empty_lines.jsonl"
        path.write_text("\n\n\n")
        state = load_state(path)
        assert len(state.tasks) == 0

    def test_load_state_parses_spec_record(self, temp_dir: str) -> None:
        """Test load_state parses spec record."""
        path = Path(temp_dir) / "plan.jsonl"
        path.write_text('{"t": "spec", "spec": "test-spec.md"}\n')
        state = load_state(path)
        assert state.spec == "test-spec.md"

    def test_load_state_parses_config_record(self, temp_dir: str) -> None:
        """Test load_state parses config record."""
        path = Path(temp_dir) / "plan.jsonl"
        path.write_text('{"t": "config", "timeout_ms": 500000, "max_iterations": 15}\n')
        state = load_state(path)
        assert state.config is not None
        assert state.config.timeout_ms == 500000
        assert state.config.max_iterations == 15

    def test_load_state_parses_task_records(self, temp_dir: str) -> None:
        """Test load_state parses task records."""
        path = Path(temp_dir) / "plan.jsonl"
        path.write_text(
            '{"t": "task", "id": "t-1", "name": "Task 1", "spec": "spec.md", "s": "p"}\n'
        )
        state = load_state(path)
        assert len(state.tasks) == 1
        assert state.tasks[0].id == "t-1"
        assert state.tasks[0].name == "Task 1"

    def test_load_state_parses_issue_records(self, temp_dir: str) -> None:
        """Test load_state parses issue records."""
        path = Path(temp_dir) / "plan.jsonl"
        path.write_text(
            '{"t": "issue", "id": "i-1", "desc": "Issue 1", "spec": "spec.md"}\n'
        )
        state = load_state(path)
        assert len(state.issues) == 1
        assert state.issues[0].id == "i-1"
        assert state.issues[0].desc == "Issue 1"

    def test_load_state_handles_malformed_json(self, temp_dir: str) -> None:
        """Test load_state skips malformed JSON lines."""
        path = Path(temp_dir) / "plan.jsonl"
        content = """\
{"t": "task", "id": "t-1", "name": "Good task", "spec": "spec.md", "s": "p"}
{malformed json here
{"t": "task", "id": "t-2", "name": "Another good task", "spec": "spec.md", "s": "p"}
"""
        path.write_text(content)
        state = load_state(path)
        assert len(state.tasks) == 2

    def test_load_state_handles_lines_missing_t_field(self, temp_dir: str) -> None:
        """Test load_state handles lines missing 't' field."""
        path = Path(temp_dir) / "plan.jsonl"
        content = """\
{"t": "task", "id": "t-1", "name": "Good task", "spec": "spec.md", "s": "p"}
{"id": "t-2", "name": "Missing t field", "spec": "spec.md", "s": "p"}
"""
        path.write_text(content)
        state = load_state(path)
        assert len(state.tasks) == 1


class TestLoadStateAcceptReject:
    """Tests for accept/reject processing in load_state()."""

    def test_accept_updates_existing_task(self, temp_dir: str) -> None:
        """Test accept updates existing task to status='a'."""
        path = Path(temp_dir) / "plan.jsonl"
        content = """\
{"t": "task", "id": "t-1", "name": "Task", "spec": "spec.md", "s": "d", "done_at": "commit1"}
{"t": "accept", "id": "t-1", "done_at": "commit1", "reason": "Works"}
"""
        path.write_text(content)
        state = load_state(path)
        task = state.get_task_by_id("t-1")
        assert task is not None
        assert task.status == "a"

    def test_accept_creates_synthetic_task_for_compacted(self, temp_dir: str) -> None:
        """Test accept creates synthetic task for compacted task."""
        path = Path(temp_dir) / "plan.jsonl"
        content = """\
{"t": "accept", "id": "t-old", "done_at": "oldcommit", "reason": "", "name": "Old compacted task"}
"""
        path.write_text(content)
        state = load_state(path)
        task = state.get_task_by_id("t-old")
        assert task is not None
        assert task.status == "a"
        assert "t-old" in task.name or "Old compacted task" in task.name

    def test_reject_creates_tombstone(self, temp_dir: str) -> None:
        """Test reject creates tombstone."""
        path = Path(temp_dir) / "plan.jsonl"
        content = """\
{"t": "task", "id": "t-1", "name": "Task", "spec": "spec.md", "s": "p"}
{"t": "reject", "id": "t-1", "done_at": "commit1", "reason": "Did not work"}
"""
        path.write_text(content)
        state = load_state(path)
        assert len(state.tombstones) == 1
        assert state.tombstones[0].id == "t-1"
        assert state.tombstones[0].reason == "Did not work"

    def test_reject_resets_task_status_to_pending(self, temp_dir: str) -> None:
        """Test reject resets task status to 'p' and sets reject_reason."""
        path = Path(temp_dir) / "plan.jsonl"
        content = """\
{"t": "task", "id": "t-1", "name": "Task", "spec": "spec.md", "s": "p"}
{"t": "reject", "id": "t-1", "done_at": "commit1", "reason": "Did not work"}
"""
        path.write_text(content)
        state = load_state(path)
        task = state.get_task_by_id("t-1")
        assert task is not None
        assert task.status == "p"
        assert task.reject_reason == "Did not work"

    def test_reject_does_not_reset_done_tasks(self, temp_dir: str) -> None:
        """Test reject doesn't reset done tasks (status='d')."""
        path = Path(temp_dir) / "plan.jsonl"
        content = """\
{"t": "task", "id": "t-1", "name": "Task", "spec": "spec.md", "s": "d", "done_at": "commit1"}
{"t": "reject", "id": "t-1", "done_at": "oldcommit", "reason": "Old rejection"}
"""
        path.write_text(content)
        state = load_state(path)
        task = state.get_task_by_id("t-1")
        assert task is not None
        assert task.status == "d"

    def test_full_plan_jsonl(self, temp_dir: str, sample_plan_jsonl: str) -> None:
        """Test loading full plan.jsonl with all record types."""
        path = Path(temp_dir) / "plan.jsonl"
        path.write_text(sample_plan_jsonl)
        state = load_state(path)
        assert state.config is not None
        assert len(state.tasks) >= 2
        assert len(state.issues) == 1


class TestValidateState:
    """Tests for validate_state() function."""

    def test_validate_state_valid_no_deps(self) -> None:
        """Test valid state with no deps returns no errors."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Task", spec="spec.md", status="p"),
        ]
        result = validate_state(state)
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_validate_state_dangling_dependency_error(self) -> None:
        """Test dangling dependency returns error."""
        state = RalphState()
        state.tasks = [
            Task(
                id="t-1",
                name="Task",
                spec="spec.md",
                status="p",
                deps=["t-nonexistent"],
            ),
        ]
        result = validate_state(state)
        assert result["valid"] is False
        assert any("t-nonexistent" in e for e in result["errors"])

    def test_validate_state_dependency_on_done_task_valid(self) -> None:
        """Test dependency on done task is valid."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Done", spec="spec.md", status="d"),
            Task(id="t-2", name="Depends", spec="spec.md", status="p", deps=["t-1"]),
        ]
        result = validate_state(state)
        assert result["valid"] is True

    def test_validate_state_dependency_on_tombstone_valid(self) -> None:
        """Test dependency on tombstone is valid."""
        state = RalphState()
        state.tasks = [
            Task(id="t-2", name="Depends", spec="spec.md", status="p", deps=["t-1"]),
        ]
        state.tombstones = [
            Tombstone(id="t-1", done_at="commit", reason=""),
        ]
        result = validate_state(state)
        assert result["valid"] is True

    def test_validate_state_dangling_parent_warning(self) -> None:
        """Test dangling parent returns warning."""
        state = RalphState()
        state.tasks = [
            Task(
                id="t-1",
                name="Task",
                spec="spec.md",
                status="p",
                parent="t-nonexistent",
            ),
        ]
        result = validate_state(state)
        assert len(result["warnings"]) > 0
        assert any("parent" in w.lower() for w in result["warnings"])

    def test_validate_state_invalid_created_from_warning(self) -> None:
        """Test invalid created_from (not starting with 'i-') returns warning."""
        state = RalphState()
        state.tasks = [
            Task(
                id="t-1", name="Task", spec="spec.md", status="p", created_from="bad-id"
            ),
        ]
        result = validate_state(state)
        assert len(result["warnings"]) > 0
        assert any("created_from" in w.lower() for w in result["warnings"])

    def test_validate_state_valid_created_from(self) -> None:
        """Test valid created_from returns no warning."""
        state = RalphState()
        state.tasks = [
            Task(
                id="t-1",
                name="Task",
                spec="spec.md",
                status="p",
                created_from="i-issue1",
            ),
        ]
        result = validate_state(state)
        assert not any("created_from" in w.lower() for w in result.get("warnings", []))

    def test_validate_state_circular_dependency_direct(self) -> None:
        """Test direct cycle (A -> A) detected."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Self dep", spec="spec.md", status="p", deps=["t-1"]),
        ]
        result = validate_state(state)
        assert result["valid"] is False
        assert any(
            "circular" in e.lower() or "cycle" in e.lower() for e in result["errors"]
        )

    def test_validate_state_circular_dependency_indirect(self) -> None:
        """Test indirect cycle (A -> B -> A) detected."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="First", spec="spec.md", status="p", deps=["t-2"]),
            Task(id="t-2", name="Second", spec="spec.md", status="p", deps=["t-1"]),
        ]
        result = validate_state(state)
        assert result["valid"] is False
        assert any(
            "circular" in e.lower() or "cycle" in e.lower() for e in result["errors"]
        )

    def test_validate_state_custom_valid_ids(self) -> None:
        """Test custom valid_ids respected."""
        state = RalphState()
        state.tasks = [
            Task(
                id="t-1", name="Task", spec="spec.md", status="p", deps=["t-external"]
            ),
        ]
        result = validate_state(state, valid_ids={"t-1", "t-external"})
        assert result["valid"] is True


class TestSaveState:
    """Tests for save_state() function."""

    def test_save_state_creates_file(self, temp_dir: str) -> None:
        """Test save_state creates file."""
        path = Path(temp_dir) / "plan.jsonl"
        state = RalphState(spec="test.md")
        save_state(state, path)
        assert path.exists()

    def test_save_state_writes_config_first(self, temp_dir: str) -> None:
        """Test save_state writes config first (if present)."""
        path = Path(temp_dir) / "plan.jsonl"
        state = RalphState(spec="test.md", config=RalphPlanConfig())
        state.tasks = [Task(id="t-1", name="Task", spec="test.md")]
        save_state(state, path)
        content = path.read_text()
        lines = content.strip().split("\n")
        first_record = json.loads(lines[0])
        assert first_record["t"] == "config"

    def test_save_state_writes_spec_after_config(self, temp_dir: str) -> None:
        """Test save_state writes spec after config."""
        path = Path(temp_dir) / "plan.jsonl"
        state = RalphState(spec="test.md", config=RalphPlanConfig())
        save_state(state, path)
        content = path.read_text()
        lines = content.strip().split("\n")
        second_record = json.loads(lines[1])
        assert second_record["t"] == "spec"
        assert second_record["spec"] == "test.md"

    def test_save_state_writes_tasks(self, temp_dir: str) -> None:
        """Test save_state writes task records."""
        path = Path(temp_dir) / "plan.jsonl"
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Task 1", spec="spec.md"),
            Task(id="t-2", name="Task 2", spec="spec.md"),
        ]
        save_state(state, path)
        content = path.read_text()
        assert '"t": "task"' in content or '"t":"task"' in content
        assert "t-1" in content
        assert "t-2" in content

    def test_save_state_writes_issues(self, temp_dir: str) -> None:
        """Test save_state writes issue records."""
        path = Path(temp_dir) / "plan.jsonl"
        state = RalphState()
        state.issues = [Issue(id="i-1", desc="Issue 1", spec="spec.md")]
        save_state(state, path)
        content = path.read_text()
        assert '"t": "issue"' in content or '"t":"issue"' in content
        assert "i-1" in content

    def test_save_state_writes_tombstones(self, temp_dir: str) -> None:
        """Test save_state writes tombstone records."""
        path = Path(temp_dir) / "plan.jsonl"
        state = RalphState()
        state.tombstones = [
            Tombstone(
                id="t-1", done_at="commit", reason="reason", tombstone_type="reject"
            ),
        ]
        save_state(state, path)
        content = path.read_text()
        assert '"t": "reject"' in content or '"t":"reject"' in content

    def test_save_state_trailing_newline(self, temp_dir: str) -> None:
        """Test save_state adds trailing newline."""
        path = Path(temp_dir) / "plan.jsonl"
        state = RalphState(spec="test.md")
        save_state(state, path)
        content = path.read_text()
        assert content.endswith("\n")

    def test_save_state_empty_state(self, temp_dir: str) -> None:
        """Test save_state handles empty state."""
        path = Path(temp_dir) / "plan.jsonl"
        state = RalphState()
        save_state(state, path)
        content = path.read_text()
        assert content == "" or content == "\n"


class TestStateRoundtrip:
    """Integration tests for save->load roundtrip."""

    def test_roundtrip_preserves_spec(self, temp_dir: str) -> None:
        """Test roundtrip preserves spec."""
        path = Path(temp_dir) / "plan.jsonl"
        state = RalphState(spec="test-spec.md")
        save_state(state, path)
        loaded = load_state(path)
        assert loaded.spec == "test-spec.md"

    def test_roundtrip_preserves_config(self, temp_dir: str) -> None:
        """Test roundtrip preserves config."""
        path = Path(temp_dir) / "plan.jsonl"
        config = RalphPlanConfig(timeout_ms=500000, max_iterations=20)
        state = RalphState(config=config)
        save_state(state, path)
        loaded = load_state(path)
        assert loaded.config is not None
        assert loaded.config.timeout_ms == 500000
        assert loaded.config.max_iterations == 20

    def test_roundtrip_preserves_tasks(self, temp_dir: str) -> None:
        """Test roundtrip preserves tasks."""
        path = Path(temp_dir) / "plan.jsonl"
        state = RalphState()
        state.tasks = [
            Task(
                id="t-1",
                name="Task 1",
                spec="spec.md",
                notes="Some notes",
                accept="Criteria",
                deps=["t-0"],
                status="p",
                priority="high",
            ),
            Task(
                id="t-2",
                name="Task 2",
                spec="spec.md",
                status="d",
                done_at="commit123",
            ),
        ]
        save_state(state, path)
        loaded = load_state(path)
        assert len(loaded.tasks) == 2
        task1 = loaded.get_task_by_id("t-1")
        assert task1 is not None
        assert task1.name == "Task 1"
        assert task1.notes == "Some notes"
        assert task1.deps == ["t-0"]
        assert task1.priority == "high"
        task2 = loaded.get_task_by_id("t-2")
        assert task2 is not None
        assert task2.status == "d"
        assert task2.done_at == "commit123"

    def test_roundtrip_preserves_issues(self, temp_dir: str) -> None:
        """Test roundtrip preserves issues."""
        path = Path(temp_dir) / "plan.jsonl"
        state = RalphState()
        state.issues = [
            Issue(id="i-1", desc="Issue 1", spec="spec.md", priority="high"),
        ]
        save_state(state, path)
        loaded = load_state(path)
        assert len(loaded.issues) == 1
        assert loaded.issues[0].id == "i-1"
        assert loaded.issues[0].desc == "Issue 1"
        assert loaded.issues[0].priority == "high"

    def test_roundtrip_preserves_tombstones(self, temp_dir: str) -> None:
        """Test roundtrip preserves tombstones."""
        path = Path(temp_dir) / "plan.jsonl"
        state = RalphState()
        state.tombstones = [
            Tombstone(
                id="t-1", done_at="commit", reason="reason", tombstone_type="reject"
            ),
            Tombstone(id="t-2", done_at="commit2", reason="", tombstone_type="accept"),
        ]
        save_state(state, path)
        loaded = load_state(path)
        assert len(loaded.tombstones) == 2

    def test_roundtrip_full_state(self, temp_dir: str) -> None:
        """Test roundtrip with complete state."""
        path = Path(temp_dir) / "plan.jsonl"
        state = RalphState(
            spec="full-test.md",
            config=RalphPlanConfig(timeout_ms=600000),
        )
        state.tasks = [
            Task(id="t-1", name="Pending", spec="full-test.md", status="p"),
            Task(id="t-2", name="Done", spec="full-test.md", status="d", done_at="abc"),
        ]
        state.issues = [
            Issue(id="i-1", desc="Issue", spec="full-test.md"),
        ]
        state.tombstones = [
            Tombstone(id="t-old", done_at="old", reason="old reason"),
        ]
        save_state(state, path)
        loaded = load_state(path)
        assert loaded.spec == "full-test.md"
        assert loaded.config is not None
        assert loaded.config.timeout_ms == 600000
        assert len(loaded.tasks) == 2
        assert len(loaded.issues) == 1
        assert len(loaded.tombstones) == 1
