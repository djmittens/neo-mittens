"""Unit tests for ralph.config module."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

from ralph.config import (
    GlobalConfig,
    get_global_config,
    reload_global_config,
    load_available_profiles,
    apply_profile,
)


class TestGlobalConfigDefaults:
    """Tests for GlobalConfig default values."""

    def test_global_config_defaults(self):
        """Test GlobalConfig has correct default values."""
        config = GlobalConfig()
        assert config.model == ""
        assert config.model_build == ""
        assert config.context_window == 200_000
        assert config.context_warn_pct == 70
        assert config.context_compact_pct == 85
        assert config.context_kill_pct == 95
        assert config.stage_timeout_ms == 900_000
        assert config.iteration_timeout_ms == 900_000
        assert config.timeout_ms == 900_000
        assert config.max_failures == 3
        assert config.max_iterations == 50
        assert config.max_tokens == 0
        assert config.max_wall_time_s == 3600
        assert config.max_api_calls == 0
        assert config.max_issues_per_spec == 10
        assert config.max_decompose_depth == 3
        assert config.commit_prefix == "ralph:"
        assert config.recent_commits_display == 3
        assert config.art_style == "braille"
        assert config.dashboard_buffer_lines == 2000
        assert config.ralph_dir == "ralph"
        assert config.log_dir == "/tmp/ralph-logs"
        assert config.profile == "default"

    def test_global_config_custom_values(self):
        """Test GlobalConfig accepts custom values."""
        config = GlobalConfig(
            model="claude-3-opus",
            context_window=100_000,
            max_iterations=10,
            profile="custom",
        )
        assert config.model == "claude-3-opus"
        assert config.context_window == 100_000
        assert config.max_iterations == 10
        assert config.profile == "custom"


class TestLoadConfigFromToml:
    """Tests for loading config from TOML files."""

    def test_load_config_from_toml(self, tmp_path, monkeypatch):
        """Test loading config from a TOML file."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(
            """
model = "claude-3-sonnet"
model_build = "claude-3-haiku"
context_window = 150000
max_iterations = 25
"""
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        config = GlobalConfig.load()
        assert config.model == "claude-3-sonnet"
        assert config.model_build == "claude-3-haiku"
        assert config.context_window == 150000
        assert config.max_iterations == 25

    def test_load_config_with_default_section(self, tmp_path, monkeypatch):
        """Test loading config with [default] section (backward compat)."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(
            """
[default]
model = "claude-default"
timeout_ms = 600000
"""
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        config = GlobalConfig.load()
        assert config.model == "claude-default"
        assert config.timeout_ms == 600000

    def test_load_config_top_level_overrides_default(self, tmp_path, monkeypatch):
        """Test top-level keys override [default] section."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(
            """
model = "top-level-model"

[default]
model = "default-model"
max_iterations = 30
"""
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        config = GlobalConfig.load()
        assert config.model == "default-model"
        assert config.max_iterations == 30


class TestProfileSelection:
    """Tests for profile selection via RALPH_PROFILE."""

    def test_profile_selection(self, tmp_path, monkeypatch):
        """Test profile selection via RALPH_PROFILE env var."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(
            """
model = "base-model"
max_iterations = 50

[profiles.budget]
model = "budget-model"
max_iterations = 10

[profiles.balanced]
model = "balanced-model"
max_iterations = 25
"""
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("RALPH_PROFILE", "budget")
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        config = GlobalConfig.load()
        assert config.model == "budget-model"
        assert config.max_iterations == 10
        assert config.profile == "budget"

    def test_profile_overlays_base_config(self, tmp_path, monkeypatch):
        """Test profile overlays but doesn't replace all base config."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(
            """
model = "base-model"
context_window = 180000
max_iterations = 50

[profiles.minimal]
max_iterations = 5
"""
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("RALPH_PROFILE", "minimal")
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        config = GlobalConfig.load()
        assert config.model == "base-model"
        assert config.context_window == 180000
        assert config.max_iterations == 5
        assert config.profile == "minimal"

    def test_nonexistent_profile_ignored(self, tmp_path, monkeypatch):
        """Test nonexistent profile is ignored."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(
            """
model = "base-model"
max_iterations = 50
"""
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("RALPH_PROFILE", "nonexistent")
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        config = GlobalConfig.load()
        assert config.model == "base-model"
        assert config.max_iterations == 50
        assert config.profile == "default"

    def test_ralph_art_style_env_var(self, tmp_path, monkeypatch):
        """Test RALPH_ART_STYLE env var overrides config."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(
            """
art_style = "blocks"
"""
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("RALPH_ART_STYLE", "minimal")
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        config = GlobalConfig.load()
        assert config.art_style == "minimal"


