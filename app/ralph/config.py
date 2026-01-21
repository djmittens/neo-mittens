"""Global Ralph configuration loaded from ~/.config/ralph/config.toml."""

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
    model: str = ""
    model_build: str = ""

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

    @classmethod
    def load(cls) -> GlobalConfig:
        """Load config from ~/.config/ralph/config.toml with profile support."""
        config_path = Path.home() / ".config" / "ralph" / "config.toml"

        if not config_path.exists():
            return cls()

        if tomllib is None:
            # No TOML parser available, use defaults
            return cls()

        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            return cls()

        # Config priority:
        # 1. Top-level keys (not in [default] or [profiles])
        # 2. [default] section (deprecated, for backward compat)
        # 3. RALPH_PROFILE overlay (if set)
        config_dict: dict = {}

        # First, load top-level keys (excluding 'profiles' and 'default' sections)
        for key, value in data.items():
            if key not in ("profiles", "default") and not isinstance(value, dict):
                config_dict[key] = value

        # Then overlay [default] section if it exists (backward compat)
        if "default" in data:
            config_dict.update(data["default"])

        # Apply profile if RALPH_PROFILE is set
        profile_name = os.environ.get("RALPH_PROFILE", "")
        if profile_name and "profiles" in data and profile_name in data["profiles"]:
            config_dict.update(data["profiles"][profile_name])
            config_dict["profile"] = profile_name

        # Also check RALPH_ART_STYLE env var for backward compatibility
        if "RALPH_ART_STYLE" in os.environ:
            config_dict["art_style"] = os.environ["RALPH_ART_STYLE"]

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
