"""Unit tests for ralph.state module."""

import json
import pytest
from pathlib import Path

from ralph.state import RalphState, load_state, save_state
from ralph.models import Task, Issue, Tombstone, RalphPlanConfig


class TestRalphState:
    """Tests for RalphState class."""

    def test_state_creation_empty(self):
        """Test creating an empty RalphState."""
        state = RalphState()
        assert state.tasks == []
        assert state.issues == []
        assert state.tombstones == {"accepted": [], "rejected": []}
        assert state.config is None
        assert state.spec is None
        assert state.current_task_id is None

    def test_state_pending_property(self):
        """Test pending property filters tasks with status 'p'."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Task 1", spec="spec.md", status="p"),
            Task(id="t-2", name="Task 2", spec="spec.md", status="d"),
            Task(id="t-3", name="Task 3", spec="spec.md", status="p"),
        ]
        pending = state.pending
        assert len(pending) == 2
        assert pending[0].id == "t-1"
        assert pending[1].id == "t-3"

    def test_state_done_property(self):
        """Test done property filters tasks with status 'd'."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Task 1", spec="spec.md", status="d"),
            Task(id="t-2", name="Task 2", spec="spec.md", status="p"),
            Task(id="t-3", name="Task 3", spec="spec.md", status="d"),
        ]
        done = state.done
        assert len(done) == 2
        assert done[0].id == "t-1"
        assert done[1].id == "t-3"

    def test_state_accepted_property(self):
        """Test accepted property filters tasks with status 'a'."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Task 1", spec="spec.md", status="a"),
            Task(id="t-2", name="Task 2", spec="spec.md", status="d"),
            Task(id="t-3", name="Task 3", spec="spec.md", status="a"),
        ]
        accepted = state.accepted
        assert len(accepted) == 2
        assert accepted[0].id == "t-1"
        assert accepted[1].id == "t-3"

    def test_state_get_next_task_no_deps(self):
        """Test get_next_task returns first pending task with no deps."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Task 1", spec="spec.md", status="p"),
            Task(id="t-2", name="Task 2", spec="spec.md", status="p"),
        ]
        next_task = state.get_next_task()
        assert next_task is not None
        assert next_task.id == "t-1"

    def test_state_get_next_task_with_deps(self):
        """Test get_next_task respects dependencies."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Task 1", spec="spec.md", status="p", deps=["t-2"]),
            Task(id="t-2", name="Task 2", spec="spec.md", status="p"),
        ]
        next_task = state.get_next_task()
        assert next_task is not None
        assert next_task.id == "t-2"

    def test_state_get_next_task_deps_satisfied(self):
        """Test get_next_task when deps are satisfied via tombstones."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Task 1", spec="spec.md", status="p", deps=["t-dep"]),
        ]
        state.tombstones["accepted"].append(
            Tombstone(id="t-dep", done_at="abc", reason="done", tombstone_type="accept")
        )
        next_task = state.get_next_task()
        assert next_task is not None
        assert next_task.id == "t-1"

    def test_state_get_next_task_by_priority(self):
        """Test get_next_task returns high priority first."""
        state = RalphState()
        state.tasks = [
            Task(id="t-1", name="Low", spec="spec.md", status="p", priority="low"),
            Task(id="t-2", name="High", spec="spec.md", status="p", priority="high"),
            Task(
                id="t-3", name="Medium", spec="spec.md", status="p", priority="medium"
            ),
        ]
        next_task = state.get_next_task()
        assert next_task is not None
        assert next_task.id == "t-2"

    def test_state_to_dict(self):
        """Test RalphState serialization to dict."""
        state = RalphState()
        state.spec = "test-spec.md"
        state.tasks = [
            Task(id="t-1", name="Pending", spec="test-spec.md", status="p"),
            Task(id="t-2", name="Done", spec="test-spec.md", status="d"),
        ]
        state.issues = [Issue(id="i-1", desc="Issue 1", spec="test-spec.md")]
        state.tombstones["accepted"].append(
            Tombstone(id="t-old", done_at="abc", reason="done", tombstone_type="accept")
        )
        d = state.to_dict()
        assert d["spec"] == "test-spec.md"
        assert len(d["tasks"]["pending"]) == 1
        assert len(d["tasks"]["done"]) == 1
        assert len(d["issues"]) == 1
        assert len(d["tombstones"]["accepted"]) == 1