class TestMissingConfigFile:
    """Tests for handling missing config file."""

    def test_missing_config_file(self, tmp_path, monkeypatch):
        """Test missing config file returns defaults."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        config = GlobalConfig.load()
        assert config.model == ""
        assert config.context_window == 200_000
        assert config.max_iterations == 50
        assert config.profile == "default"

    def test_empty_config_file(self, tmp_path, monkeypatch):
        """Test empty config file returns defaults."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text("")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        config = GlobalConfig.load()
        assert config.model == ""
        assert config.context_window == 200_000

    def test_invalid_toml_file(self, tmp_path, monkeypatch):
        """Test invalid TOML file returns defaults."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text("this is not valid toml [[[")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        config = GlobalConfig.load()
        assert config.model == ""
        assert config.context_window == 200_000

    def test_invalid_field_ignored(self, tmp_path, monkeypatch):
        """Test invalid fields in config are ignored."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(
            """
model = "valid-model"
invalid_field = "should be ignored"
another_invalid = 12345
"""
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        config = GlobalConfig.load()
        assert config.model == "valid-model"
        assert not hasattr(config, "invalid_field")
        assert not hasattr(config, "another_invalid")


class TestGlobalConfigSingleton:
    """Tests for get_global_config singleton behavior."""

    def test_get_global_config_returns_config(self, tmp_path, monkeypatch):
        """Test get_global_config returns a GlobalConfig instance."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        import ralph.config as config_module

        config_module._global_config = None
        config = get_global_config()
        assert isinstance(config, GlobalConfig)

    def test_reload_global_config(self, tmp_path, monkeypatch):
        """Test reload_global_config reloads config from file."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('model = "first-model"')
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        import ralph.config as config_module

        config_module._global_config = None
        config1 = get_global_config()
        assert config1.model == "first-model"
        config_file.write_text('model = "second-model"')
        config2 = reload_global_config()
        assert config2.model == "second-model"


class TestLoadAvailableProfiles:
    """Tests for load_available_profiles function."""

    def test_load_available_profiles(self, tmp_path, monkeypatch):
        """Test loading available profiles from config."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(
            """
[profiles.budget]
model = "budget-model"

[profiles.balanced]
model = "balanced-model"
"""
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        profiles = load_available_profiles()
        assert "budget" in profiles
        assert "balanced" in profiles
        assert profiles["budget"]["model"] == "budget-model"
        assert profiles["balanced"]["model"] == "balanced-model"

    def test_load_available_profiles_no_config(self, tmp_path, monkeypatch):
        """Test load_available_profiles with no config file."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        profiles = load_available_profiles()
        assert profiles == {}

    def test_load_available_profiles_no_profiles_section(self, tmp_path, monkeypatch):
        """Test load_available_profiles when no profiles section exists."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('model = "some-model"')
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        profiles = load_available_profiles()
        assert profiles == {}


class TestApplyProfile:
    """Tests for apply_profile function."""

    def test_apply_profile(self, tmp_path, monkeypatch):
        """Test apply_profile sets env var and reloads config."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(
            """
model = "base-model"

[profiles.test_profile]
model = "test-model"
"""
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        import ralph.config as config_module

        config_module._global_config = None
        apply_profile("test_profile")
        assert os.environ.get("RALPH_PROFILE") == "test_profile"
        config = get_global_config()
        assert config.model == "test-model"
        assert config.profile == "test_profile"


class TestIsLocalModel:
    """Tests for GlobalConfig.is_local_model method."""

    def test_vllm_prefix_is_local(self):
        """Test vllm: prefix detected as local."""
        cfg = GlobalConfig()
        assert cfg.is_local_model("vllm:devstral-small-2") is True

    def test_ollama_prefix_is_local(self):
        """Test ollama: prefix detected as local."""
        cfg = GlobalConfig()
        assert cfg.is_local_model("ollama:llama3") is True

    def test_local_prefix_is_local(self):
        """Test local: prefix detected as local."""
        cfg = GlobalConfig()
        assert cfg.is_local_model("local:my-model") is True

    def test_lmstudio_prefix_is_local(self):
        """Test lmstudio: prefix detected as local."""
        cfg = GlobalConfig()
        assert cfg.is_local_model("lmstudio:my-model") is True

    def test_localhost_url_is_local(self):
        """Test model with localhost in name detected as local."""
        cfg = GlobalConfig()
        assert cfg.is_local_model("http://localhost:8000/v1") is True

    def test_loopback_ip_is_local(self):
        """Test model with 127.0.0.1 detected as local."""
        cfg = GlobalConfig()
        assert cfg.is_local_model("http://127.0.0.1:8000") is True

    def test_anthropic_model_not_local(self):
        """Test Anthropic cloud model is not local."""
        cfg = GlobalConfig()
        assert cfg.is_local_model("anthropic:claude-opus-4-20250514") is False

    def test_empty_string_not_local(self):
        """Test empty string is not local."""
        cfg = GlobalConfig()
        assert cfg.is_local_model("") is False

    def test_case_insensitive(self):
        """Test detection is case-insensitive."""
        cfg = GlobalConfig()
        assert cfg.is_local_model("VLLM:Model") is True
        assert cfg.is_local_model("OLLAMA:Model") is True


