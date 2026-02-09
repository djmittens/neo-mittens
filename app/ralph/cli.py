#!/usr/bin/env python3
"""Ralph CLI - argparse setup and command dispatch.

Parser creation refactored into helper functions for maintainability.
"""

import argparse
import json
import os
import sys

# Add the parent directory to the Python path to resolve ralph imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pathlib import Path
from typing import Optional, Sequence

# Local imports
from .commands.init import cmd_init
from .commands.construct import cmd_construct
from .commands.compare import cmd_compare
from .commands.compact import cmd_compact
from .commands.config_cmd import cmd_config
from .commands.watch import cmd_watch
from .commands.stream import cmd_stream
from .commands.plan import cmd_plan
from .commands.set_spec import cmd_set_spec
from .commands.subagent import cmd_subagent, cmd_subagent_schema
from .config import get_global_config, GlobalConfig, load_available_profiles, apply_profile
from .tix import Tix, TixError
from .utils import Colors


def _describe_profile(name: str, profile: dict) -> tuple:
    """Generate description for a profile.
    
    Returns:
        Tuple of (short_description, model_info).
    """
    model = profile.get("model", "default")
    model_build = profile.get("model_build", model)
    
    # Generate description based on profile name
    descriptions = {
        "opus": "Best quality, highest cost",
        "sonnet": "Balanced quality and cost",
        "haiku": "Fast and cheap",
        "budget": "Cheapest option",
        "balanced": "Default balance",
        "hybrid": "Mix of models",
        "quality": "Maximum quality",
    }
    desc = descriptions.get(name.lower(), "Custom profile")
    
    # Model info
    if model == model_build:
        model_info = model.split("/")[-1] if "/" in model else model
    else:
        m1 = model.split("/")[-1] if "/" in model else model
        m2 = model_build.split("/")[-1] if "/" in model_build else model_build
        model_info = f"{m1} (build: {m2})"
    
    return desc, model_info


def _select_profile_interactive() -> Optional[str]:
    """Interactive profile selector.
    
    Prompts user to select a cost profile before starting plan/construct.
    
    Returns:
        Selected profile name, or None to use default.
    """
    # Check if already set via environment
    if os.environ.get("RALPH_PROFILE"):
        return None  # Already set, don't prompt
    
    # Check if stdin is a TTY (interactive)
    if not sys.stdin.isatty():
        return None  # Non-interactive, use default
    
    # Load profiles from config
    profiles = load_available_profiles()
    
    if not profiles:
        print(f"{Colors.DIM}No profiles found in ~/.config/ralph/config.toml{Colors.NC}")
        print(f"{Colors.DIM}Using default configuration{Colors.NC}")
        return None
    
    # Color rotation for profiles
    profile_colors = [Colors.GREEN, Colors.CYAN, Colors.YELLOW, Colors.BLUE, Colors.MAGENTA]
    
    print()
    print(f"{Colors.BLUE}{'─'*60}{Colors.NC}")
    print(f"{Colors.BLUE}SELECT COST PROFILE{Colors.NC}")
    print(f"{Colors.BLUE}{'─'*60}{Colors.NC}")
    print()
    print(f"{Colors.DIM}Choose a profile to optimize cost vs capability.{Colors.NC}")
    print(f"{Colors.DIM}Tip: Use --profile <name> or RALPH_PROFILE=<name> to skip this prompt.{Colors.NC}")
    print()
    
    # Display options
    options = list(profiles.keys())
    for i, name in enumerate(options):
        color = profile_colors[i % len(profile_colors)]
        desc, model_info = _describe_profile(name, profiles[name])
        print(f"  {color}{i+1}. {name:12}{Colors.NC} - {desc}")
        print(f"     {Colors.DIM}Model: {model_info}{Colors.NC}")
    
    print()
    cfg = get_global_config()
    print(f"  {Colors.DIM}0. default{Colors.NC}      - Use [default] section (currently: {cfg.model})")
    print()
    
    # Get selection
    try:
        while True:
            response = input(f"Select profile [1-{len(options)}, 0=default]: ").strip()
            
            if response == "" or response == "0":
                print(f"{Colors.DIM}Using default configuration{Colors.NC}")
                return None
            
            # Check if they typed a profile name directly
            if response.lower() in profiles:
                selected = response.lower()
                desc, _ = _describe_profile(selected, profiles[selected])
                print(f"{Colors.GREEN}Selected: {selected}{Colors.NC} - {desc}")
                return selected
            
            # Check numeric selection
            try:
                idx = int(response) - 1
                if 0 <= idx < len(options):
                    selected = options[idx]
                    desc, _ = _describe_profile(selected, profiles[selected])
                    print(f"{Colors.GREEN}Selected: {selected}{Colors.NC} - {desc}")
                    return selected
            except ValueError:
                pass
            
            print(f"{Colors.RED}Invalid selection. Try again.{Colors.NC}")
    
    except (KeyboardInterrupt, EOFError):
        print()
        return None


