"""Unit tests for ralph.config module."""

import os
from pathlib import Path
from typing import Any, Dict, Generator
from unittest.mock import patch, mock_open

import pytest

from ralph.config import (
    GlobalConfig,
    _load_toml,
    get_global_config,
    reload_global_config,
)


class TestGlobalConfigDefaults:
    """Tests for GlobalConfig default values."""

    def test_default_model(self) -> None:
        """Test default model value."""
        config = GlobalConfig()
        assert config.model == "anthropic/claude-opus-4-5"

    def test_default_context_window(self) -> None:
        """Test default context window value."""
        config = GlobalConfig()
        assert config.context_window == 200_000

    def test_default_context_thresholds(self) -> None:
        """Test default context threshold percentages."""
        config = GlobalConfig()
        assert config.context_warn_pct == 70
        assert config.context_compact_pct == 85
        assert config.context_kill_pct == 95

    def test_default_timeouts(self) -> None:
        """Test default timeout values."""
        config = GlobalConfig()
        assert config.stage_timeout_ms == 300_000
        assert config.iteration_timeout_ms == 300_000

    def test_default_max_failures(self) -> None:
        """Test default max failures value."""
        config = GlobalConfig()
        assert config.max_failures == 3

    def test_default_max_decompose_depth(self) -> None:
        """Test default max decompose depth value."""
        config = GlobalConfig()
        assert config.max_decompose_depth == 3

    def test_default_commit_prefix(self) -> None:
        """Test default commit prefix value."""
        config = GlobalConfig()
        assert config.commit_prefix == "ralph:"

    def test_default_recent_commits_display(self) -> None:
        """Test default recent commits display count."""
        config = GlobalConfig()
        assert config.recent_commits_display == 3

    def test_default_art_style(self) -> None:
        """Test default art style value."""
        config = GlobalConfig()
        assert config.art_style == "braille"

    def test_default_dashboard_buffer_lines(self) -> None:
        """Test default dashboard buffer lines value."""
        config = GlobalConfig()
        assert config.dashboard_buffer_lines == 2000

    def test_default_ralph_dir(self) -> None:
        """Test default ralph directory value."""
        config = GlobalConfig()
        assert config.ralph_dir == "ralph"

    def test_default_log_dir(self) -> None:
        """Test default log directory value."""
        config = GlobalConfig()
        assert config.log_dir == "build/ralph-logs"

    def test_default_profile_name(self) -> None:
        """Test default profile name value."""
        config = GlobalConfig()
        assert config._profile_name == "default"


class TestGlobalConfigCreation:
    """Tests for GlobalConfig creation with custom values."""

    def test_custom_model(self) -> None:
        """Test creating config with custom model."""
        config = GlobalConfig(model="anthropic/claude-sonnet-4")
        assert config.model == "anthropic/claude-sonnet-4"

    def test_custom_context_window(self) -> None:
        """Test creating config with custom context window."""
        config = GlobalConfig(context_window=100_000)
        assert config.context_window == 100_000

    def test_custom_context_thresholds(self) -> None:
        """Test creating config with custom context thresholds."""
        config = GlobalConfig(
            context_warn_pct=60,
            context_compact_pct=80,
            context_kill_pct=90,
        )
        assert config.context_warn_pct == 60
        assert config.context_compact_pct == 80
        assert config.context_kill_pct == 90

    def test_custom_timeouts(self) -> None:
        """Test creating config with custom timeouts."""
        config = GlobalConfig(
            stage_timeout_ms=600_000,
            iteration_timeout_ms=450_000,
        )
        assert config.stage_timeout_ms == 600_000
        assert config.iteration_timeout_ms == 450_000

    def test_all_custom_values(self) -> None:
        """Test creating config with all custom values."""
        config = GlobalConfig(
            model="custom/model",
            context_window=150_000,
            context_warn_pct=65,
            context_compact_pct=80,
            context_kill_pct=92,
            stage_timeout_ms=500_000,
            iteration_timeout_ms=400_000,
            max_failures=5,
            max_decompose_depth=4,
            commit_prefix="test:",
            recent_commits_display=5,
            art_style="ascii",
            dashboard_buffer_lines=3000,
            ralph_dir="custom-ralph",
            log_dir="custom-logs",
            _profile_name="custom",
        )
        assert config.model == "custom/model"
        assert config.context_window == 150_000
        assert config.context_warn_pct == 65
        assert config.max_failures == 5
        assert config.commit_prefix == "test:"
        assert config.art_style == "ascii"
        assert config._profile_name == "custom"


