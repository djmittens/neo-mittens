"""E2E tests for backwards compatibility with existing Ralph data."""

import json
import os
import shutil
from pathlib import Path

import pytest


def get_repo_root() -> Path:
    """Find the repository root by looking for ralph/ directory."""
    current = Path.cwd()
    while current != current.parent:
        if (current / "ralph" / "plan.jsonl").exists():
            return current
        if (current / "ralph" / "PROMPT_build.md").exists():
            return current
        current = current.parent
    return Path.cwd().parent


class TestReadsExistingPlanJsonl:
    """Tests for loading existing plan.jsonl files."""

    def test_reads_existing_plan_jsonl(self, tmp_path):
        """Test that the new state module can read existing plan.jsonl from ralph/ directory."""
        from ralph.state import load_state

        repo_root = get_repo_root()
        plan_file = repo_root / "ralph" / "plan.jsonl"
        if not plan_file.exists():
            pytest.skip("ralph/plan.jsonl not found in repo")

        state = load_state(plan_file)

        assert state is not None
        assert hasattr(state, "tasks")
        assert hasattr(state, "issues")
        assert hasattr(state, "tombstones")
        assert hasattr(state, "config")

    def test_reads_sample_plan_jsonl_copy(self, tmp_path):
        """Test loading a copied plan.jsonl into tmp directory."""
        from ralph.state import load_state

        repo_root = get_repo_root()
        plan_file = repo_root / "ralph" / "plan.jsonl"
        if not plan_file.exists():
            pytest.skip("ralph/plan.jsonl not found in repo")

        tmp_plan = tmp_path / "plan.jsonl"
        shutil.copy(plan_file, tmp_plan)

        state = load_state(tmp_plan)

        assert state is not None
        assert isinstance(state.tasks, list)
        assert isinstance(state.issues, list)
        assert isinstance(state.tombstones, dict)
        assert "accepted" in state.tombstones
        assert "rejected" in state.tombstones

    def test_parses_task_fields_correctly(self, tmp_path):
        """Test that tasks from plan.jsonl have expected fields parsed."""
        from ralph.state import load_state

        repo_root = get_repo_root()
        plan_file = repo_root / "ralph" / "plan.jsonl"
        if not plan_file.exists():
            pytest.skip("ralph/plan.jsonl not found in repo")

        state = load_state(plan_file)

        if state.tasks:
            task = state.tasks[0]
            assert hasattr(task, "id")
            assert hasattr(task, "name")
            assert hasattr(task, "spec")
            assert hasattr(task, "status")

    def test_parses_tombstones_correctly(self, tmp_path):
        """Test that tombstones are parsed correctly."""
        from ralph.state import load_state

        repo_root = get_repo_root()
        plan_file = repo_root / "ralph" / "plan.jsonl"
        if not plan_file.exists():
            pytest.skip("ralph/plan.jsonl not found in repo")

        state = load_state(plan_file)

        all_tombstones = state.tombstones["accepted"] + state.tombstones["rejected"]
        if all_tombstones:
            tombstone = all_tombstones[0]
            assert hasattr(tombstone, "id")
            assert hasattr(tombstone, "name")

    def test_synthetic_plan_jsonl(self, tmp_path):
        """Test loading a synthetic plan.jsonl with known content."""
        from ralph.state import load_state

        plan_content = [
            {"t": "config", "timeout_ms": 300000, "max_iterations": 10},
            {"t": "spec", "spec": "test-spec.md"},
            {
                "t": "task",
                "id": "t-abc123",
                "spec": "test-spec.md",
                "name": "Test task",
                "s": "p",
                "notes": "Test notes here",
                "accept": "test passes",
                "deps": [],
                "priority": "high",
            },
        ]

        plan_file = tmp_path / "plan.jsonl"
        plan_file.write_text("\n".join(json.dumps(line) for line in plan_content))

        state = load_state(plan_file)

        assert state.spec == "test-spec.md"
        assert len(state.tasks) == 1
        assert state.tasks[0].id == "t-abc123"
        assert state.tasks[0].name == "Test task"
        assert state.tasks[0].priority == "high"


class TestLoadsExistingPrompts:
    """Tests for loading existing PROMPT_*.md files."""

    def test_loads_existing_prompts(self, tmp_path):
        """Test that PROMPT_*.md files are loadable from ralph/ directory."""
        from ralph.prompts import load_prompt

        repo_root = get_repo_root()
        ralph_dir = repo_root / "ralph"
        if not ralph_dir.exists():
            pytest.skip("ralph/ directory not found")

        stages = ["plan", "build", "verify", "investigate", "decompose"]
        loaded_count = 0

        for stage in stages:
            prompt_file = ralph_dir / f"PROMPT_{stage}.md"
            if prompt_file.exists():
                prompt = load_prompt(stage, ralph_dir)
                assert prompt is not None
                assert len(prompt) > 0
                loaded_count += 1

        assert loaded_count > 0, "No PROMPT_*.md files found in ralph/"

    def test_prompt_content_is_string(self, tmp_path):
        """Test that loaded prompts return strings."""
        from ralph.prompts import load_prompt

        repo_root = get_repo_root()
        ralph_dir = repo_root / "ralph"
        prompt_file = ralph_dir / "PROMPT_build.md"
        if not prompt_file.exists():
            pytest.skip("PROMPT_build.md not found")

        prompt = load_prompt("build", ralph_dir)
        assert isinstance(prompt, str)

    def test_prompt_from_copied_directory(self, tmp_path):
        """Test loading prompts from a copied directory structure."""
        from ralph.prompts import load_prompt

        repo_root = get_repo_root()
        ralph_dir = repo_root / "ralph"
        prompt_file = ralph_dir / "PROMPT_build.md"
        if not prompt_file.exists():
            pytest.skip("PROMPT_build.md not found")

        tmp_ralph = tmp_path / "ralph"
        tmp_ralph.mkdir()
        shutil.copy(prompt_file, tmp_ralph / "PROMPT_build.md")

        prompt = load_prompt("build", tmp_ralph)
        assert prompt is not None
        assert len(prompt) > 0

    def test_missing_prompt_raises_error(self, tmp_path):
        """Test that missing prompt file raises FileNotFoundError."""
        from ralph.prompts import load_prompt

        with pytest.raises(FileNotFoundError):
            load_prompt("nonexistent_stage", tmp_path)


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
