"""Unit tests for ralph.state module.

Tests orchestration state management: stage transitions, batch tracking,
spec/config roundtrip, and ticket line preservation.

Ticket data (tasks, issues, tombstones) is owned by tix — not by RalphState.
"""

import json
import pytest
from pathlib import Path

from ralph.state import RalphState, load_state, save_state
from ralph.models import RalphPlanConfig


class TestRalphState:
    """Tests for RalphState class."""

    def test_state_creation_empty(self):
        """Test creating an empty RalphState."""
        state = RalphState()
        assert state.config is None
        assert state.spec is None
        assert state.stage == "PLAN"
        assert state.decompose_target is None
        assert state.decompose_reason is None
        assert state.decompose_log is None
        assert state.batch_items == []
        assert state.batch_completed == []
        assert state.batch_attempt == 0

    def test_state_transition_to_decompose(self):
        """Test transition_to_decompose sets fields correctly."""
        state = RalphState(stage="BUILD")
        state.transition_to_decompose("t-1", "timeout", "/tmp/log")
        assert state.stage == "DECOMPOSE"
        assert state.decompose_target == "t-1"
        assert state.decompose_reason == "timeout"
        assert state.decompose_log == "/tmp/log"

    def test_state_transition_to_investigate(self):
        """Test transition_to_investigate clears decompose and batch state."""
        state = RalphState(stage="VERIFY")
        state.decompose_target = "t-1"
        state.batch_items = ["x"]
        state.transition_to_investigate()
        assert state.stage == "INVESTIGATE"
        assert state.decompose_target is None
        assert state.batch_items == []

    def test_state_transition_to_build(self):
        """Test transition_to_build clears decompose and batch state."""
        state = RalphState(stage="INVESTIGATE")
        state.transition_to_build()
        assert state.stage == "BUILD"
        assert state.decompose_target is None
        assert state.batch_items == []

    def test_state_transition_to_verify(self):
        """Test transition_to_verify clears decompose and batch state."""
        state = RalphState(stage="BUILD")
        state.transition_to_verify()
        assert state.stage == "VERIFY"

    def test_state_transition_to_complete(self):
        """Test transition_to_complete clears decompose and batch state."""
        state = RalphState(stage="VERIFY")
        state.transition_to_complete()
        assert state.stage == "COMPLETE"

    def test_get_stage(self):
        """Test get_stage returns current stage."""
        state = RalphState(stage="BUILD")
        assert state.get_stage() == "BUILD"


class TestBatchManagement:
    """Tests for RalphState batch management methods."""

    def test_get_next_batch_first_batch(self):
        """Test getting the first batch from items."""
        state = RalphState()
        batch = state.get_next_batch(["a", "b", "c", "d"], 2)
        assert batch == ["a", "b"]
        assert state.batch_items == ["a", "b"]
        assert state.batch_attempt == 1

    def test_get_next_batch_continues_current(self):
        """Test that pending batch items are returned again."""
        state = RalphState()
        state.batch_items = ["a", "b"]
        batch = state.get_next_batch(["a", "b", "c", "d"], 2)
        assert batch == ["a", "b"]

    def test_get_next_batch_advances(self):
        """Test advancing to next batch after completion."""
        state = RalphState()
        state.batch_items = ["a", "b"]
        state.batch_completed = ["a", "b"]
        batch = state.get_next_batch(["a", "b", "c", "d"], 2)
        assert batch == ["c", "d"]

    def test_get_next_batch_empty_when_done(self):
        """Test empty result when all items completed."""
        state = RalphState()
        state.batch_completed = ["a", "b"]
        batch = state.get_next_batch(["a", "b"], 2)
        assert batch == []

    def test_mark_batch_complete(self):
        """Test marking current batch complete."""
        state = RalphState()
        state.batch_items = ["a", "b"]
        state.batch_attempt = 1
        state.mark_batch_complete()
        assert state.batch_items == []
        assert state.batch_completed == ["a", "b"]
        assert state.batch_attempt == 0

    def test_mark_batch_failed_retries(self):
        """Test batch failure with retries available."""
        state = RalphState()
        state.batch_attempt = 1
        assert state.mark_batch_failed(max_retries=2) is True
        assert state.batch_attempt == 2

    def test_mark_batch_failed_exhausted(self):
        """Test batch failure when retries exhausted."""
        state = RalphState()
        state.batch_attempt = 2
        assert state.mark_batch_failed(max_retries=2) is False
        assert state.batch_attempt == 3

    def test_get_batch_progress(self):
        """Test batch progress reporting."""
        state = RalphState()
        state.batch_items = ["a"]
        state.batch_completed = ["b", "c"]
        state.batch_attempt = 1
        progress = state.get_batch_progress()
        assert progress == {
            "current_batch": ["a"],
            "completed_batches": 2,
            "attempt": 1,
        }


