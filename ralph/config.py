"""Global configuration for Ralph.

Handles loading configuration from ~/.config/ralph/config.toml with profile
support via the RALPH_PROFILE environment variable.
"""

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Dict, Optional
import os


@dataclass
class GlobalConfig:
    """Global Ralph configuration loaded from ~/.config/ralph/config.toml."""

    model: str = "anthropic/claude-opus-4-5"
    context_window: int = 200_000
    context_warn_pct: int = 70
    context_compact_pct: int = 85
    context_kill_pct: int = 95
    stage_timeout_ms: int = 300_000
    iteration_timeout_ms: int = 300_000
    max_failures: int = 3
    max_decompose_depth: int = 3
    commit_prefix: str = "ralph:"
    recent_commits_display: int = 3
    art_style: str = "braille"
    dashboard_buffer_lines: int = 2000
    ralph_dir: str = "ralph"
    log_dir: str = "build/ralph-logs"
    _profile_name: str = "default"

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "GlobalConfig":
        """Load configuration from TOML file.

        Args:
            config_path: Optional path to config file. Defaults to
                ~/.config/ralph/config.toml

        Returns:
            GlobalConfig instance with loaded or default values.
        """
        if config_path is None:
            config_path = Path.home() / ".config" / "ralph" / "config.toml"

        if not config_path.exists():
            return cls()

        toml_data = _load_toml(config_path)
        if toml_data is None:
            return cls()

        config_dict: Dict[str, Any] = {}

        if "default" in toml_data:
            config_dict.update(toml_data["default"])

        profile_name = os.environ.get("RALPH_PROFILE", "")
        if profile_name and "profiles" in toml_data:
            if profile_name in toml_data["profiles"]:
                config_dict.update(toml_data["profiles"][profile_name])
                config_dict["_profile_name"] = profile_name

        if "RALPH_ART_STYLE" in os.environ:
            config_dict["art_style"] = os.environ["RALPH_ART_STYLE"]

        valid_fields = {f.name for f in fields(cls)}
        filtered_dict = {k: v for k, v in config_dict.items() if k in valid_fields}

        return cls(**filtered_dict)


def _load_toml(path: Path) -> Optional[Dict[str, Any]]:
    """Load TOML file, trying tomllib then tomli.

    Args:
        path: Path to the TOML file.

    Returns:
        Parsed TOML data as a dict, or None if parsing failed.
    """
    try:
        import tomllib

        with open(path, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        pass

    try:
        import tomli

        with open(path, "rb") as f:
            return tomli.load(f)
    except ImportError:
        pass

    return None


_global_config: Optional[GlobalConfig] = None


def get_global_config() -> GlobalConfig:
    """Get the global configuration singleton.

    Returns:
        The global GlobalConfig instance, loading if necessary.
    """
    global _global_config
    if _global_config is None:
        _global_config = GlobalConfig.load()
    return _global_config


def reload_global_config() -> GlobalConfig:
    """Force reload of global configuration.

    Returns:
        The newly loaded GlobalConfig instance.
    """
    global _global_config
    _global_config = GlobalConfig.load()
    return _global_config