def _maybe_select_profile(args) -> None:
    """Check if profile selection is needed and prompt if so.
    
    Args:
        args: Parsed arguments (checks for --profile flag).
    """
    # If --profile was provided, use it
    profile = getattr(args, "profile", None)
    if profile:
        apply_profile(profile)
        return
    
    # Otherwise, prompt for selection
    selected = _select_profile_interactive()
    if selected:
        apply_profile(selected)


def _build_config(global_config: GlobalConfig, include_ralph_dir: bool = True) -> dict:
    """Build config dict with common paths and global config."""
    cwd = Path.cwd()
    ralph_dir = cwd / "ralph"
    config = {
        "repo_root": cwd,
        **global_config.__dict__,
    }
    if include_ralph_dir:
        config["ralph_dir"] = ralph_dir
    return config


def _handle_init(args) -> int:
    return cmd_init()


def _handle_status(args) -> int:
    tix = Tix(Path.cwd())
    print(tix.status())
    return 0


def _handle_config(args) -> int:
    return cmd_config()


def _handle_watch(args) -> int:
    config = _build_config(get_global_config())
    return cmd_watch(config)


def _handle_stream(args) -> int:
    return cmd_stream()


def _handle_plan(args) -> int:
    _maybe_select_profile(args)
    return cmd_plan(get_global_config(), args.spec, args)


def _handle_construct(args) -> int:
    _maybe_select_profile(args)
    global_cfg = get_global_config()

    # CLI flags override config defaults for guard limits
    if getattr(args, "max_tokens", 0):
        global_cfg.max_tokens = args.max_tokens
    if getattr(args, "max_wall_time", 0):
        global_cfg.max_wall_time_s = args.max_wall_time
    if getattr(args, "max_api_calls", 0):
        global_cfg.max_api_calls = args.max_api_calls

    config = _build_config(global_cfg)
    iterations = args.max_iterations or 0
    max_cost = getattr(args, "max_cost", 0.0) or 0.0
    max_failures = getattr(args, "max_failures", 3) or 3
    return cmd_construct(config, iterations, args, max_cost=max_cost, max_failures=max_failures)


def _handle_compare(args) -> int:
    return cmd_compare(get_global_config(), args)


def _handle_query(args) -> int:
    """Delegate query to tix CLI."""
    tix = Tix(Path.cwd())
    subquery = getattr(args, "subquery", None)
    done_only = getattr(args, "done", False)

    if subquery == "tasks":
        data = tix.query_tasks()
    elif subquery == "issues":
        data = tix.query_issues()
    else:
        data = tix.query_full()

    if done_only and isinstance(data, list):
        data = [t for t in data if t.get("status") == "done"]

    print(json.dumps(data, indent=2))
    return 0


