"""Unit tests for ralph.models module."""

import pytest
from ralph.models import Task, Issue, Tombstone, RalphPlanConfig


class TestTask:
    """Tests for Task model."""

    def test_task_creation(self):
        """Test creating a Task with required and optional fields."""
        task = Task(
            id="t-abc123",
            name="Test task",
            spec="test-spec.md",
            notes="Implementation notes",
            accept="pytest runs successfully",
            deps=["t-dep1", "t-dep2"],
            priority="high",
        )
        assert task.id == "t-abc123"
        assert task.name == "Test task"
        assert task.spec == "test-spec.md"
        assert task.notes == "Implementation notes"
        assert task.accept == "pytest runs successfully"
        assert task.deps == ["t-dep1", "t-dep2"]
        assert task.status == "p"
        assert task.priority == "high"
        assert task.done_at is None
        assert task.needs_decompose is False
        assert task.decompose_depth == 0

    def test_task_to_dict(self):
        """Test Task serialization to dict."""
        task = Task(
            id="t-xyz789",
            name="Serializable task",
            spec="spec.md",
            notes="Some notes",
            accept="exit 0",
            deps=["t-dep"],
            status="d",
            done_at="abc123",
            priority="medium",
        )
        d = task.to_dict()
        assert d["t"] == "task"
        assert d["id"] == "t-xyz789"
        assert d["name"] == "Serializable task"
        assert d["spec"] == "spec.md"
        assert d["notes"] == "Some notes"
        assert d["accept"] == "exit 0"
        assert d["deps"] == ["t-dep"]
        assert d["s"] == "d"
        assert d["done_at"] == "abc123"
        assert d["priority"] == "medium"

    def test_task_to_dict_minimal(self):
        """Test Task serialization with only required fields."""
        task = Task(id="t-min", name="Minimal task", spec="s.md")
        d = task.to_dict()
        assert d["t"] == "task"
        assert d["id"] == "t-min"
        assert d["name"] == "Minimal task"
        assert d["spec"] == "s.md"
        assert d["s"] == "p"
        assert "notes" not in d
        assert "accept" not in d
        assert "deps" not in d

    def test_task_from_dict(self):
        """Test Task deserialization from dict."""
        d = {
            "t": "task",
            "id": "t-from",
            "name": "From dict task",
            "spec": "spec.md",
            "notes": "Loaded notes",
            "accept": "test passes",
            "deps": ["t-a", "t-b"],
            "s": "d",
            "done_at": "commit123",
            "priority": "low",
        }
        task = Task.from_dict(d)
        assert task.id == "t-from"
        assert task.name == "From dict task"
        assert task.spec == "spec.md"
        assert task.notes == "Loaded notes"
        assert task.accept == "test passes"
        assert task.deps == ["t-a", "t-b"]
        assert task.status == "d"
        assert task.done_at == "commit123"
        assert task.priority == "low"

    def test_task_from_dict_with_desc(self):
        """Test Task deserialization when using 'desc' instead of 'name'."""
        d = {"id": "t-desc", "desc": "Task from desc field", "spec": "s.md"}
        task = Task.from_dict(d)
        assert task.name == "Task from desc field"

    def test_task_roundtrip(self):
        """Test Task serialization roundtrip."""
        # Note: status="d" with kill_reason is invalid - __post_init__ will fix it
        # So we use status="p" here for a valid roundtrip test
        original = Task(
            id="t-round",
            name="Roundtrip task",
            spec="spec.md",
            notes="Detailed notes",
            accept="all tests pass",
            deps=["t-x"],
            status="p",
            done_at=None,
            needs_decompose=True,
            kill_reason="timeout",
            priority="high",
            reject_reason="failed tests",
            parent="t-parent",
            created_from="t-original",
            supersedes="t-old",
            decompose_depth=2,
            timeout_ms=60000,
        )
        d = original.to_dict()
        restored = Task.from_dict(d)
        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.spec == original.spec
        assert restored.notes == original.notes
        assert restored.accept == original.accept
        assert restored.deps == original.deps
        assert restored.status == original.status
        assert restored.done_at == original.done_at
        assert restored.needs_decompose == original.needs_decompose
        assert restored.kill_reason == original.kill_reason
        assert restored.priority == original.priority
        assert restored.reject_reason == original.reject_reason
        assert restored.parent == original.parent
        assert restored.created_from == original.created_from
        assert restored.supersedes == original.supersedes
        assert restored.decompose_depth == original.decompose_depth
        assert restored.timeout_ms == original.timeout_ms

    def test_task_kill_reason_clears_done_status(self):
        """Test that kill_reason and status=d are mutually exclusive.

        A killed task should not be marked as done - it needs decomposition.
        The __post_init__ validation should reset status to 'p' if both are set.
        """
        task = Task(
            id="t-killed",
            name="Killed task",
            spec="spec.md",
            status="d",
            done_at="abc123",
            kill_reason="timeout",
        )
        # __post_init__ should have fixed the contradictory state
        assert task.status == "p"
        assert task.done_at is None
        assert task.kill_reason == "timeout"


