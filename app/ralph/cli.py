#!/usr/bin/env python3
"""Ralph CLI - argparse setup and command dispatch."""

import argparse
import os
import sys

# Add the parent directory to the Python path to resolve ralph imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sys
from pathlib import Path
from typing import Optional, Sequence

# Local imports
from .commands.init import cmd_init
from .commands.construct import cmd_construct
from .commands.task import cmd_task
from .commands.validate import cmd_validate
from .commands.compact import cmd_compact
from .commands.status import cmd_status
from .commands.config_cmd import cmd_config
from .commands.watch import cmd_watch
from .commands.stream import cmd_stream
from .commands.plan import cmd_plan
from .commands.query import cmd_query
from .commands.issue import cmd_issue
from .config import get_global_config, GlobalConfig


def _build_config(global_config: GlobalConfig, include_ralph_dir: bool = True) -> dict:
    """Build config dict with common paths and global config."""
    cwd = Path.cwd()
    ralph_dir = cwd / "ralph"
    plan_file = ralph_dir / "plan.jsonl"
    config = {
        "plan_file": plan_file,
        "repo_root": cwd,
        **global_config.__dict__,
    }
    if include_ralph_dir:
        config["ralph_dir"] = ralph_dir
    return config


def _handle_init(args) -> int:
    return cmd_init()


def _handle_status(args) -> int:
    config = _build_config(get_global_config())
    return cmd_status(config)


def _handle_config(args) -> int:
    return cmd_config()


def _handle_watch(args) -> int:
    config = _build_config(get_global_config())
    return cmd_watch(config)


def _handle_stream(args) -> int:
    return cmd_stream()


def _handle_plan(args) -> int:
    return cmd_plan(get_global_config(), args.spec, args)


def _handle_construct(args) -> int:
    config = _build_config(get_global_config())
    iterations = args.max_iterations or 0
    return cmd_construct(config, iterations, args)


def _handle_query(args) -> int:
    config = _build_config(get_global_config())
    return cmd_query(config, args.subquery, args.done)


def _handle_task(args) -> int:
    if not args.action:
        print(
            "Usage: ralph task [add|done|accept|reject|delete|prioritize] <description>"
        )
        return 1
    config = _build_config(get_global_config(), include_ralph_dir=False)
    return cmd_task(config, args.action, args.description, args.extra)


def _handle_issue(args) -> int:
    if not args.action:
        print("Usage: ralph issue [add|done|done-all|done-ids] <description>")
        return 1
    config = _build_config(get_global_config(), include_ralph_dir=False)
    return cmd_issue(config, args.action, args.description)


def _handle_validate(args) -> int:
    return cmd_validate(get_global_config(), args)


def _handle_compact(args) -> int:
    cmd_compact(get_global_config(), args)
    return 0


def _handle_log(args) -> int:
    print("ralph log: feature not yet implemented")
    return 0


def _handle_set_spec(args) -> int:
    print("ralph set-spec: feature not yet implemented")
    return 0


_COMMAND_HANDLERS = {
    "init": _handle_init,
    "status": _handle_status,
    "config": _handle_config,
    "watch": _handle_watch,
    "stream": _handle_stream,
    "plan": _handle_plan,
    "construct": _handle_construct,
    "query": _handle_query,
    "task": _handle_task,
    "issue": _handle_issue,
    "validate": _handle_validate,
    "compact": _handle_compact,
    "log": _handle_log,
    "set-spec": _handle_set_spec,
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
    subparsers.add_parser("log", help="Show state change history")


def _add_construct_parser(subparsers) -> None:
    """Add construct subcommand with all its options."""
    p = subparsers.add_parser("construct", help="Run autonomous construction")
    p.add_argument("spec", help="Spec file to construct")
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


def _add_entity_parsers(subparsers) -> None:
    """Add task, query, issue, plan, and set-spec parsers."""
    plan_p = subparsers.add_parser("plan", help="Generate plan from spec")
    plan_p.add_argument("spec", help="Spec file to plan from")

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
    _add_entity_parsers(subparsers)
    return parser


if __name__ == "__main__":
    sys.exit(main())
