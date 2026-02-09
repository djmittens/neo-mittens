"""Unit tests for ralph.state module.

Tests orchestration state management: stage transitions, batch tracking,
decompose state, and JSON roundtrip.

State is ephemeral — stored under /tmp keyed by a hash of the repo root.
Ticket data (tasks, issues, tombstones) is owned by tix — not by RalphState.
"""

import json
import pytest
from pathlib import Path

from ralph.state import RalphState, load_state, save_state, _state_path


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

    load_state reads from the ephemeral location under /tmp, and
    migrates from legacy .tix/ralph-state.json if present.
    """

    def test_load_state_missing_file(self, tmp_path):
        """Test loading state when no state file exists."""
        state = load_state(tmp_path)
        assert state.spec is None
        assert state.stage == "PLAN"

    def test_load_state_from_legacy_location(self, tmp_path):
        """Test loading state migrates from legacy .tix/ralph-state.json."""
        tix_dir = tmp_path / ".tix"
        tix_dir.mkdir()
        (tix_dir / "ralph-state.json").write_text(
            json.dumps({"spec": "my-spec.md", "stage": "BUILD"})
        )
        state = load_state(tmp_path)
        assert state.spec == "my-spec.md"
        assert state.stage == "BUILD"
        # Legacy file should be cleaned up after migration
        assert not (tix_dir / "ralph-state.json").exists()
        # Ephemeral file should exist now
        assert _state_path(tmp_path).exists()

    def test_load_state_from_ephemeral_location(self, tmp_path):
        """Test loading state from ephemeral /tmp location."""
        # Save first to create the ephemeral file
        state = RalphState(spec="eph-spec.md", stage="VERIFY")
        save_state(state, tmp_path)
        # Load it back
        loaded = load_state(tmp_path)
        assert loaded.spec == "eph-spec.md"
        assert loaded.stage == "VERIFY"

    def test_load_state_empty_legacy_file(self, tmp_path):
        """Test loading state from empty legacy file."""
        tix_dir = tmp_path / ".tix"
        tix_dir.mkdir()
        (tix_dir / "ralph-state.json").write_text("")
        state = load_state(tmp_path)
        assert state.spec is None

    def test_load_state_with_stage(self, tmp_path):
        """Test loading state with stage and batch fields."""
        # Use save/load roundtrip
        original = RalphState(spec="s.md", stage="VERIFY")
        original.batch_items = ["t-1"]
        original.batch_attempt = 2
        save_state(original, tmp_path)
        state = load_state(tmp_path)
        assert state.stage == "VERIFY"
        assert state.batch_items == ["t-1"]
        assert state.batch_attempt == 2

    def test_load_state_with_decompose_state(self, tmp_path):
        """Test loading state with decompose fields."""
        original = RalphState(spec="s.md", stage="DECOMPOSE")
        original.decompose_target = "t-42"
        original.decompose_reason = "timeout"
        original.decompose_log = "/tmp/log"
        save_state(original, tmp_path)
        state = load_state(tmp_path)
        assert state.stage == "DECOMPOSE"
        assert state.decompose_target == "t-42"
        assert state.decompose_reason == "timeout"
        assert state.decompose_log == "/tmp/log"

    def test_load_state_rescue_migrates_to_investigate(self, tmp_path):
        """Test that old RESCUE stage is migrated to INVESTIGATE."""
        # Write legacy file with RESCUE stage
        tix_dir = tmp_path / ".tix"
        tix_dir.mkdir()
        (tix_dir / "ralph-state.json").write_text(
            json.dumps({"stage": "RESCUE"})
        )
        state = load_state(tmp_path)
        assert state.stage == "INVESTIGATE"


class TestSaveState:
    """Tests for save_state function.

    save_state writes to ephemeral location under /tmp.
    """

    def test_save_state_with_spec(self, tmp_path):
        """Test saving state with spec."""
        state = RalphState(spec="test-spec.md")
        save_state(state, tmp_path)
        path = _state_path(tmp_path)
        content = path.read_text()
        assert '"spec": "test-spec.md"' in content

    def test_save_state_empty(self, tmp_path):
        """Test saving empty state writes stage."""
        state = RalphState()
        save_state(state, tmp_path)
        path = _state_path(tmp_path)
        content = path.read_text()
        assert '"stage": "PLAN"' in content

    def test_save_state_creates_parent_dir(self, tmp_path):
        """Test that save_state creates parent directory if missing."""
        state = RalphState(spec="s.md")
        save_state(state, tmp_path)
        assert _state_path(tmp_path).exists()

    def test_save_state_with_decompose_fields(self, tmp_path):
        """Test saving state with decompose fields."""
        state = RalphState(spec="s.md", stage="DECOMPOSE")
        state.decompose_target = "t-42"
        state.decompose_reason = "timeout"
        state.decompose_log = "/tmp/log"
        save_state(state, tmp_path)
        content = _state_path(tmp_path).read_text()
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
        content = _state_path(tmp_path).read_text()
        assert "t-1" in content
        assert "t-2" in content
        assert "t-0" in content
        assert '"batch_attempt": 2' in content

    def test_save_state_not_in_repo_tree(self, tmp_path):
        """Test that state file is NOT written to .tix/ in the repo."""
        state = RalphState(spec="s.md")
        save_state(state, tmp_path)
        assert not (tmp_path / ".tix" / "ralph-state.json").exists()

    def test_save_state_atomic_write(self, tmp_path):
        """Test that no .tmp file is left behind after save."""
        state = RalphState(spec="s.md")
        save_state(state, tmp_path)
        path = _state_path(tmp_path)
        assert path.exists()
        assert not path.with_suffix(".tmp").exists()


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


class TestStatePath:
    """Tests for _state_path and ephemeral storage."""

    def test_state_path_is_under_tmp(self, tmp_path):
        """Test state path is under /tmp, not in repo."""
        import tempfile
        path = _state_path(tmp_path)
        assert str(path).startswith(tempfile.gettempdir())
        assert ".tix" not in str(path)

    def test_state_path_is_deterministic(self, tmp_path):
        """Test same repo root always produces same state path."""
        path1 = _state_path(tmp_path)
        path2 = _state_path(tmp_path)
        assert path1 == path2

    def test_different_repos_get_different_paths(self, tmp_path):
        """Test different repo roots get different state paths."""
        repo_a = tmp_path / "repo-a"
        repo_b = tmp_path / "repo-b"
        repo_a.mkdir()
        repo_b.mkdir()
        assert _state_path(repo_a) != _state_path(repo_b)