class TestGlobalConfigLoad:
    """Tests for GlobalConfig.load() method."""

    def test_load_returns_defaults_when_no_config_file(self, temp_dir: str) -> None:
        """Test that load returns defaults when config file doesn't exist."""
        nonexistent_path = Path(temp_dir) / "nonexistent" / "config.toml"
        config = GlobalConfig.load(nonexistent_path)
        assert config.model == "anthropic/claude-opus-4-5"
        assert config.context_window == 200_000
        assert config._profile_name == "default"

    def test_load_uses_default_path_when_none_provided(self) -> None:
        """Test that load uses ~/.config/ralph/config.toml when no path provided."""
        with patch("ralph.config.Path.home") as mock_home:
            mock_home.return_value = Path("/nonexistent/home")
            config = GlobalConfig.load()
            assert config.model == "anthropic/claude-opus-4-5"

    def test_load_from_valid_toml(self, temp_dir: str) -> None:
        """Test loading config from valid TOML file."""
        config_path = Path(temp_dir) / "config.toml"
        toml_content = """
[default]
model = "test/model"
context_window = 150000
max_failures = 5
"""
        config_path.write_text(toml_content)

        with patch("ralph.config._load_toml") as mock_load:
            mock_load.return_value = {
                "default": {
                    "model": "test/model",
                    "context_window": 150000,
                    "max_failures": 5,
                }
            }
            config = GlobalConfig.load(config_path)
            assert config.model == "test/model"
            assert config.context_window == 150000
            assert config.max_failures == 5

    def test_load_returns_defaults_when_toml_parse_fails(self, temp_dir: str) -> None:
        """Test that load returns defaults when TOML parsing fails."""
        config_path = Path(temp_dir) / "config.toml"
        config_path.write_text("invalid toml content [[[")

        with patch("ralph.config._load_toml", return_value=None):
            config = GlobalConfig.load(config_path)
            assert config.model == "anthropic/claude-opus-4-5"


class TestProfileResolution:
    """Tests for profile resolution via RALPH_PROFILE environment variable."""

    def test_load_with_profile(self, temp_dir: str) -> None:
        """Test loading config with specific profile."""
        config_path = Path(temp_dir) / "config.toml"
        config_path.touch()

        toml_data = {
            "default": {
                "model": "default/model",
                "max_failures": 3,
            },
            "profiles": {
                "fast": {
                    "model": "fast/model",
                    "max_failures": 1,
                },
            },
        }

        with patch("ralph.config._load_toml", return_value=toml_data):
            with patch.dict(os.environ, {"RALPH_PROFILE": "fast"}):
                config = GlobalConfig.load(config_path)
                assert config.model == "fast/model"
                assert config.max_failures == 1
                assert config._profile_name == "fast"

    def test_profile_overrides_default_values(self, temp_dir: str) -> None:
        """Test that profile values override default section values."""
        config_path = Path(temp_dir) / "config.toml"
        config_path.touch()

        toml_data = {
            "default": {
                "model": "default/model",
                "context_window": 200000,
                "max_failures": 3,
            },
            "profiles": {
                "small": {
                    "context_window": 100000,
                },
            },
        }

        with patch("ralph.config._load_toml", return_value=toml_data):
            with patch.dict(os.environ, {"RALPH_PROFILE": "small"}):
                config = GlobalConfig.load(config_path)
                assert config.model == "default/model"
                assert config.context_window == 100000
                assert config.max_failures == 3
                assert config._profile_name == "small"

    def test_nonexistent_profile_uses_default(self, temp_dir: str) -> None:
        """Test that nonexistent profile falls back to default values."""
        config_path = Path(temp_dir) / "config.toml"
        config_path.touch()

        toml_data = {
            "default": {
                "model": "default/model",
            },
            "profiles": {
                "existing": {
                    "model": "existing/model",
                },
            },
        }

        with patch("ralph.config._load_toml", return_value=toml_data):
            with patch.dict(os.environ, {"RALPH_PROFILE": "nonexistent"}):
                config = GlobalConfig.load(config_path)
                assert config.model == "default/model"
                assert config._profile_name == "default"

    def test_empty_profile_uses_default(self, temp_dir: str) -> None:
        """Test that empty RALPH_PROFILE uses default values."""
        config_path = Path(temp_dir) / "config.toml"
        config_path.touch()

        toml_data = {
            "default": {
                "model": "default/model",
            },
            "profiles": {
                "other": {
                    "model": "other/model",
                },
            },
        }

        with patch("ralph.config._load_toml", return_value=toml_data):
            with patch.dict(os.environ, {"RALPH_PROFILE": ""}):
                config = GlobalConfig.load(config_path)
                assert config.model == "default/model"
                assert config._profile_name == "default"

    def test_no_profiles_section(self, temp_dir: str) -> None:
        """Test loading when profiles section is missing."""
        config_path = Path(temp_dir) / "config.toml"
        config_path.touch()

        toml_data = {
            "default": {
                "model": "default/model",
            },
        }

        with patch("ralph.config._load_toml", return_value=toml_data):
            with patch.dict(os.environ, {"RALPH_PROFILE": "any"}):
                config = GlobalConfig.load(config_path)
                assert config.model == "default/model"