def _handle_task(args) -> int:
    """Delegate task operations to tix CLI."""
    if not args.action:
        print(
            "Usage: ralph task [add|done|accept|reject|delete|prioritize] <description>"
        )
        return 1

    tix = Tix(Path.cwd())
    action = args.action
    desc = args.description
    extra = args.extra

    try:
        if action == "add":
            if not desc:
                print("Error: task description required", file=sys.stderr)
                return 1
            result = tix.task_add({"name": desc})
        elif action == "done":
            result = tix.task_done(desc)
        elif action == "accept":
            result = tix.task_accept(desc)
        elif action == "reject":
            if not desc:
                print("Error: task ID required", file=sys.stderr)
                return 1
            result = tix.task_reject(desc, extra or "rejected")
        elif action == "delete":
            if not desc:
                print("Error: task ID required", file=sys.stderr)
                return 1
            result = tix.task_delete(desc)
        elif action == "prioritize":
            if not desc or not extra:
                print("Error: task ID and priority required", file=sys.stderr)
                return 1
            result = tix.task_prioritize(desc, extra)
        else:
            print(f"Unknown task action: {action}", file=sys.stderr)
            return 1

        print(json.dumps(result, indent=2))
        return 0
    except TixError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _handle_issue(args) -> int:
    """Delegate issue operations to tix CLI."""
    if not args.action:
        print("Usage: ralph issue [add|done|done-all|done-ids] <description|ids>")
        return 1

    tix = Tix(Path.cwd())
    action = args.action
    desc = args.description

    try:
        if action == "add":
            if not desc:
                print("Error: issue description required", file=sys.stderr)
                return 1
            result = tix.issue_add(desc)
        elif action == "done":
            result = tix.issue_done()
        elif action == "done-all":
            result = tix.issue_done_all()
        elif action == "done-ids":
            if not desc:
                print("Error: issue IDs required", file=sys.stderr)
                return 1
            result = tix.issue_done_ids(desc.split(","))
        else:
            print(f"Unknown issue action: {action}", file=sys.stderr)
            return 1

        print(json.dumps(result, indent=2))
        return 0
    except TixError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _handle_validate(args) -> int:
    """Delegate validate to tix CLI."""
    tix = Tix(Path.cwd())
    try:
        result = tix.validate()
        if result.raw:
            print(result.raw)
        else:
            print(json.dumps(result.data, indent=2))
        return 0
    except TixError as e:
        print(f"Validation failed: {e}", file=sys.stderr)
        return 1


def _handle_compact(args) -> int:
    cmd_compact(get_global_config(), args)
    return 0


def _handle_log(args) -> int:
    """Delegate log to tix CLI."""
    tix = Tix(Path.cwd())
    cmd_args = ["log"]
    if getattr(args, "all", False):
        cmd_args.append("--all")
    if getattr(args, "spec", None):
        cmd_args.extend(["--spec", args.spec])
    if getattr(args, "branch", None):
        cmd_args.extend(["--branch", args.branch])
    if getattr(args, "since", None):
        cmd_args.extend(["--since", args.since])
    try:
        result = tix._run(*cmd_args, parse_json=False)
        if result.raw:
            print(result.raw)
        return 0
    except TixError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def _handle_set_spec(args) -> int:
    config = _build_config(get_global_config())
    return cmd_set_spec(config, args.spec)


def _handle_subagent(args) -> int:
    return cmd_subagent(
        subagent_type=args.type,
        context_json=getattr(args, "context", None),
        validate_json=getattr(args, "validate", None),
    )


def _handle_subagent_schema(args) -> int:
    return cmd_subagent_schema(args.type)


_COMMAND_HANDLERS = {
    "init": _handle_init,
    "status": _handle_status,
    "config": _handle_config,
    "watch": _handle_watch,
    "stream": _handle_stream,
    "plan": _handle_plan,
    "construct": _handle_construct,
    "compare": _handle_compare,
    "query": _handle_query,
    "task": _handle_task,
    "issue": _handle_issue,
    "validate": _handle_validate,
    "compact": _handle_compact,
    "log": _handle_log,
    "set-spec": _handle_set_spec,
    "subagent": _handle_subagent,
    "subagent-schema": _handle_subagent_schema,
}