class TestLoadState:
    """Tests for load_state function."""

    def test_load_state_empty(self, tmp_path):
        """Test loading state from empty/missing file."""
        plan_path = tmp_path / "plan.jsonl"
        state = load_state(plan_path)
        assert state.tasks == []
        assert state.issues == []
        assert state.tombstones == {"accepted": [], "rejected": []}
        assert state.config is None
        assert state.spec is None

    def test_load_state_empty_file(self, tmp_path):
        """Test loading state from empty file."""
        plan_path = tmp_path / "plan.jsonl"
        plan_path.write_text("")
        state = load_state(plan_path)
        assert state.tasks == []
        assert state.issues == []

    def test_load_state_with_tasks(self, tmp_path):
        """Test loading state with tasks from file."""
        plan_path = tmp_path / "plan.jsonl"
        lines = [
            json.dumps({"t": "spec", "spec": "my-spec.md"}),
            json.dumps(
                {
                    "t": "task",
                    "id": "t-1",
                    "name": "Task 1",
                    "spec": "my-spec.md",
                    "s": "p",
                }
            ),
            json.dumps(
                {
                    "t": "task",
                    "id": "t-2",
                    "name": "Task 2",
                    "spec": "my-spec.md",
                    "s": "d",
                    "deps": ["t-1"],
                }
            ),
        ]
        plan_path.write_text("\n".join(lines))
        state = load_state(plan_path)
        assert state.spec == "my-spec.md"
        assert len(state.tasks) == 2
        assert state.tasks[0].id == "t-1"
        assert state.tasks[0].name == "Task 1"
        assert state.tasks[0].status == "p"
        assert state.tasks[1].id == "t-2"
        assert state.tasks[1].deps == ["t-1"]

    def test_load_state_with_issues(self, tmp_path):
        """Test loading state with issues from file."""
        plan_path = tmp_path / "plan.jsonl"
        lines = [
            json.dumps(
                {"t": "issue", "id": "i-1", "desc": "Issue 1", "spec": "spec.md"}
            ),
            json.dumps(
                {
                    "t": "issue",
                    "id": "i-2",
                    "desc": "Issue 2",
                    "spec": "spec.md",
                    "priority": "high",
                }
            ),
        ]
        plan_path.write_text("\n".join(lines))
        state = load_state(plan_path)
        assert len(state.issues) == 2
        assert state.issues[0].id == "i-1"
        assert state.issues[0].desc == "Issue 1"
        assert state.issues[1].priority == "high"

    def test_load_state_with_tombstones(self, tmp_path):
        """Test loading state with tombstones from file."""
        plan_path = tmp_path / "plan.jsonl"
        lines = [
            json.dumps(
                {"t": "accept", "id": "t-1", "done_at": "abc", "reason": "passed"}
            ),
            json.dumps(
                {"t": "reject", "id": "t-2", "done_at": "def", "reason": "failed tests"}
            ),
        ]
        plan_path.write_text("\n".join(lines))
        state = load_state(plan_path)
        assert len(state.tombstones["accepted"]) == 1
        assert len(state.tombstones["rejected"]) == 1
        assert state.tombstones["accepted"][0].id == "t-1"
        assert state.tombstones["rejected"][0].id == "t-2"

    def test_load_state_with_config(self, tmp_path):
        """Test loading state with config from file."""
        plan_path = tmp_path / "plan.jsonl"
        lines = [
            json.dumps({"t": "config", "timeout_ms": 600000, "max_iterations": 5}),
        ]
        plan_path.write_text("\n".join(lines))
        state = load_state(plan_path)
        assert state.config is not None
        assert state.config.timeout_ms == 600000
        assert state.config.max_iterations == 5

    def test_load_state_marks_accepted_tasks(self, tmp_path):
        """Test that tasks with accept tombstones get status 'a'."""
        plan_path = tmp_path / "plan.jsonl"
        lines = [
            json.dumps(
                {
                    "t": "task",
                    "id": "t-1",
                    "name": "Task 1",
                    "spec": "spec.md",
                    "s": "d",
                }
            ),
            json.dumps(
                {"t": "accept", "id": "t-1", "done_at": "abc", "reason": "passed"}
            ),
        ]
        plan_path.write_text("\n".join(lines))
        state = load_state(plan_path)
        assert state.tasks[0].status == "a"

    def test_load_state_ignores_blank_lines(self, tmp_path):
        """Test that blank lines in file are ignored."""
        plan_path = tmp_path / "plan.jsonl"
        content = '{"t": "task", "id": "t-1", "name": "Task 1", "spec": "spec.md", "s": "p"}\n\n\n'
        plan_path.write_text(content)
        state = load_state(plan_path)
        assert len(state.tasks) == 1