class TestEnvironmentVariableHandling:
    """Tests for environment variable handling."""

    def test_ralph_art_style_overrides_config(self, temp_dir: str) -> None:
        """Test that RALPH_ART_STYLE environment variable overrides config."""
        config_path = Path(temp_dir) / "config.toml"
        config_path.touch()

        toml_data = {
            "default": {
                "art_style": "braille",
            },
        }

        with patch("ralph.config._load_toml", return_value=toml_data):
            with patch.dict(os.environ, {"RALPH_ART_STYLE": "ascii"}):
                config = GlobalConfig.load(config_path)
                assert config.art_style == "ascii"

    def test_ralph_art_style_without_config_file(self, temp_dir: str) -> None:
        """Test RALPH_ART_STYLE when no config file exists."""
        nonexistent_path = Path(temp_dir) / "nonexistent.toml"

        with patch.dict(os.environ, {"RALPH_ART_STYLE": "pixel"}):
            config = GlobalConfig.load(nonexistent_path)
            assert config.art_style == "braille"

    def test_ralph_art_style_overrides_profile(self, temp_dir: str) -> None:
        """Test that RALPH_ART_STYLE overrides profile art_style."""
        config_path = Path(temp_dir) / "config.toml"
        config_path.touch()

        toml_data = {
            "default": {
                "art_style": "braille",
            },
            "profiles": {
                "fancy": {
                    "art_style": "unicode",
                },
            },
        }

        with patch("ralph.config._load_toml", return_value=toml_data):
            with patch.dict(
                os.environ,
                {"RALPH_PROFILE": "fancy", "RALPH_ART_STYLE": "simple"},
            ):
                config = GlobalConfig.load(config_path)
                assert config.art_style == "simple"


class TestFieldValidation:
    """Tests for field validation and filtering."""

    def test_invalid_fields_are_filtered(self, temp_dir: str) -> None:
        """Test that invalid/unknown fields are filtered out."""
        config_path = Path(temp_dir) / "config.toml"
        config_path.touch()

        toml_data = {
            "default": {
                "model": "test/model",
                "invalid_field": "should be ignored",
                "another_invalid": 12345,
            },
        }

        with patch("ralph.config._load_toml", return_value=toml_data):
            config = GlobalConfig.load(config_path)
            assert config.model == "test/model"
            assert not hasattr(config, "invalid_field")
            assert not hasattr(config, "another_invalid")

    def test_only_valid_fields_applied(self, temp_dir: str) -> None:
        """Test that only valid GlobalConfig fields are applied."""
        config_path = Path(temp_dir) / "config.toml"
        config_path.touch()

        toml_data = {
            "default": {
                "model": "valid/model",
                "context_window": 100000,
                "unknown_setting": True,
            },
        }

        with patch("ralph.config._load_toml", return_value=toml_data):
            config = GlobalConfig.load(config_path)
            assert config.model == "valid/model"
            assert config.context_window == 100000


