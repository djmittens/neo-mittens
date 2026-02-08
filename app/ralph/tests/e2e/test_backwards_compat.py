"""E2E tests for backwards compatibility with existing Ralph data.

Since state.py now stores orchestration in .tix/ralph-state.json,
these tests verify that:
1. load_state reads from .tix/ralph-state.json correctly
2. Prompts, config, and other subsystems still work
3. RalphState no longer has ticket data fields
"""

import json
import os
from pathlib import Path

import pytest


class TestReadsExistingState:
    """Tests for loading state from .tix/ralph-state.json."""

    def test_reads_state_from_tix_dir(self, tmp_path):
        """Test that load_state reads from .tix/ralph-state.json."""
        from ralph.state import load_state

        tix_dir = tmp_path / ".tix"
        tix_dir.mkdir()
        (tix_dir / "ralph-state.json").write_text(json.dumps({
            "spec": "test-spec.md",
            "stage": "BUILD",
        }))

        state = load_state(tmp_path)
        assert state.spec == "test-spec.md"
        assert state.stage == "BUILD"

    def test_empty_repo_returns_default_state(self, tmp_path):
        """Test that missing state file returns default RalphState."""
        from ralph.state import load_state

        state = load_state(tmp_path)
        assert state is not None
        assert state.stage == "PLAN"
        assert state.spec is None

    def test_does_not_have_ticket_fields(self, tmp_path):
        """Test that RalphState no longer has ticket attributes."""
        from ralph.state import RalphState

        state = RalphState()

        # These fields are now owned by tix
        assert not hasattr(state, "tasks")
        assert not hasattr(state, "issues")
        assert not hasattr(state, "tombstones")
        assert not hasattr(state, "current_task_id")
        assert not hasattr(state, "config")

    def test_state_roundtrip(self, tmp_path):
        """Test save/load roundtrip for orchestration state."""
        from ralph.state import RalphState, load_state, save_state

        original = RalphState(spec="my-spec.md", stage="VERIFY")
        original.batch_items = ["t-1"]
        original.batch_attempt = 2
        save_state(original, tmp_path)

        restored = load_state(tmp_path)
        assert restored.spec == "my-spec.md"
        assert restored.stage == "VERIFY"
        assert restored.batch_items == ["t-1"]
        assert restored.batch_attempt == 2


class TestLoadsPackagePrompts:
    """Tests for loading prompts from package-embedded defaults."""

    def test_loads_all_stages(self):
        """Test that all stage prompts are loadable from package defaults."""
        from ralph.prompts import load_prompt

        stages = ["plan", "build", "verify", "investigate", "decompose"]

        for stage in stages:
            prompt = load_prompt(stage)
            assert prompt is not None
            assert len(prompt) > 0

    def test_prompt_content_is_string(self):
        """Test that loaded prompts return strings."""
        from ralph.prompts import load_prompt

        prompt = load_prompt("build")
        assert isinstance(prompt, str)

    def test_prompts_contain_ralph_output(self):
        """Test all prompts contain the RALPH_OUTPUT marker."""
        from ralph.prompts import load_prompt

        stages = ["plan", "build", "verify", "investigate", "decompose"]
        for stage in stages:
            prompt = load_prompt(stage)
            assert "RALPH_OUTPUT" in prompt, f"{stage} missing RALPH_OUTPUT"

    def test_unknown_stage_raises_error(self):
        """Test that unknown stage name raises KeyError."""
        from ralph.prompts import load_prompt

        with pytest.raises(KeyError):
            load_prompt("nonexistent_stage")


class TestLoadsGlobalConfig:
    """Tests for loading global config from ~/.config/ralph/config.toml."""

    def test_loads_global_config(self):
        """Test that get_global_config() returns a valid config object."""
        from ralph.config import get_global_config, GlobalConfig

        config = get_global_config()

        assert config is not None
        assert isinstance(config, GlobalConfig)
        assert hasattr(config, "model")
        assert hasattr(config, "context_window")
        assert hasattr(config, "timeout_ms")
        assert hasattr(config, "max_iterations")

    def test_config_has_sensible_defaults(self):
        """Test that config has sensible default values."""
        from ralph.config import GlobalConfig

        config = GlobalConfig()

        assert config.context_window > 0
        assert config.timeout_ms > 0
        assert config.max_iterations > 0
        assert config.context_warn_pct > 0
        assert config.context_warn_pct < 100

    def test_config_file_loading_does_not_crash(self, tmp_path, monkeypatch):
        """Test that loading config from file does not crash even if malformed."""
        from ralph.config import GlobalConfig, reload_global_config

        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"

        config_file.write_text("invalid [ toml content")

        monkeypatch.setenv("HOME", str(tmp_path))

        config = GlobalConfig.load()

        assert config is not None
        assert isinstance(config, GlobalConfig)

    def test_loads_valid_toml_config(self, tmp_path, monkeypatch):
        """Test loading a valid TOML config file."""
        from ralph.config import GlobalConfig

        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"

        config_file.write_text("""
model = "claude-sonnet-4-20250514"
context_window = 150000
timeout_ms = 600000
max_iterations = 25
""")

        monkeypatch.setenv("HOME", str(tmp_path))

        config = GlobalConfig.load()

        assert config.model == "claude-sonnet-4-20250514"
        assert config.context_window == 150000
        assert config.timeout_ms == 600000
        assert config.max_iterations == 25

    def test_profile_loading(self, tmp_path, monkeypatch):
        """Test that profiles can be loaded via RALPH_PROFILE env var."""
        from ralph.config import GlobalConfig

        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"

        config_file.write_text("""
model = "default-model"

[profiles.budget]
model = "budget-model"
max_iterations = 5
""")

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("RALPH_PROFILE", "budget")

        config = GlobalConfig.load()

        assert config.model == "budget-model"
        assert config.max_iterations == 5
        assert config.profile == "budget"

    def test_existing_config_loads_without_error(self):
        """Test that existing ~/.config/ralph/config.toml loads without error."""
        from ralph.config import get_global_config, reload_global_config

        reload_global_config()
        config = get_global_config()

        assert config is not None
        assert config.context_window >= 0
