"""Unit tests for ralph.models module."""

import json

import pytest

from ralph.models import Issue, RalphPlanConfig, Task, Tombstone


class TestTask:
    """Tests for the Task dataclass."""

    def test_task_creation_minimal(self) -> None:
        """Test creating a task with minimal required fields."""
        task = Task(id="t-abc123", name="Test task", spec="test.md")
        assert task.id == "t-abc123"
        assert task.name == "Test task"
        assert task.spec == "test.md"
        assert task.status == "p"
        assert task.notes is None
        assert task.accept is None
        assert task.deps is None
        assert task.done_at is None
        assert task.priority is None

    def test_task_creation_full(self, sample_task: Task) -> None:
        """Test creating a task with all fields using fixture."""
        assert sample_task.id == "t-abc123"
        assert sample_task.name == "Test task"
        assert sample_task.spec == "test-spec.md"
        assert sample_task.notes == "Some implementation notes"
        assert sample_task.accept == "Verify it works"
        assert sample_task.status == "p"
        assert sample_task.priority == "high"

    def test_task_status_pending(self) -> None:
        """Test that new tasks default to pending status."""
        task = Task(id="t-new", name="New task", spec="spec.md")
        assert task.status == "p"

    def test_task_status_done(self, sample_done_task: Task) -> None:
        """Test task with done status."""
        assert sample_done_task.status == "d"
        assert sample_done_task.done_at == "abc123def"

    def test_task_with_dependencies(self) -> None:
        """Test task with dependency list."""
        task = Task(
            id="t-dep",
            name="Dependent task",
            spec="spec.md",
            deps=["t-first", "t-second"],
        )
        assert task.deps == ["t-first", "t-second"]

    def test_task_with_decompose_info(self) -> None:
        """Test task that was killed and needs decomposition."""
        task = Task(
            id="t-killed",
            name="Killed task",
            spec="spec.md",
            needs_decompose=True,
            kill_reason="timeout",
            kill_log="/path/to/log.txt",
            decompose_depth=1,
        )
        assert task.needs_decompose is True
        assert task.kill_reason == "timeout"
        assert task.kill_log == "/path/to/log.txt"
        assert task.decompose_depth == 1

    def test_task_with_parent(self) -> None:
        """Test task created from decomposition."""
        task = Task(
            id="t-child",
            name="Child task",
            spec="spec.md",
            parent="t-parent",
            decompose_depth=2,
        )
        assert task.parent == "t-parent"
        assert task.decompose_depth == 2

    def test_task_with_created_from_issue(self) -> None:
        """Test task created from an issue."""
        task = Task(
            id="t-from-issue",
            name="Task from issue",
            spec="spec.md",
            created_from="i-abc123",
        )
        assert task.created_from == "i-abc123"

    def test_task_with_supersedes(self) -> None:
        """Test task that supersedes another task."""
        task = Task(
            id="t-new-approach",
            name="New approach",
            spec="spec.md",
            supersedes="t-old-approach",
        )
        assert task.supersedes == "t-old-approach"

    def test_task_with_reject_reason(self) -> None:
        """Test task that was rejected and is being retried."""
        task = Task(
            id="t-retry",
            name="Retry task",
            spec="spec.md",
            reject_reason="Implementation incomplete",
        )
        assert task.reject_reason == "Implementation incomplete"

    def test_task_with_timeout_override(self) -> None:
        """Test task with custom timeout."""
        task = Task(
            id="t-slow",
            name="Slow task",
            spec="spec.md",
            timeout_ms=600000,
        )
        assert task.timeout_ms == 600000

    def test_task_to_dict_minimal(self) -> None:
        """Test serializing minimal task to dict."""
        task = Task(id="t-min", name="Minimal", spec="spec.md")
        d = task.to_dict()
        assert d["t"] == "task"
        assert d["id"] == "t-min"
        assert d["name"] == "Minimal"
        assert d["spec"] == "spec.md"
        assert d["s"] == "p"
        assert "notes" not in d
        assert "accept" not in d
        assert "deps" not in d
        assert "done_at" not in d

    def test_task_to_dict_full(self) -> None:
        """Test serializing full task to dict."""
        task = Task(
            id="t-full",
            name="Full task",
            spec="spec.md",
            notes="Notes here",
            accept="Acceptance criteria",
            deps=["t-dep1"],
            status="d",
            done_at="commit123",
            needs_decompose=True,
            kill_reason="context",
            kill_log="/log.txt",
            priority="high",
            reject_reason="Rejected",
            parent="t-parent",
            created_from="i-issue",
            supersedes="t-old",
            decompose_depth=2,
            timeout_ms=500000,
        )
        d = task.to_dict()
        assert d["t"] == "task"
        assert d["id"] == "t-full"
        assert d["name"] == "Full task"
        assert d["spec"] == "spec.md"
        assert d["notes"] == "Notes here"
        assert d["accept"] == "Acceptance criteria"
        assert d["deps"] == ["t-dep1"]
        assert d["s"] == "d"
        assert d["done_at"] == "commit123"
        assert d["decompose"] is True
        assert d["kill"] == "context"
        assert d["kill_log"] == "/log.txt"
        assert d["priority"] == "high"
        assert d["reject"] == "Rejected"
        assert d["parent"] == "t-parent"
        assert d["created_from"] == "i-issue"
        assert d["supersedes"] == "t-old"
        assert d["decompose_depth"] == 2
        assert d["timeout_ms"] == 500000

    def test_task_to_jsonl(self) -> None:
        """Test serializing task to JSONL string."""
        task = Task(id="t-json", name="JSON task", spec="spec.md")
        jsonl = task.to_jsonl()
        parsed = json.loads(jsonl)
        assert parsed["t"] == "task"
        assert parsed["id"] == "t-json"
        assert parsed["name"] == "JSON task"

    def test_task_from_dict(self) -> None:
        """Test deserializing task from dict."""
        d = {
            "id": "t-from",
            "name": "From dict",
            "spec": "spec.md",
            "notes": "Notes",
            "accept": "Criteria",
            "deps": ["t-dep"],
            "s": "d",
            "done_at": "commit456",
            "priority": "medium",
        }
        task = Task.from_dict(d)
        assert task.id == "t-from"
        assert task.name == "From dict"
        assert task.spec == "spec.md"
        assert task.notes == "Notes"
        assert task.accept == "Criteria"
        assert task.deps == ["t-dep"]
        assert task.status == "d"
        assert task.done_at == "commit456"
        assert task.priority == "medium"

    def test_task_from_dict_with_decompose_fields(self) -> None:
        """Test deserializing task with decompose fields."""
        d = {
            "id": "t-decompose",
            "name": "Decompose task",
            "spec": "spec.md",
            "s": "p",
            "decompose": True,
            "kill": "timeout",
            "kill_log": "/path.txt",
            "decompose_depth": 1,
        }
        task = Task.from_dict(d)
        assert task.needs_decompose is True
        assert task.kill_reason == "timeout"
        assert task.kill_log == "/path.txt"
        assert task.decompose_depth == 1

    def test_task_from_dict_with_lineage_fields(self) -> None:
        """Test deserializing task with parent/supersedes/created_from."""
        d = {
            "id": "t-lineage",
            "name": "Lineage task",
            "spec": "spec.md",
            "s": "p",
            "parent": "t-parent",
            "created_from": "i-issue",
            "supersedes": "t-old",
        }
        task = Task.from_dict(d)
        assert task.parent == "t-parent"
        assert task.created_from == "i-issue"
        assert task.supersedes == "t-old"

    def test_task_from_dict_legacy_desc_field(self) -> None:
        """Test deserializing task with legacy 'desc' field instead of 'name'."""
        d = {
            "id": "t-legacy",
            "desc": "Legacy description",
            "spec": "spec.md",
            "s": "p",
        }
        task = Task.from_dict(d)
        assert task.name == "Legacy description"

    def test_task_from_dict_defaults(self) -> None:
        """Test that from_dict uses proper defaults."""
        d = {"id": "t-minimal", "name": "Minimal"}
        task = Task.from_dict(d)
        assert task.spec == ""
        assert task.status == "p"
        assert task.needs_decompose is False
        assert task.decompose_depth == 0

    def test_task_from_jsonl(self) -> None:
        """Test from_jsonl is alias for from_dict."""
        d = {"id": "t-jsonl", "name": "JSONL task", "spec": "spec.md", "s": "p"}
        task = Task.from_jsonl(d)
        assert task.id == "t-jsonl"
        assert task.name == "JSONL task"

    def test_task_roundtrip(self) -> None:
        """Test serialization roundtrip preserves data."""
        original = Task(
            id="t-round",
            name="Roundtrip task",
            spec="spec.md",
            notes="Some notes",
            accept="Criteria",
            deps=["t-dep1", "t-dep2"],
            status="d",
            done_at="commit789",
            priority="low",
            decompose_depth=1,
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
        assert restored.priority == original.priority
        assert restored.decompose_depth == original.decompose_depth


class TestIssue:
    """Tests for the Issue dataclass."""

    def test_issue_creation_minimal(self) -> None:
        """Test creating an issue with minimal fields."""
        issue = Issue(id="i-abc123", desc="Test issue", spec="test.md")
        assert issue.id == "i-abc123"
        assert issue.desc == "Test issue"
        assert issue.spec == "test.md"
        assert issue.priority is None

    def test_issue_creation_with_priority(self, sample_issue: Issue) -> None:
        """Test creating an issue with priority using fixture."""
        assert sample_issue.id == "i-ghi789"
        assert sample_issue.desc == "Something needs investigation"
        assert sample_issue.spec == "test-spec.md"
        assert sample_issue.priority == "high"

    def test_issue_to_dict_minimal(self) -> None:
        """Test serializing minimal issue to dict."""
        issue = Issue(id="i-min", desc="Minimal issue", spec="spec.md")
        d = issue.to_dict()
        assert d["t"] == "issue"
        assert d["id"] == "i-min"
        assert d["desc"] == "Minimal issue"
        assert d["spec"] == "spec.md"
        assert "priority" not in d

    def test_issue_to_dict_with_priority(self) -> None:
        """Test serializing issue with priority to dict."""
        issue = Issue(
            id="i-priority",
            desc="Priority issue",
            spec="spec.md",
            priority="high",
        )
        d = issue.to_dict()
        assert d["priority"] == "high"

    def test_issue_to_jsonl(self) -> None:
        """Test serializing issue to JSONL string."""
        issue = Issue(id="i-json", desc="JSON issue", spec="spec.md")
        jsonl = issue.to_jsonl()
        parsed = json.loads(jsonl)
        assert parsed["t"] == "issue"
        assert parsed["id"] == "i-json"
        assert parsed["desc"] == "JSON issue"

    def test_issue_from_dict(self) -> None:
        """Test deserializing issue from dict."""
        d = {
            "id": "i-from",
            "desc": "From dict issue",
            "spec": "spec.md",
            "priority": "medium",
        }
        issue = Issue.from_dict(d)
        assert issue.id == "i-from"
        assert issue.desc == "From dict issue"
        assert issue.spec == "spec.md"
        assert issue.priority == "medium"

    def test_issue_from_dict_defaults(self) -> None:
        """Test that from_dict uses proper defaults."""
        d = {"id": "i-minimal", "desc": "Minimal"}
        issue = Issue.from_dict(d)
        assert issue.spec == ""
        assert issue.priority is None

    def test_issue_from_jsonl(self) -> None:
        """Test from_jsonl is alias for from_dict."""
        d = {"id": "i-jsonl", "desc": "JSONL issue", "spec": "spec.md"}
        issue = Issue.from_jsonl(d)
        assert issue.id == "i-jsonl"
        assert issue.desc == "JSONL issue"

    def test_issue_roundtrip(self) -> None:
        """Test serialization roundtrip preserves data."""
        original = Issue(
            id="i-round",
            desc="Roundtrip issue",
            spec="spec.md",
            priority="low",
        )
        d = original.to_dict()
        restored = Issue.from_dict(d)
        assert restored.id == original.id
        assert restored.desc == original.desc
        assert restored.spec == original.spec
        assert restored.priority == original.priority


class TestTombstone:
    """Tests for the Tombstone dataclass."""

    def test_tombstone_creation_reject(self, sample_tombstone: Tombstone) -> None:
        """Test creating a reject tombstone using fixture."""
        assert sample_tombstone.id == "t-jkl012"
        assert sample_tombstone.done_at == "xyz789abc"
        assert (
            sample_tombstone.reason == "Task rejected due to incomplete implementation"
        )
        assert sample_tombstone.tombstone_type == "reject"

    def test_tombstone_creation_accept(
        self, sample_accept_tombstone: Tombstone
    ) -> None:
        """Test creating an accept tombstone using fixture."""
        assert sample_accept_tombstone.id == "t-mno345"
        assert sample_accept_tombstone.done_at == "def456ghi"
        assert sample_accept_tombstone.reason == ""
        assert sample_accept_tombstone.tombstone_type == "accept"

    def test_tombstone_default_type(self) -> None:
        """Test that tombstone defaults to reject type."""
        tombstone = Tombstone(id="t-default", done_at="commit", reason="reason")
        assert tombstone.tombstone_type == "reject"

    def test_tombstone_to_dict_reject(self) -> None:
        """Test serializing reject tombstone to dict."""
        tombstone = Tombstone(
            id="t-rej",
            done_at="commit123",
            reason="Rejected reason",
            tombstone_type="reject",
        )
        d = tombstone.to_dict()
        assert d["t"] == "reject"
        assert d["id"] == "t-rej"
        assert d["done_at"] == "commit123"
        assert d["reason"] == "Rejected reason"

    def test_tombstone_to_dict_accept(self) -> None:
        """Test serializing accept tombstone to dict."""
        tombstone = Tombstone(
            id="t-acc",
            done_at="commit456",
            reason="",
            tombstone_type="accept",
        )
        d = tombstone.to_dict()
        assert d["t"] == "accept"
        assert d["id"] == "t-acc"
        assert d["done_at"] == "commit456"
        assert d["reason"] == ""

    def test_tombstone_to_jsonl(self) -> None:
        """Test serializing tombstone to JSONL string."""
        tombstone = Tombstone(
            id="t-json",
            done_at="commit",
            reason="reason",
            tombstone_type="reject",
        )
        jsonl = tombstone.to_jsonl()
        parsed = json.loads(jsonl)
        assert parsed["t"] == "reject"
        assert parsed["id"] == "t-json"

    def test_tombstone_from_dict_reject(self) -> None:
        """Test deserializing reject tombstone from dict."""
        d = {
            "id": "t-from-rej",
            "done_at": "commit789",
            "reason": "From dict reason",
        }
        tombstone = Tombstone.from_dict(d, tombstone_type="reject")
        assert tombstone.id == "t-from-rej"
        assert tombstone.done_at == "commit789"
        assert tombstone.reason == "From dict reason"
        assert tombstone.tombstone_type == "reject"

    def test_tombstone_from_dict_accept(self) -> None:
        """Test deserializing accept tombstone from dict."""
        d = {
            "id": "t-from-acc",
            "done_at": "commit000",
            "reason": "",
        }
        tombstone = Tombstone.from_dict(d, tombstone_type="accept")
        assert tombstone.id == "t-from-acc"
        assert tombstone.done_at == "commit000"
        assert tombstone.reason == ""
        assert tombstone.tombstone_type == "accept"

    def test_tombstone_from_dict_defaults(self) -> None:
        """Test that from_dict uses proper defaults."""
        d = {"id": "t-minimal"}
        tombstone = Tombstone.from_dict(d)
        assert tombstone.done_at == ""
        assert tombstone.reason == ""
        assert tombstone.tombstone_type == "reject"

    def test_tombstone_from_jsonl(self) -> None:
        """Test from_jsonl is alias for from_dict."""
        d = {"id": "t-jsonl", "done_at": "commit", "reason": "reason"}
        tombstone = Tombstone.from_jsonl(d, tombstone_type="accept")
        assert tombstone.id == "t-jsonl"
        assert tombstone.tombstone_type == "accept"

    def test_tombstone_roundtrip_reject(self) -> None:
        """Test serialization roundtrip for reject tombstone."""
        original = Tombstone(
            id="t-round-rej",
            done_at="commit111",
            reason="Roundtrip reject",
            tombstone_type="reject",
        )
        d = original.to_dict()
        restored = Tombstone.from_dict(d, tombstone_type=d["t"])
        assert restored.id == original.id
        assert restored.done_at == original.done_at
        assert restored.reason == original.reason
        assert restored.tombstone_type == original.tombstone_type

    def test_tombstone_roundtrip_accept(self) -> None:
        """Test serialization roundtrip for accept tombstone."""
        original = Tombstone(
            id="t-round-acc",
            done_at="commit222",
            reason="",
            tombstone_type="accept",
        )
        d = original.to_dict()
        restored = Tombstone.from_dict(d, tombstone_type=d["t"])
        assert restored.id == original.id
        assert restored.done_at == original.done_at
        assert restored.reason == original.reason
        assert restored.tombstone_type == original.tombstone_type


class TestRalphPlanConfig:
    """Tests for the RalphPlanConfig dataclass."""

    def test_config_creation_defaults(self) -> None:
        """Test creating config with all defaults."""
        config = RalphPlanConfig()
        assert config.timeout_ms == 300000
        assert config.max_iterations == 10
        assert config.context_warn == 0.70
        assert config.context_compact == 0.85
        assert config.context_kill == 0.95

    def test_config_creation_custom(self, sample_config: RalphPlanConfig) -> None:
        """Test creating config with custom values using fixture."""
        assert sample_config.timeout_ms == 300000
        assert sample_config.max_iterations == 10
        assert sample_config.context_warn == 0.70
        assert sample_config.context_compact == 0.85
        assert sample_config.context_kill == 0.95

    def test_config_creation_override_values(self) -> None:
        """Test creating config with overridden values."""
        config = RalphPlanConfig(
            timeout_ms=600000,
            max_iterations=20,
            context_warn=0.60,
            context_compact=0.80,
            context_kill=0.90,
        )
        assert config.timeout_ms == 600000
        assert config.max_iterations == 20
        assert config.context_warn == 0.60
        assert config.context_compact == 0.80
        assert config.context_kill == 0.90

    def test_config_to_dict(self) -> None:
        """Test serializing config to dict."""
        config = RalphPlanConfig(timeout_ms=500000, max_iterations=15)
        d = config.to_dict()
        assert d["t"] == "config"
        assert d["timeout_ms"] == 500000
        assert d["max_iterations"] == 15
        assert d["context_warn"] == 0.70
        assert d["context_compact"] == 0.85
        assert d["context_kill"] == 0.95

    def test_config_to_jsonl(self) -> None:
        """Test serializing config to JSONL string."""
        config = RalphPlanConfig()
        jsonl = config.to_jsonl()
        parsed = json.loads(jsonl)
        assert parsed["t"] == "config"
        assert parsed["timeout_ms"] == 300000
        assert parsed["max_iterations"] == 10

    def test_config_from_dict(self) -> None:
        """Test deserializing config from dict."""
        d = {
            "timeout_ms": 400000,
            "max_iterations": 5,
            "context_warn": 0.65,
            "context_compact": 0.80,
            "context_kill": 0.92,
        }
        config = RalphPlanConfig.from_dict(d)
        assert config.timeout_ms == 400000
        assert config.max_iterations == 5
        assert config.context_warn == 0.65
        assert config.context_compact == 0.80
        assert config.context_kill == 0.92

    def test_config_from_dict_partial(self) -> None:
        """Test deserializing config with partial dict (uses defaults)."""
        d = {"timeout_ms": 600000}
        config = RalphPlanConfig.from_dict(d)
        assert config.timeout_ms == 600000
        assert config.max_iterations == 10
        assert config.context_warn == 0.70
        assert config.context_compact == 0.85
        assert config.context_kill == 0.95

    def test_config_from_dict_empty(self) -> None:
        """Test deserializing config from empty dict (all defaults)."""
        d: dict = {}
        config = RalphPlanConfig.from_dict(d)
        assert config.timeout_ms == 300000
        assert config.max_iterations == 10
        assert config.context_warn == 0.70
        assert config.context_compact == 0.85
        assert config.context_kill == 0.95

    def test_config_from_jsonl(self) -> None:
        """Test from_jsonl is alias for from_dict."""
        d = {"timeout_ms": 250000, "max_iterations": 8}
        config = RalphPlanConfig.from_jsonl(d)
        assert config.timeout_ms == 250000
        assert config.max_iterations == 8

    def test_config_roundtrip(self) -> None:
        """Test serialization roundtrip preserves data."""
        original = RalphPlanConfig(
            timeout_ms=450000,
            max_iterations=12,
            context_warn=0.68,
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