class TestSaveState:
    """Tests for save_state function."""

    def test_save_state(self, tmp_path):
        """Test saving state to file."""
        plan_path = tmp_path / "plan.jsonl"
        state = RalphState()
        state.spec = "test-spec.md"
        state.tasks = [
            Task(id="t-1", name="Task 1", spec="test-spec.md", status="p"),
        ]
        state.issues = [Issue(id="i-1", desc="Issue 1", spec="test-spec.md")]
        save_state(state, plan_path)
        content = plan_path.read_text()
        assert "test-spec.md" in content
        assert "t-1" in content
        assert "i-1" in content

    def test_save_state_with_config(self, tmp_path):
        """Test saving state with config."""
        plan_path = tmp_path / "plan.jsonl"
        state = RalphState()
        state.config = RalphPlanConfig(timeout_ms=300000)
        save_state(state, plan_path)
        content = plan_path.read_text()
        assert '"t": "config"' in content
        assert "300000" in content

    def test_save_state_with_tombstones(self, tmp_path):
        """Test saving state with tombstones."""
        plan_path = tmp_path / "plan.jsonl"
        state = RalphState()
        state.tombstones["accepted"].append(
            Tombstone(id="t-1", done_at="abc", reason="passed", tombstone_type="accept")
        )
        state.tombstones["rejected"].append(
            Tombstone(id="t-2", done_at="def", reason="failed", tombstone_type="reject")
        )
        save_state(state, plan_path)
        content = plan_path.read_text()
        assert '"t": "accept"' in content
        assert '"t": "reject"' in content

    def test_save_state_empty(self, tmp_path):
        """Test saving empty state still writes stage record."""
        plan_path = tmp_path / "plan.jsonl"
        state = RalphState()
        save_state(state, plan_path)
        content = plan_path.read_text()
        # Empty state still has stage record
        assert '"t": "stage"' in content
        assert '"stage": "PLAN"' in content


class TestStateRoundtrip:
    """Tests for state serialization roundtrip."""

    def test_state_roundtrip(self, tmp_path):
        """Test full state save/load roundtrip."""
        plan_path = tmp_path / "plan.jsonl"
        original = RalphState()
        original.spec = "roundtrip-spec.md"
        original.config = RalphPlanConfig(timeout_ms=450000, max_iterations=7)
        original.tasks = [
            Task(
                id="t-1",
                name="Pending",
                spec="roundtrip-spec.md",
                status="p",
                priority="high",
            ),
            Task(
                id="t-2",
                name="Done",
                spec="roundtrip-spec.md",
                status="d",
                deps=["t-1"],
            ),
        ]
        original.issues = [
            Issue(
                id="i-1", desc="Test issue", spec="roundtrip-spec.md", priority="medium"
            ),
        ]
        original.tombstones["accepted"].append(
            Tombstone(
                id="t-old",
                done_at="abc",
                reason="passed",
                tombstone_type="accept",
                name="Old task",
            )
        )
        save_state(original, plan_path)
        restored = load_state(plan_path)
        assert restored.spec == original.spec
        assert restored.config is not None
        assert restored.config.timeout_ms == original.config.timeout_ms
        assert restored.config.max_iterations == original.config.max_iterations
        assert len(restored.tasks) == 2
        assert restored.tasks[0].id == "t-1"
        assert restored.tasks[0].priority == "high"
        assert restored.tasks[1].id == "t-2"
        assert restored.tasks[1].deps == ["t-1"]
        assert len(restored.issues) == 1
        assert restored.issues[0].id == "i-1"
        assert len(restored.tombstones["accepted"]) == 1
        assert restored.tombstones["accepted"][0].id == "t-old"

    def test_state_roundtrip_preserves_task_fields(self, tmp_path):
        """Test roundtrip preserves all task fields."""
        plan_path = tmp_path / "plan.jsonl"
        original = RalphState()
        original.tasks = [
            Task(
                id="t-full",
                name="Full task",
                spec="spec.md",
                notes="Detailed notes",
                accept="tests pass",
                deps=["t-dep1", "t-dep2"],
                status="p",
                priority="high",
                parent="t-parent",
                created_from="t-orig",
                supersedes="t-old",
                timeout_ms=60000,
            ),
        ]
        save_state(original, plan_path)
        restored = load_state(plan_path)
        task = restored.tasks[0]
        assert task.id == "t-full"
        assert task.name == "Full task"
        assert task.notes == "Detailed notes"
        assert task.accept == "tests pass"
        assert task.deps == ["t-dep1", "t-dep2"]
        assert task.priority == "high"
        assert task.parent == "t-parent"
        assert task.created_from == "t-orig"
        assert task.supersedes == "t-old"
        assert task.timeout_ms == 60000