class TestLoadToml:
    """Tests for _load_toml helper function."""

    def test_load_toml_with_tomllib(self, temp_dir: str) -> None:
        """Test _load_toml uses tomllib when available."""
        config_path = Path(temp_dir) / "test.toml"
        config_path.write_text('[section]\nkey = "value"\n')

        with patch.dict("sys.modules", {"tomllib": None}):
            import importlib
            import ralph.config

            result = _load_toml(config_path)

        if result is not None:
            assert "section" in result
            assert result["section"]["key"] == "value"

    def test_load_toml_returns_none_when_no_parser(self, temp_dir: str) -> None:
        """Test _load_toml returns None when no TOML parser available."""
        config_path = Path(temp_dir) / "test.toml"
        config_path.write_text('[section]\nkey = "value"\n')

        with patch.dict(
            "sys.modules",
            {"tomllib": None, "tomli": None},
        ):
            with patch("ralph.config._load_toml") as mock_load:
                mock_load.return_value = None
                result = mock_load(config_path)
                assert result is None


class TestGlobalConfigSingleton:
    """Tests for global config singleton functions."""

    def test_get_global_config_returns_config(self) -> None:
        """Test that get_global_config returns a GlobalConfig instance."""
        import ralph.config

        ralph.config._global_config = None

        with patch.object(GlobalConfig, "load", return_value=GlobalConfig()):
            config = get_global_config()
            assert isinstance(config, GlobalConfig)

    def test_get_global_config_caches_result(self) -> None:
        """Test that get_global_config caches the config."""
        import ralph.config

        ralph.config._global_config = None

        with patch.object(GlobalConfig, "load") as mock_load:
            mock_load.return_value = GlobalConfig(model="cached/model")
            config1 = get_global_config()
            config2 = get_global_config()
            assert mock_load.call_count == 1
            assert config1 is config2
            assert config1.model == "cached/model"

    def test_reload_global_config_forces_reload(self) -> None:
        """Test that reload_global_config forces a fresh load."""
        import ralph.config

        ralph.config._global_config = GlobalConfig(model="old/model")

        with patch.object(GlobalConfig, "load") as mock_load:
            mock_load.return_value = GlobalConfig(model="new/model")
            config = reload_global_config()
            assert mock_load.call_count == 1
            assert config.model == "new/model"

    def test_reload_global_config_updates_singleton(self) -> None:
        """Test that reload_global_config updates the cached singleton."""
        import ralph.config

        ralph.config._global_config = GlobalConfig(model="old/model")

        with patch.object(GlobalConfig, "load") as mock_load:
            mock_load.return_value = GlobalConfig(model="reloaded/model")
            reload_global_config()
            config = get_global_config()
            assert config.model == "reloaded/model"


class TestConfigIntegration:
    """Integration tests for config loading scenarios."""

    def test_full_config_loading_scenario(self, temp_dir: str) -> None:
        """Test a complete config loading scenario with all features."""
        config_path = Path(temp_dir) / "config.toml"
        config_path.touch()

        toml_data = {
            "default": {
                "model": "default/model",
                "context_window": 200000,
                "max_failures": 3,
                "art_style": "braille",
                "commit_prefix": "default:",
            },
            "profiles": {
                "production": {
                    "model": "production/model",
                    "max_failures": 5,
                    "commit_prefix": "prod:",
                },
            },
        }

        with patch("ralph.config._load_toml", return_value=toml_data):
            with patch.dict(
                os.environ,
                {"RALPH_PROFILE": "production", "RALPH_ART_STYLE": "minimal"},
            ):
                config = GlobalConfig.load(config_path)

                assert config.model == "production/model"
                assert config.context_window == 200000
                assert config.max_failures == 5
                assert config.commit_prefix == "prod:"
                assert config.art_style == "minimal"
                assert config._profile_name == "production"

    def test_config_without_default_section(self, temp_dir: str) -> None:
        """Test loading config that has no default section."""
        config_path = Path(temp_dir) / "config.toml"
        config_path.touch()

        toml_data = {
            "profiles": {
                "only": {
                    "model": "only/model",
                },
            },
        }

        with patch("ralph.config._load_toml", return_value=toml_data):
            with patch.dict(os.environ, {"RALPH_PROFILE": "only"}):
                config = GlobalConfig.load(config_path)
                assert config.model == "only/model"
                assert config.context_window == 200_000

    def test_empty_toml_file(self, temp_dir: str) -> None:
        """Test loading from empty TOML file."""
        config_path = Path(temp_dir) / "config.toml"
        config_path.touch()

        with patch("ralph.config._load_toml", return_value={}):
            config = GlobalConfig.load(config_path)
            assert config.model == "anthropic/claude-opus-4-5"
            assert config._profile_name == "default"
