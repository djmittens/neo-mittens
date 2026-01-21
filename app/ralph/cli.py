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
from .config import get_global_config


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Main entry point for ralph CLI."""
    parser = _create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "init":
        return cmd_init()

    if args.command == "status":
        global_config = get_global_config()
        cwd = Path.cwd()
        ralph_dir = cwd / "ralph"
        plan_file = ralph_dir / "plan.jsonl"
        config = {
            "plan_file": plan_file,
            "repo_root": cwd,
            "ralph_dir": ralph_dir,
            **global_config.__dict__,
        }
        return cmd_status(config)

    if args.command == "config":
        return cmd_config()

    if args.command == "watch":
        global_config = get_global_config()
        cwd = Path.cwd()
        ralph_dir = cwd / "ralph"
        plan_file = ralph_dir / "plan.jsonl"
        config = {
            "plan_file": plan_file,
            "repo_root": cwd,
            "ralph_dir": ralph_dir,
            **global_config.__dict__,
        }
        return cmd_watch(config)

    if args.command == "stream":
        return cmd_stream()

    if args.command == "plan":
        global_config = get_global_config()
        cwd = Path.cwd()
        config = {
            "repo_root": cwd,
            **global_config.__dict__,
        }
        return cmd_plan(config, args.spec, args)

    if args.command == "construct":
        global_config = get_global_config()
        cwd = Path.cwd()
        ralph_dir = cwd / "ralph"
        plan_file = ralph_dir / "plan.jsonl"

        # Determine spec and iterations
        spec_file = args.spec

        config = {
            "plan_file": plan_file,
            "repo_root": cwd,
            "ralph_dir": ralph_dir,
            **global_config.__dict__,
        }

        # Use max_iterations if provided, otherwise use iterations
        iterations = 0
        if args.max_iterations is not None:
            iterations = args.max_iterations
        elif args.iterations is not None:
            iterations = args.iterations

        return cmd_construct(config, iterations, args)

    if args.command == "query":
        global_config = get_global_config()
        cwd = Path.cwd()
        ralph_dir = cwd / "ralph"
        plan_file = ralph_dir / "plan.jsonl"
        config = {
            "plan_file": plan_file,
            "repo_root": cwd,
            "ralph_dir": ralph_dir,
            **global_config.__dict__,
        }
        return cmd_query(config, args.subquery, args.done)

    if args.command == "task":
        if not args.action:
            print(
                "Usage: ralph task [add|done|accept|reject|delete|prioritize] <description>"
            )
            return 1

        global_config = get_global_config()
        cwd = Path.cwd()
        ralph_dir = cwd / "ralph"
        plan_file = ralph_dir / "plan.jsonl"
        config = {
            "plan_file": plan_file,
            "repo_root": cwd,
            **global_config.__dict__,
        }
        return cmd_task(config, args.action, args.description, args.extra)

    if args.command == "issue":
        if not args.action:
            print("Usage: ralph issue [add|done|done-all|done-ids] <description>")
            return 1
        global_config = get_global_config()
        cwd = Path.cwd()
        ralph_dir = cwd / "ralph"
        plan_file = ralph_dir / "plan.jsonl"
        config = {
            "plan_file": plan_file,
            "repo_root": cwd,
            **global_config.__dict__,
        }
        return cmd_issue(config, args.action, args.description)

    if args.command == "validate":
        global_config = get_global_config()
        return cmd_validate(global_config, args)

    if args.command == "compact":
        global_config = get_global_config()
        cmd_compact(global_config, args)
        return 0

    if args.command == "log":
        print("ralph log: feature not yet implemented")
        return 0

    if args.command == "set-spec":
        print("ralph set-spec: feature not yet implemented")
        return 0

    print(f"ralph: unknown command '{args.command}'", file=sys.stderr)
    return 1


def _create_parser() -> argparse.ArgumentParser:
    """Create argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        description="Ralph CLI - Autonomous Development Assistant"
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    subparsers = parser.add_subparsers(
        dest="command", help="Ralph commands", required=False
    )

    # init
    subparsers.add_parser("init", help="Initialize a new ralph project")

    # status
    subparsers.add_parser("status", help="Show current project status")

    # config
    subparsers.add_parser("config", help="Configure Ralph settings")

    # watch
    subparsers.add_parser("watch", help="Watch for plan changes and sync")

    # stream
    subparsers.add_parser("stream", help="Stream construct output")

    # plan
    plan_parser = subparsers.add_parser("plan", help="Generate plan from spec")
    plan_parser.add_argument("spec", help="Spec file to plan from")

    # construct
    construct_parser = subparsers.add_parser(
        "construct", help="Run autonomous construction"
    )
    construct_parser.add_argument("spec", nargs="?", help="Spec file to construct")
    construct_parser.add_argument(
        "iterations", nargs="?", type=int, help="Max iterations"
    )
    construct_parser.add_argument(
        "--max-cost", type=float, default=0, help="Stop when cost exceeds $N"
    )
    construct_parser.add_argument(
        "--max-failures", type=int, help="Stop after N consecutive failures"
    )
    construct_parser.add_argument(
        "--completion-promise", default="", help="Stop when output contains this text"
    )
    construct_parser.add_argument(
        "--timeout", type=int, help="Kill stage after N milliseconds"
    )
    construct_parser.add_argument(
        "--context-limit", type=int, help="Context window size in tokens"
    )
    construct_parser.add_argument(
        "--no-ui", action="store_true", help="Disable interactive dashboard"
    )
    construct_parser.add_argument(
        "--max-iterations", type=int, help="Max iterations (alternative syntax)"
    )
    construct_parser.add_argument(
        "--profile",
        "-p",
        help="Cost profile: budget, balanced, hybrid, cost_smart, quality",
    )

    # task
    task_parser = subparsers.add_parser("task", help="Manage tasks")
    task_parser.add_argument(
        "action",
        nargs="?",
        help="Action: add, done, accept, reject, delete, prioritize",
    )
    task_parser.add_argument("description", nargs="?", help="Task description or ID")
    task_parser.add_argument(
        "extra", nargs="?", help="Extra argument (e.g., reject reason)"
    )

    # query
    query_parser = subparsers.add_parser("query", help="Query current state as JSON")
    query_parser.add_argument(
        "subquery", nargs="?", help="Subquery: stage, iteration, tasks, issues, next"
    )
    query_parser.add_argument(
        "--done", action="store_true", help="Show only done tasks"
    )

    # issue
    issue_parser = subparsers.add_parser("issue", help="Manage issues")
    issue_parser.add_argument(
        "action", nargs="?", help="Action: add, done, done-all, done-ids"
    )
    issue_parser.add_argument("description", nargs="?", help="Issue description or IDs")

    # Additional parsers with minimal setup
    subparsers.add_parser("validate", help="Validate plan for issues")
    subparsers.add_parser("compact", help="Compact plan file")
    subparsers.add_parser("log", help="Show state change history")
    set_spec_parser = subparsers.add_parser("set-spec", help="Set current spec")
    set_spec_parser.add_argument("spec", help="Spec file to set")

    return parser


if __name__ == "__main__":
    sys.exit(main())
