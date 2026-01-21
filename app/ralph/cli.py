#!/usr/bin/env python3
"""Ralph CLI - argparse setup and command dispatch."""

import argparse
import sys
from typing import Optional, Sequence

from ralph import __version__


def _create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        prog="ralph",
        description="Ralph Wiggum - Autonomous AI Development Loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ralph init                    Initialize in current repo
  ralph plan spec.md            Plan tasks for a specific spec
  ralph construct               Run autonomous construction
  ralph status                  Show current status
  ralph query                   Query current state as JSON
  ralph task add "description"  Add a new task
  ralph issue add "description" Add a new issue
""",
    )

    parser.add_argument("--version", action="version", version=f"ralph {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # init
    subparsers.add_parser("init", help="Initialize ralph in current directory")

    # status
    subparsers.add_parser("status", help="Show ralph status")

    # config
    subparsers.add_parser("config", help="Configure ralph settings")

    # watch
    subparsers.add_parser("watch", help="Watch for changes and show live dashboard")

    # stream
    subparsers.add_parser(
        "stream", help="Stream opencode output with pretty formatting"
    )

    # plan
    plan_parser = subparsers.add_parser("plan", help="Create plan from spec")
    plan_parser.add_argument("spec", nargs="?", help="Spec file to plan")
    plan_parser.add_argument(
        "--max-cost", type=float, default=0, help="Stop when cost exceeds $N"
    )
    plan_parser.add_argument(
        "--timeout", type=int, help="Kill stage after N milliseconds"
    )
    plan_parser.add_argument(
        "--no-ui", action="store_true", help="Disable interactive dashboard"
    )

    # construct
    construct_parser = subparsers.add_parser(
        "construct", help="Run autonomous construction"
    )
    construct_parser.add_argument(
        "iterations", nargs="?", type=int, help="Max iterations"
    )
    construct_parser.add_argument("spec", nargs="?", help="Spec file to construct")
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

    # query
    query_parser = subparsers.add_parser("query", help="Query current state as JSON")
    query_parser.add_argument(
        "subquery", nargs="?", help="Subquery: stage, iteration, tasks, issues, next"
    )
    query_parser.add_argument(
        "--done", action="store_true", help="Show only done tasks"
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

    # issue
    issue_parser = subparsers.add_parser("issue", help="Manage issues")
    issue_parser.add_argument(
        "action", nargs="?", help="Action: add, done, done-all, done-ids"
    )
    issue_parser.add_argument("description", nargs="?", help="Issue description or IDs")

    # validate
    subparsers.add_parser("validate", help="Validate plan for issues")

    # compact
    subparsers.add_parser("compact", help="Compact plan file, archive old tombstones")

    # log
    log_parser = subparsers.add_parser("log", help="Show state change history")
    log_parser.add_argument("--all", action="store_true", help="Show all history")
    log_parser.add_argument("--spec", help="Filter by spec")
    log_parser.add_argument("--branch", help="Filter by branch")
    log_parser.add_argument("--since", help="Filter since date/commit")

    # set-spec
    set_spec_parser = subparsers.add_parser("set-spec", help="Set current spec")
    set_spec_parser.add_argument("spec", help="Spec file to set")

    return parser


def _stub_command(name: str) -> int:
    """Return stub message for unimplemented commands."""
    print(f"ralph {name}: stub - not yet implemented")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Main entry point for ralph CLI."""
    parser = _create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "init":
        return _stub_command("init")

    if args.command == "status":
        return _stub_command("status")

    if args.command == "config":
        return _stub_command("config")

    if args.command == "watch":
        return _stub_command("watch")

    if args.command == "stream":
        return _stub_command("stream")

    if args.command == "plan":
        return _stub_command("plan")

    if args.command == "construct":
        return _stub_command("construct")

    if args.command == "query":
        return _stub_command("query")

    if args.command == "task":
        if not args.action:
            print(
                "Usage: ralph task [add|done|accept|reject|delete|prioritize] <description>"
            )
            return 1
        return _stub_command(f"task {args.action}")

    if args.command == "issue":
        if not args.action:
            print("Usage: ralph issue [add|done|done-all|done-ids] <description>")
            return 1
        return _stub_command(f"issue {args.action}")

    if args.command == "validate":
        return _stub_command("validate")

    if args.command == "compact":
        return _stub_command("compact")

    if args.command == "log":
        return _stub_command("log")

    if args.command == "set-spec":
        return _stub_command("set-spec")

    print(f"ralph: unknown command '{args.command}'", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