class TestLoadState:
    """Tests for load_state function."""

    def test_load_state_missing_file(self, tmp_path):
        """Test loading state from missing file."""
        plan_path = tmp_path / "plan.jsonl"
        state = load_state(plan_path)
        assert state.config is None
        assert state.spec is None
        assert state.stage == "PLAN"

    def test_load_state_empty_file(self, tmp_path):
        """Test loading state from empty file."""
        plan_path = tmp_path / "plan.jsonl"
        plan_path.write_text("")
        state = load_state(plan_path)
        assert state.config is None
        assert state.spec is None

    def test_load_state_with_spec(self, tmp_path):
        """Test loading state with spec record."""
        plan_path = tmp_path / "plan.jsonl"
        plan_path.write_text(json.dumps({"t": "spec", "spec": "my-spec.md"}))
        state = load_state(plan_path)
        assert state.spec == "my-spec.md"

    def test_load_state_with_config(self, tmp_path):
        """Test loading state with config record."""
        plan_path = tmp_path / "plan.jsonl"
        lines = [
            json.dumps({
                "t": "config",
                "timeout_ms": 600000,
                "max_iterations": 5,
            }),
        ]
        plan_path.write_text("\n".join(lines))
        state = load_state(plan_path)
        assert state.config is not None
        assert state.config.timeout_ms == 600000
        assert state.config.max_iterations == 5

    def test_load_state_with_stage(self, tmp_path):
        """Test loading state with stage record."""
        plan_path = tmp_path / "plan.jsonl"
        lines = [
            json.dumps({"t": "spec", "spec": "s.md"}),
            json.dumps({
                "t": "stage",
                "stage": "VERIFY",
                "batch_items": ["t-1"],
                "batch_attempt": 2,
            }),
        ]
        plan_path.write_text("\n".join(lines))
        state = load_state(plan_path)
        assert state.stage == "VERIFY"
        assert state.batch_items == ["t-1"]
        assert state.batch_attempt == 2

    def test_load_state_with_decompose_state(self, tmp_path):
        """Test loading state with decompose fields in stage record."""
        plan_path = tmp_path / "plan.jsonl"
        lines = [
            json.dumps({"t": "spec", "spec": "s.md"}),
            json.dumps({
                "t": "stage",
                "stage": "DECOMPOSE",
                "decompose_target": "t-42",
                "decompose_reason": "timeout",
                "decompose_log": "/tmp/log",
            }),
        ]
        plan_path.write_text("\n".join(lines))
        state = load_state(plan_path)
        assert state.stage == "DECOMPOSE"
        assert state.decompose_target == "t-42"
        assert state.decompose_reason == "timeout"
        assert state.decompose_log == "/tmp/log"

    def test_load_state_ignores_ticket_records(self, tmp_path):
        """Test that load_state ignores task/issue/accept/reject records."""
        plan_path = tmp_path / "plan.jsonl"
        lines = [
            json.dumps({"t": "spec", "spec": "s.md"}),
            json.dumps({"t": "task", "id": "t-1", "name": "X", "spec": "s.md", "s": "p"}),
            json.dumps({"t": "issue", "id": "i-1", "desc": "Y", "spec": "s.md"}),
            json.dumps({"t": "accept", "id": "t-0", "done_at": "x", "reason": "ok"}),
            json.dumps({"t": "reject", "id": "t-2", "done_at": "y", "reason": "bad"}),
            json.dumps({"t": "stage", "stage": "BUILD"}),
        ]
        plan_path.write_text("\n".join(lines))
        state = load_state(plan_path)
        assert state.spec == "s.md"
        assert state.stage == "BUILD"
        # No ticket attributes
        assert not hasattr(state, "tasks")
        assert not hasattr(state, "issues")
        assert not hasattr(state, "tombstones")

    def test_load_state_ignores_blank_lines(self, tmp_path):
        """Test that blank lines in file are ignored."""
        plan_path = tmp_path / "plan.jsonl"
        content = '{"t": "spec", "spec": "s.md"}\n\n\n{"t": "stage", "stage": "BUILD"}\n'
        plan_path.write_text(content)
        state = load_state(plan_path)
        assert state.spec == "s.md"
        assert state.stage == "BUILD"

    def test_load_state_rescue_migrates_to_investigate(self, tmp_path):
        """Test that old RESCUE stage is migrated to INVESTIGATE."""
        plan_path = tmp_path / "plan.jsonl"
        plan_path.write_text(json.dumps({"t": "stage", "stage": "RESCUE"}))
        state = load_state(plan_path)
        assert state.stage == "INVESTIGATE"