def _dispatch_command(command: str, args) -> int:
    """Dispatch to appropriate command handler."""
    handler = _COMMAND_HANDLERS.get(command)
    if handler is None:
        print(f"ralph: unknown command '{command}'", file=sys.stderr)
        return 1
    return handler(args)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Main entry point for ralph CLI."""
    parser = _create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    return _dispatch_command(args.command, args)


def _add_simple_parsers(subparsers) -> None:
    """Add simple single-line subcommand parsers."""
    subparsers.add_parser("init", help="Initialize a new ralph project")
    subparsers.add_parser("status", help="Show current project status")
    subparsers.add_parser("config", help="Configure Ralph settings")
    subparsers.add_parser("watch", help="Watch for plan changes and sync")
    subparsers.add_parser("stream", help="Stream construct output")
    subparsers.add_parser("validate", help="Validate plan for issues")
    subparsers.add_parser("compact", help="Compact plan file")

    log_p = subparsers.add_parser("log", help="Show state change history")
    log_p.add_argument("--all", action="store_true", help="Show all history")
    log_p.add_argument("--spec", help="Filter by spec")
    log_p.add_argument("--branch", help="Filter by branch")
    log_p.add_argument("--since", help="Filter since date/commit")


def _add_construct_parser(subparsers) -> None:
    """Add construct subcommand with all its options."""
    p = subparsers.add_parser("construct", help="Run autonomous construction")
    p.add_argument(
        "--spec", help="Spec file to construct (auto-initializes if not set up)"
    )
    p.add_argument(
        "--max-cost", type=float, default=0, help="Stop when cost exceeds $N"
    )
    p.add_argument("--max-failures", type=int, help="Stop after N consecutive failures")
    p.add_argument(
        "--completion-promise", default="", help="Stop when output contains this text"
    )
    p.add_argument("--timeout", type=int, help="Kill stage after N milliseconds")
    p.add_argument("--context-limit", type=int, help="Context window size in tokens")
    p.add_argument("--no-ui", action="store_true", help="Disable interactive dashboard")
    p.add_argument(
        "--max-iterations", type=int, help="Max iterations (alternative syntax)"
    )
    p.add_argument(
        "--profile",
        "-p",
        help="Cost profile: budget, balanced, hybrid, cost_smart, quality",
    )
    p.add_argument(
        "--max-tokens", type=int, default=0,
        help="Stop when total tokens exceed N (0 = unlimited)",
    )
    p.add_argument(
        "--max-wall-time", type=int, default=0,
        help="Stop after N seconds of wall time (0 = use config default)",
    )
    p.add_argument(
        "--max-api-calls", type=int, default=0,
        help="Stop after N remote API calls (0 = unlimited, local is free)",
    )


def _add_compare_parser(subparsers) -> None:
    """Add compare subcommand for A/B run comparison."""
    p = subparsers.add_parser("compare", help="Compare runs from the ledger")
    p.add_argument("--spec", help="Filter by spec name")
    p.add_argument("--profile-filter", help="Filter by profile name")
    p.add_argument("--json", action="store_true", help="Output as JSON")


def _add_entity_parsers(subparsers) -> None:
    """Add task, query, issue, plan, and set-spec parsers."""
    plan_p = subparsers.add_parser("plan", help="Generate plan from spec")
    plan_p.add_argument("spec", help="Spec file to plan from")
    plan_p.add_argument(
        "--profile",
        "-p",
        help="Cost profile: opus, sonnet, haiku, etc.",
    )

    task_p = subparsers.add_parser("task", help="Manage tasks")
    task_p.add_argument(
        "action",
        nargs="?",
        help="Action: add, done, accept, reject, delete, prioritize",
    )
    task_p.add_argument("description", nargs="?", help="Task description or ID")
    task_p.add_argument("extra", nargs="?", help="Extra argument (e.g., reject reason)")

    query_p = subparsers.add_parser("query", help="Query current state as JSON")
    query_p.add_argument(
        "subquery", nargs="?", help="Subquery: stage, iteration, tasks, issues, next"
    )
    query_p.add_argument("--done", action="store_true", help="Show only done tasks")

    issue_p = subparsers.add_parser("issue", help="Manage issues")
    issue_p.add_argument(
        "action", nargs="?", help="Action: add, done, done-all, done-ids"
    )
    issue_p.add_argument("description", nargs="?", help="Issue description or IDs")

    set_spec_p = subparsers.add_parser("set-spec", help="Set current spec")
    set_spec_p.add_argument("spec", help="Spec file to set")

    # Subagent command for generating structured prompts
    subagent_p = subparsers.add_parser("subagent", help="Generate subagent prompts")
    subagent_p.add_argument(
        "type",
        choices=["investigate", "verify_task", "verify_criterion", "research", "decompose"],
        help="Subagent type",
    )
    subagent_p.add_argument("--context", help="JSON context for prompt generation")
    subagent_p.add_argument("--validate", help="JSON response to validate against schema")

    # Subagent schema command
    schema_p = subparsers.add_parser("subagent-schema", help="Get subagent JSON schema")
    schema_p.add_argument(
        "type",
        choices=["investigate", "verify_task", "verify_criterion", "research", "decompose"],
        help="Subagent type",
    )


def _create_parser() -> argparse.ArgumentParser:
    """Create argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        description="Ralph CLI - Autonomous Development Assistant"
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    subparsers = parser.add_subparsers(
        dest="command", help="Ralph commands", required=False
    )
    _add_simple_parsers(subparsers)
    _add_construct_parser(subparsers)
    _add_compare_parser(subparsers)
    _add_entity_parsers(subparsers)
    return parser


if __name__ == "__main__":
    sys.exit(main())