class TestIsStageLocal:
    """Tests for GlobalConfig.is_stage_local method."""

    def test_stage_with_local_model(self):
        """Test stage using local model is detected."""
        cfg = GlobalConfig(model="vllm:devstral")
        assert cfg.is_stage_local("build") is True

    def test_stage_with_cloud_model(self):
        """Test stage using cloud model is not local."""
        cfg = GlobalConfig(model="anthropic:claude-opus-4-20250514")
        assert cfg.is_stage_local("build") is False

    def test_stage_override_local(self):
        """Test per-stage override to local model."""
        cfg = GlobalConfig(
            model="anthropic:claude-opus-4-20250514",
            model_build="vllm:devstral",
        )
        assert cfg.is_stage_local("build") is True
        assert cfg.is_stage_local("verify") is False

    def test_stage_override_cloud(self):
        """Test per-stage override to cloud model."""
        cfg = GlobalConfig(
            model="vllm:devstral",
            model_verify="anthropic:claude-sonnet-4-20250514",
        )
        assert cfg.is_stage_local("build") is True
        assert cfg.is_stage_local("verify") is False


class TestGuardConfigFields:
    """Tests for new guard-related config fields."""

    def test_max_tokens_from_toml(self, tmp_path, monkeypatch):
        """Test max_tokens loaded from TOML."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text("max_tokens = 500000")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        cfg = GlobalConfig.load()
        assert cfg.max_tokens == 500000

    def test_max_wall_time_from_toml(self, tmp_path, monkeypatch):
        """Test max_wall_time_s loaded from TOML."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text("max_wall_time_s = 7200")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        cfg = GlobalConfig.load()
        assert cfg.max_wall_time_s == 7200

    def test_max_api_calls_from_toml(self, tmp_path, monkeypatch):
        """Test max_api_calls loaded from TOML."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text("max_api_calls = 100")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        cfg = GlobalConfig.load()
        assert cfg.max_api_calls == 100


class TestAgentForStage:
    """Tests for GlobalConfig.agent_for_stage method."""

    def test_no_agents_configured(self):
        """Test empty string when no agents configured."""
        cfg = GlobalConfig()
        assert cfg.agent_for_stage("build") == ""
        assert cfg.agent_for_stage("verify") == ""
        assert cfg.agent_for_stage("dedup") == ""

    def test_global_agent_fallback(self):
        """Test global agent used when no stage-specific override."""
        cfg = GlobalConfig(agent="ralph-default")
        assert cfg.agent_for_stage("build") == "ralph-default"
        assert cfg.agent_for_stage("verify") == "ralph-default"

    def test_stage_specific_agent(self):
        """Test stage-specific agent overrides global."""
        cfg = GlobalConfig(
            agent="ralph-default",
            agent_build="ralph-build",
            agent_verify="ralph-verify",
        )
        assert cfg.agent_for_stage("build") == "ralph-build"
        assert cfg.agent_for_stage("verify") == "ralph-verify"
        # investigate falls back to global
        assert cfg.agent_for_stage("investigate") == "ralph-default"

    def test_dedup_agent(self):
        """Test dedup stage gets its own agent."""
        cfg = GlobalConfig(agent_dedup="ralph-dedup")
        assert cfg.agent_for_stage("dedup") == "ralph-dedup"
        # Other stages get empty (no global fallback)
        assert cfg.agent_for_stage("build") == ""

    def test_all_stages_configured(self):
        """Test all stages with individual agents."""
        cfg = GlobalConfig(
            agent_build="ralph-build",
            agent_verify="ralph-verify",
            agent_investigate="ralph-investigate",
            agent_decompose="ralph-decompose",
            agent_plan="ralph-plan",
            agent_dedup="ralph-dedup",
        )
        assert cfg.agent_for_stage("build") == "ralph-build"
        assert cfg.agent_for_stage("verify") == "ralph-verify"
        assert cfg.agent_for_stage("investigate") == "ralph-investigate"
        assert cfg.agent_for_stage("decompose") == "ralph-decompose"
        assert cfg.agent_for_stage("plan") == "ralph-plan"
        assert cfg.agent_for_stage("dedup") == "ralph-dedup"

    def test_agent_from_toml(self, tmp_path, monkeypatch):
        """Test agent config loaded from TOML file."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text(
            'agent_build = "ralph-build"\n'
            'agent_dedup = "ralph-dedup"\n'
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        cfg = GlobalConfig.load()
        assert cfg.agent_for_stage("build") == "ralph-build"
        assert cfg.agent_for_stage("dedup") == "ralph-dedup"
        assert cfg.agent_for_stage("verify") == ""

    def test_agent_from_profile(self, tmp_path, monkeypatch):
        """Test agent config from profile overlay."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text(
            'agent_build = "base-build"\n\n'
            "[profiles.sandboxed]\n"
            'agent_build = "ralph-build"\n'
            'agent_verify = "ralph-verify"\n'
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("RALPH_PROFILE", "sandboxed")
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)
        cfg = GlobalConfig.load()
        assert cfg.agent_for_stage("build") == "ralph-build"
        assert cfg.agent_for_stage("verify") == "ralph-verify"

    def test_agent_defaults_empty(self):
        """Test all agent fields default to empty string."""
        cfg = GlobalConfig()
        assert cfg.agent == ""
        assert cfg.agent_build == ""
        assert cfg.agent_verify == ""
        assert cfg.agent_investigate == ""
        assert cfg.agent_decompose == ""
        assert cfg.agent_plan == ""
        assert cfg.agent_dedup == ""


class TestRepoConfigOverlay:
    """Tests for per-repo config.toml overlay."""

    def test_repo_config_overrides_global(self, tmp_path, monkeypatch):
        """Test per-repo config.toml overrides global settings."""
        # Global config
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text('format_command = "global-fmt"')
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)

        # Per-repo config
        repo_dir = tmp_path / "ralph"
        repo_dir.mkdir()
        (repo_dir / "config.toml").write_text('format_command = "make format"')

        cfg = GlobalConfig.load(repo_config=repo_dir / "config.toml")
        assert cfg.format_command == "make format"

    def test_repo_config_without_global(self, tmp_path, monkeypatch):
        """Test per-repo config works even without global config."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        # No global config.toml
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)

        repo_dir = tmp_path / "ralph"
        repo_dir.mkdir()
        (repo_dir / "config.toml").write_text('format_command = "make format"')

        cfg = GlobalConfig.load(repo_config=repo_dir / "config.toml")
        assert cfg.format_command == "make format"

    def test_missing_repo_config_is_ignored(self, tmp_path, monkeypatch):
        """Test missing per-repo config.toml is silently ignored."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text('format_command = "global-fmt"')
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)

        cfg = GlobalConfig.load(repo_config=tmp_path / "nonexistent" / "config.toml")
        assert cfg.format_command == "global-fmt"

    def test_repo_config_ignores_sections(self, tmp_path, monkeypatch):
        """Test per-repo config only applies scalar keys, not sections."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text("")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)

        repo_dir = tmp_path / "ralph"
        repo_dir.mkdir()
        (repo_dir / "config.toml").write_text(
            'format_command = "make format"\n\n'
            "[profiles.sneaky]\n"
            'model = "should-be-ignored"\n'
        )

        cfg = GlobalConfig.load(repo_config=repo_dir / "config.toml")
        assert cfg.format_command == "make format"
        # model should NOT be overridden by a section in repo config
        assert cfg.model == ""

    def test_repo_config_invalid_fields_ignored(self, tmp_path, monkeypatch):
        """Test per-repo config with unknown fields doesn't crash."""
        config_dir = tmp_path / ".config" / "ralph"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text("")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RALPH_PROFILE", raising=False)
        monkeypatch.delenv("RALPH_ART_STYLE", raising=False)

        repo_dir = tmp_path / "ralph"
        repo_dir.mkdir()
        (repo_dir / "config.toml").write_text(
            'format_command = "make format"\n'
            'bogus_field = "should be ignored"\n'
        )

        cfg = GlobalConfig.load(repo_config=repo_dir / "config.toml")
        assert cfg.format_command == "make format"