class TestIssue:
    """Tests for Issue model."""

    def test_issue_creation(self):
        """Test creating an Issue."""
        issue = Issue(
            id="i-abc123",
            desc="Test issue description",
            spec="test-spec.md",
            priority="high",
        )
        assert issue.id == "i-abc123"
        assert issue.desc == "Test issue description"
        assert issue.spec == "test-spec.md"
        assert issue.priority == "high"

    def test_issue_creation_minimal(self):
        """Test creating an Issue with minimal fields."""
        issue = Issue(id="i-min", desc="Minimal issue", spec="s.md")
        assert issue.id == "i-min"
        assert issue.desc == "Minimal issue"
        assert issue.spec == "s.md"
        assert issue.priority is None

    def test_issue_to_dict(self):
        """Test Issue serialization to dict."""
        issue = Issue(
            id="i-ser", desc="Serializable issue", spec="spec.md", priority="medium"
        )
        d = issue.to_dict()
        assert d["t"] == "issue"
        assert d["id"] == "i-ser"
        assert d["desc"] == "Serializable issue"
        assert d["spec"] == "spec.md"
        assert d["priority"] == "medium"

    def test_issue_from_dict(self):
        """Test Issue deserialization from dict."""
        d = {
            "t": "issue",
            "id": "i-from",
            "desc": "Loaded issue",
            "spec": "spec.md",
            "priority": "low",
        }
        issue = Issue.from_dict(d)
        assert issue.id == "i-from"
        assert issue.desc == "Loaded issue"
        assert issue.spec == "spec.md"
        assert issue.priority == "low"

    def test_issue_roundtrip(self):
        """Test Issue serialization roundtrip."""
        original = Issue(
            id="i-round", desc="Roundtrip issue", spec="spec.md", priority="high"
        )
        d = original.to_dict()
        restored = Issue.from_dict(d)
        assert restored.id == original.id
        assert restored.desc == original.desc
        assert restored.spec == original.spec
        assert restored.priority == original.priority


class TestTombstone:
    """Tests for Tombstone model."""

    def test_tombstone_creation(self):
        """Test creating a Tombstone."""
        tombstone = Tombstone(
            id="t-tomb123",
            done_at="abc123",
            reason="Task completed successfully",
            tombstone_type="accept",
            name="Completed task",
            timestamp="2024-01-15T10:00:00Z",
            changed_files=["file1.py", "file2.py"],
            notes="Some notes",
        )
        assert tombstone.id == "t-tomb123"
        assert tombstone.done_at == "abc123"
        assert tombstone.reason == "Task completed successfully"
        assert tombstone.tombstone_type == "accept"
        assert tombstone.name == "Completed task"
        assert tombstone.timestamp == "2024-01-15T10:00:00Z"
        assert tombstone.changed_files == ["file1.py", "file2.py"]
        assert tombstone.notes == "Some notes"

    def test_tombstone_creation_minimal(self):
        """Test creating a Tombstone with minimal fields."""
        tombstone = Tombstone(id="t-min", done_at="xyz", reason="done")
        assert tombstone.id == "t-min"
        assert tombstone.done_at == "xyz"
        assert tombstone.reason == "done"
        assert tombstone.tombstone_type == "reject"
        assert tombstone.name == ""
        assert tombstone.changed_files is None

    def test_tombstone_to_dict(self):
        """Test Tombstone serialization to dict."""
        tombstone = Tombstone(
            id="t-ser",
            done_at="commit1",
            reason="Accepted",
            tombstone_type="accept",
            name="Task name",
            timestamp="2024-01-15",
            changed_files=["a.py"],
            log_file="log.txt",
            iteration=3,
            notes="Notes here",
        )
        d = tombstone.to_dict()
        assert d["t"] == "accept"
        assert d["id"] == "t-ser"
        assert d["done_at"] == "commit1"
        assert d["reason"] == "Accepted"
        assert d["name"] == "Task name"
        assert d["timestamp"] == "2024-01-15"
        assert d["changed_files"] == ["a.py"]
        assert d["log_file"] == "log.txt"
        assert d["iteration"] == 3
        assert d["notes"] == "Notes here"

    def test_tombstone_from_dict(self):
        """Test Tombstone deserialization from dict."""
        d = {
            "id": "t-from",
            "done_at": "commit2",
            "reason": "Rejected due to failures",
            "name": "Failed task",
            "timestamp": "2024-01-16",
            "changed_files": ["b.py", "c.py"],
            "iteration": 5,
        }
        tombstone = Tombstone.from_dict(d, tombstone_type="reject")
        assert tombstone.id == "t-from"
        assert tombstone.done_at == "commit2"
        assert tombstone.reason == "Rejected due to failures"
        assert tombstone.tombstone_type == "reject"
        assert tombstone.name == "Failed task"
        assert tombstone.timestamp == "2024-01-16"
        assert tombstone.changed_files == ["b.py", "c.py"]
        assert tombstone.iteration == 5

    def test_tombstone_roundtrip(self):
        """Test Tombstone serialization roundtrip."""
        original = Tombstone(
            id="t-round",
            done_at="commit3",
            reason="Full roundtrip",
            tombstone_type="accept",
            name="Roundtrip task",
            timestamp="2024-01-17T12:00:00Z",
            changed_files=["x.py", "y.py", "z.py"],
            log_file="roundtrip.log",
            iteration=7,
            notes="Roundtrip notes",
        )
        d = original.to_dict()
        restored = Tombstone.from_dict(d, tombstone_type=d["t"])
        assert restored.id == original.id
        assert restored.done_at == original.done_at
        assert restored.reason == original.reason
        assert restored.tombstone_type == original.tombstone_type
        assert restored.name == original.name
        assert restored.timestamp == original.timestamp
        assert restored.changed_files == original.changed_files
        assert restored.log_file == original.log_file
        assert restored.iteration == original.iteration
        assert restored.notes == original.notes