class TestSaveState:
    """Tests for save_state function."""

    def test_save_state_with_spec(self, tmp_path):
        """Test saving state with spec."""
        plan_path = tmp_path / "plan.jsonl"
        state = RalphState(spec="test-spec.md")
        save_state(state, plan_path)
        content = plan_path.read_text()
        assert '"spec": "test-spec.md"' in content

    def test_save_state_with_config(self, tmp_path):
        """Test saving state with config."""
        plan_path = tmp_path / "plan.jsonl"
        state = RalphState(config=RalphPlanConfig(timeout_ms=300000))
        save_state(state, plan_path)
        content = plan_path.read_text()
        assert '"t": "config"' in content
        assert "300000" in content

    def test_save_state_empty(self, tmp_path):
        """Test saving empty state still writes stage record."""
        plan_path = tmp_path / "plan.jsonl"
        state = RalphState()
        save_state(state, plan_path)
        content = plan_path.read_text()
        assert '"t": "stage"' in content
        assert '"stage": "PLAN"' in content

    def test_save_state_preserves_ticket_lines(self, tmp_path):
        """Test that save_state preserves ticket lines owned by tix."""
        plan_path = tmp_path / "plan.jsonl"
        # Pre-populate with ticket lines
        ticket_lines = [
            json.dumps({"t": "task", "id": "t-1", "name": "Task 1", "spec": "s.md", "s": "p"}),
            json.dumps({"t": "issue", "id": "i-1", "desc": "Issue 1", "spec": "s.md"}),
            json.dumps({"t": "accept", "id": "t-0", "done_at": "x", "reason": "ok"}),
            json.dumps({"t": "reject", "id": "t-2", "done_at": "y", "reason": "bad"}),
            json.dumps({"t": "spec", "spec": "old-spec.md"}),
            json.dumps({"t": "stage", "stage": "OLD"}),
        ]
        plan_path.write_text("\n".join(ticket_lines))

        # Save new orchestration state
        state = RalphState(spec="new-spec.md", stage="BUILD")
        save_state(state, plan_path)

        content = plan_path.read_text()
        lines = [l for l in content.strip().split("\n") if l.strip()]

        # Orchestration lines rewritten
        assert any('"spec": "new-spec.md"' in l for l in lines)
        assert any('"stage": "BUILD"' in l for l in lines)
        # Old orchestration lines NOT present
        assert not any('"spec": "old-spec.md"' in l for l in lines)
        assert not any('"stage": "OLD"' in l for l in lines)
        # Ticket lines preserved
        assert any('"t": "task"' in l and "t-1" in l for l in lines)
        assert any('"t": "issue"' in l and "i-1" in l for l in lines)
        assert any('"t": "accept"' in l and "t-0" in l for l in lines)
        assert any('"t": "reject"' in l and "t-2" in l for l in lines)

    def test_save_state_with_decompose_fields(self, tmp_path):
        """Test saving state with decompose fields."""
        plan_path = tmp_path / "plan.jsonl"
        state = RalphState(spec="s.md", stage="DECOMPOSE")
        state.decompose_target = "t-42"
        state.decompose_reason = "timeout"
        state.decompose_log = "/tmp/log"
        save_state(state, plan_path)
        content = plan_path.read_text()
        assert "t-42" in content
        assert "timeout" in content
        assert "/tmp/log" in content

    def test_save_state_with_batch_fields(self, tmp_path):
        """Test saving state with batch tracking fields."""
        plan_path = tmp_path / "plan.jsonl"
        state = RalphState(spec="s.md", stage="VERIFY")
        state.batch_items = ["t-1", "t-2"]
        state.batch_completed = ["t-0"]
        state.batch_attempt = 2
        save_state(state, plan_path)
        content = plan_path.read_text()
        assert "t-1" in content
        assert "t-2" in content
        assert "t-0" in content
        assert '"batch_attempt": 2' in content


