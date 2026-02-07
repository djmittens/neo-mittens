"""Unit tests for ralph.state module.

Tests orchestration state management: stage transitions, batch tracking,
decompose state, and JSON roundtrip.

State is stored in .tix/ralph-state.json — separate from tix's plan.jsonl.
Ticket data (tasks, issues, tombstones) is owned by tix — not by RalphState.
"""

import json
import pytest
from pathlib import Path

from ralph.state import RalphState, load_state, save_state


class TestRalphState:
    """Tests for RalphState class."""

    def test_state_creation_empty(self):
        """Test creating an empty RalphState."""
        state = RalphState()
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
    """Tests for load_state function.

    load_state reads from .tix/ralph-state.json within repo_root.
    """

    def test_load_state_missing_file(self, tmp_path):
        """Test loading state when .tix/ralph-state.json doesn't exist."""
        state = load_state(tmp_path)
        assert state.spec is None
        assert state.stage == "PLAN"

    def test_load_state_empty_file(self, tmp_path):
        """Test loading state from empty file."""
        tix_dir = tmp_path / ".tix"
        tix_dir.mkdir()
        (tix_dir / "ralph-state.json").write_text("")
        state = load_state(tmp_path)
        assert state.spec is None

    def test_load_state_with_spec(self, tmp_path):
        """Test loading state with spec field."""
        tix_dir = tmp_path / ".tix"
        tix_dir.mkdir()
        (tix_dir / "ralph-state.json").write_text(
            json.dumps({"spec": "my-spec.md", "stage": "BUILD"})
        )
        state = load_state(tmp_path)
        assert state.spec == "my-spec.md"
        assert state.stage == "BUILD"

    def test_load_state_with_stage(self, tmp_path):
        """Test loading state with stage and batch fields."""
        tix_dir = tmp_path / ".tix"
        tix_dir.mkdir()
        (tix_dir / "ralph-state.json").write_text(json.dumps({
            "spec": "s.md",
            "stage": "VERIFY",
            "batch_items": ["t-1"],
            "batch_attempt": 2,
        }))
        state = load_state(tmp_path)
        assert state.stage == "VERIFY"
        assert state.batch_items == ["t-1"]
        assert state.batch_attempt == 2

    def test_load_state_with_decompose_state(self, tmp_path):
        """Test loading state with decompose fields."""
        tix_dir = tmp_path / ".tix"
        tix_dir.mkdir()
        (tix_dir / "ralph-state.json").write_text(json.dumps({
            "spec": "s.md",
            "stage": "DECOMPOSE",
            "decompose_target": "t-42",
            "decompose_reason": "timeout",
            "decompose_log": "/tmp/log",
        }))
        state = load_state(tmp_path)
        assert state.stage == "DECOMPOSE"
        assert state.decompose_target == "t-42"
        assert state.decompose_reason == "timeout"
        assert state.decompose_log == "/tmp/log"

    def test_load_state_rescue_migrates_to_investigate(self, tmp_path):
        """Test that old RESCUE stage is migrated to INVESTIGATE."""
        tix_dir = tmp_path / ".tix"
        tix_dir.mkdir()
        (tix_dir / "ralph-state.json").write_text(
            json.dumps({"stage": "RESCUE"})
        )
        state = load_state(tmp_path)
        assert state.stage == "INVESTIGATE"


class TestSaveState:
    """Tests for save_state function.

    save_state writes to .tix/ralph-state.json within repo_root.
    """

    def test_save_state_with_spec(self, tmp_path):
        """Test saving state with spec."""
        state = RalphState(spec="test-spec.md")
        save_state(state, tmp_path)
        content = (tmp_path / ".tix" / "ralph-state.json").read_text()
        assert '"spec": "test-spec.md"' in content

    def test_save_state_empty(self, tmp_path):
        """Test saving empty state writes stage."""
        state = RalphState()
        save_state(state, tmp_path)
        content = (tmp_path / ".tix" / "ralph-state.json").read_text()
        assert '"stage": "PLAN"' in content

    def test_save_state_creates_tix_dir(self, tmp_path):
        """Test that save_state creates .tix/ directory if missing."""
        state = RalphState(spec="s.md")
        save_state(state, tmp_path)
        assert (tmp_path / ".tix" / "ralph-state.json").exists()

    def test_save_state_with_decompose_fields(self, tmp_path):
        """Test saving state with decompose fields."""
        state = RalphState(spec="s.md", stage="DECOMPOSE")
        state.decompose_target = "t-42"
        state.decompose_reason = "timeout"
        state.decompose_log = "/tmp/log"
        save_state(state, tmp_path)
        content = (tmp_path / ".tix" / "ralph-state.json").read_text()
        assert "t-42" in content
        assert "timeout" in content
        assert "/tmp/log" in content

    def test_save_state_with_batch_fields(self, tmp_path):
        """Test saving state with batch tracking fields."""
        state = RalphState(spec="s.md", stage="VERIFY")
        state.batch_items = ["t-1", "t-2"]
        state.batch_completed = ["t-0"]
        state.batch_attempt = 2
        save_state(state, tmp_path)
        content = (tmp_path / ".tix" / "ralph-state.json").read_text()
        assert "t-1" in content
        assert "t-2" in content
        assert "t-0" in content
        assert '"batch_attempt": 2' in content


class TestStateRoundtrip:
    """Tests for state serialization roundtrip."""

    def test_orchestration_roundtrip(self, tmp_path):
        """Test full orchestration state save/load roundtrip."""
        original = RalphState(
            spec="roundtrip-spec.md",
            stage="VERIFY",
        )
        original.batch_items = ["t-1", "t-2"]
        original.batch_completed = ["t-0"]
        original.batch_attempt = 1
        save_state(original, tmp_path)
        restored = load_state(tmp_path)
        assert restored.spec == "roundtrip-spec.md"
        assert restored.stage == "VERIFY"
        assert restored.batch_items == ["t-1", "t-2"]
        assert restored.batch_completed == ["t-0"]
        assert restored.batch_attempt == 1

    def test_decompose_roundtrip(self, tmp_path):
        """Test decompose state roundtrip."""
        original = RalphState(spec="s.md", stage="DECOMPOSE")
        original.decompose_target = "t-42"
        original.decompose_reason = "context_limit"
        original.decompose_log = "/tmp/decompose.log"
        save_state(original, tmp_path)
        restored = load_state(tmp_path)
        assert restored.stage == "DECOMPOSE"
        assert restored.decompose_target == "t-42"
        assert restored.decompose_reason == "context_limit"
        assert restored.decompose_log == "/tmp/decompose.log"