class TestRalphPlanConfig:
    """Tests for RalphPlanConfig model."""

    def test_ralph_plan_config_defaults(self):
        """Test RalphPlanConfig with default values."""
        config = RalphPlanConfig()
        assert config.timeout_ms == 900000
        assert config.max_iterations == 10
        assert config.context_warn == 0.70
        assert config.context_compact == 0.85
        assert config.context_kill == 0.95

    def test_ralph_plan_config_custom(self):
        """Test RalphPlanConfig with custom values."""
        config = RalphPlanConfig(
            timeout_ms=600000,
            max_iterations=5,
            context_warn=0.60,
            context_compact=0.80,
            context_kill=0.90,
        )
        assert config.timeout_ms == 600000
        assert config.max_iterations == 5
        assert config.context_warn == 0.60
        assert config.context_compact == 0.80
        assert config.context_kill == 0.90

    def test_ralph_plan_config_to_dict(self):
        """Test RalphPlanConfig serialization to dict."""
        config = RalphPlanConfig(timeout_ms=120000, max_iterations=3)
        d = config.to_dict()
        assert d["t"] == "config"
        assert d["timeout_ms"] == 120000
        assert d["max_iterations"] == 3
        assert d["context_warn"] == 0.70
        assert d["context_compact"] == 0.85
        assert d["context_kill"] == 0.95

    def test_ralph_plan_config_from_dict(self):
        """Test RalphPlanConfig deserialization from dict."""
        d = {
            "t": "config",
            "timeout_ms": 300000,
            "max_iterations": 15,
            "context_warn": 0.50,
            "context_compact": 0.75,
            "context_kill": 0.92,
        }
        config = RalphPlanConfig.from_dict(d)
        assert config.timeout_ms == 300000
        assert config.max_iterations == 15
        assert config.context_warn == 0.50
        assert config.context_compact == 0.75
        assert config.context_kill == 0.92

    def test_ralph_plan_config_from_dict_defaults(self):
        """Test RalphPlanConfig from_dict with missing keys uses defaults."""
        d = {"t": "config"}
        config = RalphPlanConfig.from_dict(d)
        assert config.timeout_ms == 900000
        assert config.max_iterations == 10
        assert config.context_warn == 0.70
        assert config.context_compact == 0.85
        assert config.context_kill == 0.95

    def test_ralph_plan_config_roundtrip(self):
        """Test RalphPlanConfig serialization roundtrip."""
        original = RalphPlanConfig(
            timeout_ms=450000,
            max_iterations=8,
            context_warn=0.65,
            context_compact=0.82,
            context_kill=0.93,
        )
        d = original.to_dict()
        restored = RalphPlanConfig.from_dict(d)
        assert restored.timeout_ms == original.timeout_ms
        assert restored.max_iterations == original.max_iterations
        assert restored.context_warn == original.context_warn
        assert restored.context_compact == original.context_compact
        assert restored.context_kill == original.context_kill
