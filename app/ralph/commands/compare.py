"""Ralph compare command.

Reads run records from the ledger and displays a comparison table
grouped by spec. Designed for A/B testing different model configurations
across worktrees.
"""

import argparse
import json
from pathlib import Path
from typing import Optional

from ..config import GlobalConfig
from ..ledger import load_runs, load_iterations
from ..utils import Colors

__all__ = ["cmd_compare"]


def _format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable string.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like "12m30s" or "1h05m".
    """
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h{mins:02d}m"


def _format_tokens(count: int) -> str:
    """Format token count with K/M suffix.

    Args:
        count: Token count.

    Returns:
        Formatted string like "150K" or "1.2M".
    """
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.0f}K"
    return str(count)


def _print_run_row(run: dict) -> None:
    """Print a single run as a table row.

    Args:
        run: Run record dict from JSONL.
    """
    profile = run.get("profile", "?")
    branch = run.get("branch", "?")
    exit_reason = run.get("exit_reason", "?")
    iters = run.get("iterations", 0)
    duration = run.get("duration_s", 0)
    cost = run.get("cost", 0)
    tokens = run.get("tokens", {})
    total_tok = tokens.get("input", 0) + tokens.get("cached", 0) + tokens.get("output", 0)
    api = run.get("api_calls", {})
    remote = api.get("remote", 0)
    local = api.get("local", 0)
    tasks = run.get("tasks", {})
    completed = tasks.get("completed", 0)

    # Color exit reason
    exit_colors = {
        "complete": Colors.GREEN,
        "no_work": Colors.GREEN,
        "max_iterations": Colors.YELLOW,
        "cost_limit": Colors.YELLOW,
        "token_limit": Colors.YELLOW,
        "wall_time_limit": Colors.YELLOW,
        "api_call_limit": Colors.YELLOW,
        "progress_stall": Colors.RED,
        "circuit_breaker": Colors.RED,
    }
    ec = exit_colors.get(exit_reason, Colors.NC)

    print(
        f"  {profile:<14} {branch:<20} "
        f"{iters:>4}  {_format_duration(duration):>7}  "
        f"${cost:>7.4f}  {_format_tokens(total_tok):>6}  "
        f"{remote:>3}r/{local:<2}l  "
        f"{completed:>3}  "
        f"{ec}{exit_reason}{Colors.NC}"
    )


def _print_comparison_table(runs: list[dict], spec: str) -> None:
    """Print a comparison table for runs matching a spec.

    Args:
        runs: List of run record dicts.
        spec: Spec name to display.
    """
    print(f"\n{Colors.CYAN}Spec: {spec}{Colors.NC}")
    print(
        f"  {'Profile':<14} {'Branch':<20} "
        f"{'Iter':>4}  {'Time':>7}  "
        f"{'Cost':>8}  {'Tokens':>6}  "
        f"{'API':>7}  "
        f"{'Done':>4}  "
        f"Exit"
    )
    print(f"  {'─' * 14} {'─' * 20} {'─' * 4}  {'─' * 7}  {'─' * 8}  {'─' * 6}  {'─' * 7}  {'─' * 4}  {'─' * 16}")

    for run in runs:
        _print_run_row(run)


def _print_json_output(runs: list[dict]) -> None:
    """Print runs as JSON for machine consumption.

    Args:
        runs: List of run record dicts.
    """
    print(json.dumps(runs, indent=2))


def cmd_compare(
    config: GlobalConfig,
    args: argparse.Namespace,
) -> int:
    """Compare runs from the ledger.

    Reads runs.jsonl, groups by spec, and displays a comparison table.

    Args:
        config: Global Ralph configuration.
        args: CLI arguments (spec filter, json output, etc.).

    Returns:
        Exit code (0 for success).
    """
    log_dir = Path(config.log_dir)
    runs = load_runs(log_dir)

    if not runs:
        print(f"{Colors.YELLOW}No runs found in {log_dir}{Colors.NC}")
        return 0

    # Apply filters
    spec_filter = getattr(args, "spec", None)
    profile_filter = getattr(args, "profile_filter", None)
    json_output = getattr(args, "json", False)

    if spec_filter:
        runs = [r for r in runs if r.get("spec") == spec_filter]
    if profile_filter:
        runs = [r for r in runs if r.get("profile") == profile_filter]

    if not runs:
        print(f"{Colors.YELLOW}No matching runs found{Colors.NC}")
        return 0

    if json_output:
        _print_json_output(runs)
        return 0

    # Group by spec
    specs: dict[str, list[dict]] = {}
    for run in runs:
        spec = run.get("spec", "unknown")
        specs.setdefault(spec, []).append(run)

    print(f"{Colors.BLUE}{'━' * 60}{Colors.NC}")
    print(f"{Colors.BLUE}RALPH RUN COMPARISON{Colors.NC}")
    print(f"{Colors.BLUE}{'━' * 60}{Colors.NC}")
    print(f"Log dir: {log_dir}")
    print(f"Total runs: {len(runs)}")

    for spec, spec_runs in sorted(specs.items()):
        _print_comparison_table(spec_runs, spec)

    print(f"\n{Colors.BLUE}{'━' * 60}{Colors.NC}")
    return 0
