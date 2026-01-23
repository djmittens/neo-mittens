"""Ralph config command.

Shows the global configuration.
"""

from pathlib import Path

from ralph.config import get_global_config, GlobalConfig
from ralph.utils import Colors

__all__ = ["cmd_config"]


def _get_config_path() -> Path:
    """Get path to config file."""
    return Path.home() / ".config" / "ralph" / "config.toml"


def _format_ms(ms: int) -> str:
    """Format milliseconds as human-readable."""
    if ms >= 60000:
        return f"{ms:,}ms ({ms / 60000:.1f} min)"
    return f"{ms:,}ms"


def _print_header() -> None:
    """Print config header."""
    print(f"{Colors.BLUE}{'=' * 60}{Colors.NC}")
    print(f"{Colors.BLUE}RALPH GLOBAL CONFIGURATION{Colors.NC}")
    print(f"{Colors.BLUE}{'=' * 60}{Colors.NC}")
    print()


def _print_config_file() -> None:
    """Print config file section."""
    config_path = _get_config_path()
    print(f"{Colors.CYAN}Config File{Colors.NC}")
    if config_path.exists():
        print(f"  {Colors.GREEN}✓{Colors.NC} {config_path}")
    else:
        print(f"  {Colors.YELLOW}○{Colors.NC} {config_path} (using defaults)")
    print()


def _print_profile(gcfg: GlobalConfig) -> None:
    """Print active profile."""
    print(f"{Colors.CYAN}Active Profile{Colors.NC}")
    print(f"  Profile: {Colors.GREEN}{gcfg.profile}{Colors.NC}")
    print()


def _print_model_settings(gcfg: GlobalConfig) -> None:
    """Print model settings."""
    print(f"{Colors.CYAN}Model Settings{Colors.NC}")
    print(f"  model: {Colors.GREEN}{gcfg.model}{Colors.NC}")
    if hasattr(gcfg, "model_build") and gcfg.model_build:
        print(f"  model_build: {Colors.GREEN}{gcfg.model_build}{Colors.NC}")
    print()


def _print_context_limits(gcfg: GlobalConfig) -> None:
    """Print context limit settings."""
    print(f"{Colors.CYAN}Context Limits{Colors.NC}")
    print(f"  context_window:     {gcfg.context_window:,} tokens")
    print(f"  context_warn_pct:   {gcfg.context_warn_pct}%")
    print(f"  context_compact_pct: {gcfg.context_compact_pct}%")
    print(f"  context_kill_pct:   {gcfg.context_kill_pct}%")
    print()


def _print_timeouts(gcfg: GlobalConfig) -> None:
    """Print timeout settings."""
    print(f"{Colors.CYAN}Timeouts{Colors.NC}")
    print(f"  stage_timeout_ms:     {_format_ms(gcfg.stage_timeout_ms)}")
    print(f"  iteration_timeout_ms: {_format_ms(gcfg.iteration_timeout_ms)}")
    print()


def _print_circuit_breaker(gcfg: GlobalConfig) -> None:
    """Print circuit breaker settings."""
    print(f"{Colors.CYAN}Circuit Breaker{Colors.NC}")
    print(f"  max_failures:       {gcfg.max_failures}")
    print(f"  max_decompose_depth: {gcfg.max_decompose_depth}")
    print()


def _print_batch_settings(gcfg: GlobalConfig) -> None:
    """Print bounded fork-join settings."""
    print(f"{Colors.CYAN}Bounded Fork-Join{Colors.NC}")
    print(f"  verify_batch_size:     {gcfg.verify_batch_size}")
    print(f"  investigate_batch_size: {gcfg.investigate_batch_size}")
    print()


def _print_git_settings(gcfg: GlobalConfig) -> None:
    """Print git settings."""
    print(f"{Colors.CYAN}Git Settings{Colors.NC}")
    print(f"  commit_prefix:        {gcfg.commit_prefix}")
    print(f"  recent_commits_display: {gcfg.recent_commits_display}")
    print()


def _print_ui_settings(gcfg: GlobalConfig) -> None:
    """Print UI settings."""
    print(f"{Colors.CYAN}UI Settings{Colors.NC}")
    print(f"  art_style:            {gcfg.art_style}")
    print(f"  dashboard_buffer_lines: {gcfg.dashboard_buffer_lines}")
    print()


def _print_directories(gcfg: GlobalConfig) -> None:
    """Print directory settings."""
    print(f"{Colors.CYAN}Directories{Colors.NC}")
    print(f"  ralph_dir: {gcfg.ralph_dir}")
    print(f"  log_dir:   {gcfg.log_dir}")
    print()


def _print_example() -> None:
    """Print example config."""
    print(f"{Colors.DIM}{'─' * 60}{Colors.NC}")
    print(f"{Colors.CYAN}Example config.toml:{Colors.NC}")
    print(
        f"""{Colors.DIM}
[default]
model = "anthropic/claude-sonnet-4"

[profiles.work]
model = "anthropic/claude-opus-4"

[profiles.home]
model = "openrouter/anthropic/claude-opus-4"

# Set RALPH_PROFILE=work or RALPH_PROFILE=home to switch
{Colors.NC}"""
    )


def cmd_config() -> int:
    """Show global configuration.

    Returns:
        Exit code (0 for success).
    """
    gcfg = get_global_config()

    _print_header()
    _print_config_file()
    _print_profile(gcfg)
    _print_model_settings(gcfg)
    _print_context_limits(gcfg)
    _print_timeouts(gcfg)
    _print_circuit_breaker(gcfg)
    _print_batch_settings(gcfg)
    _print_git_settings(gcfg)
    _print_ui_settings(gcfg)
    _print_directories(gcfg)
    _print_example()

    return 0