class TestStateRoundtrip:
    """Tests for state serialization roundtrip."""

    def test_orchestration_roundtrip(self, tmp_path):
        """Test full orchestration state save/load roundtrip."""
        plan_path = tmp_path / "plan.jsonl"
        original = RalphState(
            spec="roundtrip-spec.md",
            config=RalphPlanConfig(timeout_ms=450000, max_iterations=7),
            stage="VERIFY",
        )
        original.batch_items = ["t-1", "t-2"]
        original.batch_completed = ["t-0"]
        original.batch_attempt = 1
        save_state(original, plan_path)
        restored = load_state(plan_path)
        assert restored.spec == "roundtrip-spec.md"
        assert restored.config is not None
        assert restored.config.timeout_ms == 450000
        assert restored.config.max_iterations == 7
        assert restored.stage == "VERIFY"
        assert restored.batch_items == ["t-1", "t-2"]
        assert restored.batch_completed == ["t-0"]
        assert restored.batch_attempt == 1

    def test_decompose_roundtrip(self, tmp_path):
        """Test decompose state roundtrip."""
        plan_path = tmp_path / "plan.jsonl"
        original = RalphState(spec="s.md", stage="DECOMPOSE")
        original.decompose_target = "t-42"
        original.decompose_reason = "context_limit"
        original.decompose_log = "/tmp/decompose.log"
        save_state(original, plan_path)
        restored = load_state(plan_path)
        assert restored.stage == "DECOMPOSE"
        assert restored.decompose_target == "t-42"
        assert restored.decompose_reason == "context_limit"
        assert restored.decompose_log == "/tmp/decompose.log"

    def test_ticket_lines_survive_roundtrip(self, tmp_path):
        """Test that ticket lines in plan.jsonl survive save/load cycles."""
        plan_path = tmp_path / "plan.jsonl"
        # Write initial file with ticket data + orchestration
        initial_lines = [
            json.dumps({"t": "config", "timeout_ms": 300000, "max_iterations": 10}),
            json.dumps({"t": "spec", "spec": "s.md"}),
            json.dumps({"t": "stage", "stage": "BUILD"}),
            json.dumps({"t": "task", "id": "t-1", "name": "Task 1", "spec": "s.md", "s": "p"}),
            json.dumps({"t": "issue", "id": "i-1", "desc": "Issue 1", "spec": "s.md"}),
        ]
        plan_path.write_text("\n".join(initial_lines))

        # Load, modify orchestration, save
        state = load_state(plan_path)
        state.stage = "VERIFY"
        save_state(state, plan_path)

        # Verify ticket lines survived
        content = plan_path.read_text()
        lines = [l for l in content.strip().split("\n") if l.strip()]
        ticket_lines = [l for l in lines if '"t": "task"' in l or '"t": "issue"' in l]
        assert len(ticket_lines) == 2
        assert any("t-1" in l for l in ticket_lines)
        assert any("i-1" in l for l in ticket_lines)

        # Verify orchestration updated
        assert any('"stage": "VERIFY"' in l for l in lines)
