"""Global Ralph configuration loaded from ~/.config/ralph/config.toml.

Complexity refactored with helper methods for better maintainability.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore


@dataclass
class GlobalConfig:
    """Global Ralph configuration loaded from ~/.config/ralph/config.toml.

    Model Selection
    ===============
    - model: Main model for reasoning stages (INVESTIGATE, VERIFY, DECOMPOSE, PLAN)
             Also used as fallback when BUILD struggles
    - model_build: Fast/cheap model for BUILD stage

    Config priority:
    1. Top-level keys (not in [default] or [profiles])
    2. [default] section (deprecated, for backward compat)
    3. RALPH_PROFILE overlay (if set via env var)
    """

    # Models - must be set via config.toml
    # model: fallback for any stage without a specific override
    model: str = ""
    # Per-stage model overrides (empty string = fall back to `model`)
    model_build: str = ""
    model_verify: str = ""
    model_investigate: str = ""
    model_decompose: str = ""
    model_plan: str = ""

    # Context limits
    context_window: int = 200_000
    context_warn_pct: int = 70
    context_compact_pct: int = 85
    context_kill_pct: int = 95

    # Timeouts (milliseconds)
    stage_timeout_ms: int = 900_000  # 15 minutes
    iteration_timeout_ms: int = 900_000  # 15 minutes
    timeout_ms: int = 900_000  # Alias for stage_timeout_ms

    # Circuit breaker
    max_failures: int = 3
    max_iterations: int = 50

    # Decomposition
    max_decompose_depth: int = 3

    # Pattern detection
    max_retries_per_task: int = 3  # Escalate to issue after N rejections
    issue_similarity_threshold: float = 0.8  # Jaccard token overlap for fuzzy dedup

    # Bounded fork-join limits
    verify_batch_size: int = 5  # Max tasks to verify in one batch
    investigate_batch_size: int = 5  # Max issues to investigate in one batch

    # Loop detection - abort if stuck in repetitive patterns
    loop_detection_threshold: int = 3  # Abort after N identical stage outputs
    max_identical_tool_calls: int = 5  # Abort after N identical tool calls in a stage

    # Progress tracking
    progress_check_interval: int = 600  # Warn if no progress in N seconds (0 = disabled)

    # Session logging
    emit_session_summary: bool = True  # Write JSON summary at end of session

    # Git settings
    commit_prefix: str = "ralph:"
    recent_commits_display: int = 3

    # UI settings
    art_style: str = "braille"
    dashboard_buffer_lines: int = 2000

    # Directories (relative to repo root, or absolute)
    ralph_dir: str = "ralph"
    log_dir: str = "/tmp/ralph-logs"

    # Profile name (for display/debugging)
    profile: str = "default"

    def model_for_stage(self, stage: str) -> str:
        """Resolve the model to use for a given stage.

        Resolution order:
        1. model_{stage} if set (e.g. model_build, model_verify)
        2. model (global fallback)

        Args:
            stage: Stage name (build, verify, investigate, decompose, plan).

        Returns:
            Model identifier string (may be empty if nothing configured).
        """
        stage_field = f"model_{stage.lower()}"
        stage_model = getattr(self, stage_field, "")
        if stage_model:
            return stage_model
        return self.model

    @classmethod
    def _load_toml_data(cls, config_path: Path) -> Optional[dict]:
        """Load TOML data from config file.

        Handles file existence check, missing TOML parser check,
        and TOML parsing with exception handling.

        Args:
            config_path: Path to the config.toml file.

        Returns:
            Parsed TOML data as dict, or None if loading fails.
        """
        if not config_path.exists():
            return None

        if tomllib is None:
            # No TOML parser available
            return None

        try:
            with open(config_path, "rb") as f:
                return tomllib.load(f)
        except Exception:
            return None

    @classmethod
    def _extract_base_config(cls, data: dict) -> dict:
        """Extract base config from TOML data.

        Loops over data keys (excluding 'profiles' and 'default'),
        then overlays [default] section for backward compatibility.

        Args:
            data: Parsed TOML data.

        Returns:
            Merged config dict with base and default values.
        """
        config_dict: dict = {}

        # First, load top-level keys (excluding 'profiles' and 'default' sections)
        for key, value in data.items():
            if key not in ("profiles", "default") and not isinstance(value, dict):
                config_dict[key] = value

        # Then overlay [default] section if it exists (backward compat)
        if "default" in data:
            config_dict.update(data["default"])

        return config_dict

    @classmethod
    def _apply_profile_overlay(cls, config_dict: dict, data: dict) -> None:
        """Apply profile overlay to config if RALPH_PROFILE env var is set.

        Checks RALPH_PROFILE env var via os.getenv, looks up profile in
        data['profiles'], and updates config_dict in place.

        Args:
            config_dict: Config dict to update in place.
            data: Parsed TOML data containing profiles section.
        """
        profile_name = os.getenv("RALPH_PROFILE", "")
        if profile_name and "profiles" in data and profile_name in data["profiles"]:
            config_dict.update(data["profiles"][profile_name])
            config_dict["profile"] = profile_name

    @classmethod
    def _apply_env_overrides(cls, config_dict: dict) -> None:
        """Apply environment variable overrides to config dict.

        Checks RALPH_ART_STYLE env var and updates art_style in config_dict.

        Args:
            config_dict: Config dict to update in place.
        """
        if "RALPH_ART_STYLE" in os.environ:
            config_dict["art_style"] = os.environ["RALPH_ART_STYLE"]

    @classmethod
    def load(cls) -> GlobalConfig:
        """Load config from ~/.config/ralph/config.toml with profile support."""
        config_path = Path.home() / ".config" / "ralph" / "config.toml"

        data = cls._load_toml_data(config_path)
        if data is None:
            return cls()

        # Config priority:
        # 1. Top-level keys (not in [default] or [profiles])
        # 2. [default] section (deprecated, for backward compat)
        # 3. RALPH_PROFILE overlay (if set)
        config_dict = cls._extract_base_config(data)

        # Apply profile overlay
        cls._apply_profile_overlay(config_dict, data)

        # Apply environment variable overrides
        cls._apply_env_overrides(config_dict)

        # Build config object with only valid fields
        valid_fields = {k: v for k, v in config_dict.items() if hasattr(cls, k)}
        return cls(**valid_fields)


# Global singleton - loaded once at first access
_global_config: Optional[GlobalConfig] = None


def get_global_config() -> GlobalConfig:
    """Get the global configuration singleton.

    Returns:
        GlobalConfig instance loaded from ~/.config/ralph/config.toml
        or with default values if config file is missing.
    """
    global _global_config
    if _global_config is None:
        _global_config = GlobalConfig.load()
    return _global_config


def reload_global_config() -> GlobalConfig:
    """Force reload of global configuration.

    Returns:
        Freshly loaded GlobalConfig instance.
    """
    global _global_config
    _global_config = GlobalConfig.load()
    return _global_config


def load_available_profiles() -> dict:
    """Load available profiles from config.toml.

    Returns:
        Dict of profile_name -> profile_config dict.
    """
    config_path = Path.home() / ".config" / "ralph" / "config.toml"

    if not config_path.exists():
        return {}

    if tomllib is None:
        return {}

    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        return data.get("profiles", {})
    except Exception:
        return {}


def apply_profile(profile_name: str) -> None:
    """Apply a profile by setting RALPH_PROFILE and reloading config.

    Args:
        profile_name: Name of profile to apply (e.g., 'budget', 'balanced')
    """
    os.environ["RALPH_PROFILE"] = profile_name
    reload_global_config()


# Config complexity fixed
