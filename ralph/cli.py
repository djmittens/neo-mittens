"""Ralph CLI - Argparse setup and command dispatch.

This module provides the main command-line interface for Ralph,
setting up all subcommands and routing to the appropriate handlers.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from ralph.config import get_global_config, GlobalConfig
from ralph.state import load_state, save_state, RalphState
from ralph.utils import Colors


def find_repo_root() -> Optional[Path]:
    """Find the git repository root from the current directory.

    Walks up the directory tree looking for a .git directory.

    Returns:
        Path to the repository root, or None if not in a git repo.
    """
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".git").exists():
            return parent
    return None


def get_ralph_config(repo_root: Path) -> dict:
    """Get Ralph configuration for a repository.

    Args:
        repo_root: Path to the repository root.

    Returns:
        Dictionary with ralph_dir, specs_dir, and plan_file paths.
    """
    gcfg = get_global_config()
    ralph_dir = repo_root / gcfg.ralph_dir
    return {
        "repo_root": repo_root,
        "ralph_dir": ralph_dir,
        "specs_dir": ralph_dir / "specs",
        "plan_file": ralph_dir / "plan.jsonl",
    }


def cmd_status(config: dict) -> int:
    """Show current Ralph status.

    Args:
        config: Ralph configuration dict.

    Returns:
        Exit code.
    """
    plan_file = config["plan_file"]
    if not plan_file.exists():
        print(
            f"{Colors.YELLOW}Ralph not initialized. Run 'ralph init' first.{Colors.NC}"
        )
        return 1

    state = load_state(plan_file)
    print(f"{Colors.CYAN}Spec:{Colors.NC} {state.spec or 'Not set'}")
    print(f"{Colors.CYAN}Stage:{Colors.NC} {state.get_stage()}")
    print(
        f"{Colors.CYAN}Tasks:{Colors.NC} {len(state.pending)} pending, {len(state.done)} done"
    )
    print(f"{Colors.CYAN}Issues:{Colors.NC} {len(state.issues)}")
    return 0


def cmd_config_show() -> int:
    """Show global configuration.

    Returns:
        Exit code.
    """
    gcfg = get_global_config()
    print(f"{Colors.CYAN}Global Configuration:{Colors.NC}")
    print(f"  Model: {gcfg.model}")
    print(f"  Context window: {gcfg.context_window:,}")
    print(f"  Stage timeout: {gcfg.stage_timeout_ms:,}ms")
    print(f"  Max failures: {gcfg.max_failures}")
    print(f"  Profile: {gcfg._profile_name}")
    return 0


def cmd_query(
    config: dict, subcommand: Optional[str] = None, done_only: bool = False
) -> int:
    """Query current state as JSON.

    Args:
        config: Ralph configuration dict.
        subcommand: Optional subquery (stage, tasks, issues, iteration, etc.)
        done_only: If True, only show done tasks.

    Returns:
        Exit code.
    """
    plan_file = config["plan_file"]
    state = load_state(plan_file)

    if subcommand == "stage":
        print(state.get_stage())
        return 0

    if subcommand == "tasks":
        tasks = state.done if done_only else state.pending
        print(json.dumps([t.to_dict() for t in tasks], indent=2))
        return 0

    if subcommand == "issues":
        print(json.dumps([i.to_dict() for i in state.issues], indent=2))
        return 0

    if subcommand == "iteration":
        print("0")
        return 0

    result = state.to_dict()
    if state.tasks:
        next_task = state.get_next_task()
        if next_task:
            result["current_task"] = next_task.id
    print(json.dumps(result, indent=2))
    return 0


def cmd_task(
    config: dict, action: str, arg2: Optional[str] = None, arg3: Optional[str] = None
) -> int:
    """Handle task subcommands.

    Args:
        config: Ralph configuration dict.
        action: Task action (add, done, accept, reject, delete, prioritize).
        arg2: Additional argument (task description or task ID).
        arg3: Third argument (e.g., reject reason).

    Returns:
        Exit code.
    """
    plan_file = config["plan_file"]
    state = load_state(plan_file)

    if action == "add":
        if not arg2:
            print(
                f"{Colors.RED}Usage: ralph task add '<json>' or ralph task add 'description'{Colors.NC}"
            )
            return 1
        from ralph.models import Task
        from ralph.utils import id_generate

        try:
            data = json.loads(arg2)
            task = Task(
                id=id_generate("t"),
                name=data.get("name", ""),
                spec=state.spec or "",
                notes=data.get("notes"),
                accept=data.get("accept"),
                deps=data.get("deps"),
                priority=data.get("priority"),
                parent=data.get("parent"),
                created_from=data.get("created_from"),
            )
        except json.JSONDecodeError:
            task = Task(
                id=id_generate("t"),
                name=arg2,
                spec=state.spec or "",
            )
        state.add_task(task)
        save_state(state, plan_file)
        print(f"{Colors.GREEN}Task added:{Colors.NC} {task.id} - {task.name}")
        return 0

    if action == "done":
        task_id = arg2
        if task_id:
            task = state.get_task_by_id(task_id)
        else:
            task = state.get_next_task()

        if not task:
            print(f"{Colors.YELLOW}No pending tasks{Colors.NC}")
            return 1

        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=config["repo_root"],
        )
        commit_hash = result.stdout.strip() if result.returncode == 0 else None

        task.status = "d"
        task.done_at = commit_hash
        save_state(state, plan_file)

        subprocess.run(
            ["git", "add", str(plan_file)], cwd=config["repo_root"], check=False
        )
        subprocess.run(
            ["git", "commit", "-m", f"ralph: task done {task.id}"],
            cwd=config["repo_root"],
            check=False,
        )

        print(f"{Colors.GREEN}Task done:{Colors.NC} {task.id} - {task.name}")
        return 0

    if action == "accept":
        task_id = arg2
        if task_id:
            task = state.get_task_by_id(task_id)
            if not task:
                print(f"{Colors.RED}Task not found: {task_id}{Colors.NC}")
                return 1
            if task.status != "d":
                print(f"{Colors.RED}Task not done: {task_id}{Colors.NC}")
                return 1
            state.tasks = [t for t in state.tasks if t.id != task_id]
            save_state(state, plan_file)
            print(f"{Colors.GREEN}Task accepted:{Colors.NC} {task_id}")
        else:
            done_tasks = state.done
            if not done_tasks:
                print(f"{Colors.YELLOW}No done tasks to accept{Colors.NC}")
                return 1
            state.tasks = [t for t in state.tasks if t.status != "d"]
            save_state(state, plan_file)
            print(f"{Colors.GREEN}Accepted {len(done_tasks)} tasks{Colors.NC}")
        return 0

    if action == "reject":
        task_id = arg2
        reason = arg3 or "No reason provided"

        if task_id:
            task = state.get_task_by_id(task_id)
        else:
            done_tasks = state.done
            task = done_tasks[0] if done_tasks else None

        if not task:
            print(f"{Colors.RED}No task to reject{Colors.NC}")
            return 1

        from ralph.models import Tombstone

        tombstone = Tombstone(
            id=task.id,
            done_at=task.done_at or "",
            reason=reason,
            tombstone_type="reject",
        )
        state.add_tombstone(tombstone)
        task.status = "p"
        task.reject_reason = reason
        save_state(state, plan_file)
        print(f"{Colors.YELLOW}Task rejected:{Colors.NC} {task.id} - {reason}")
        return 0

    if action == "delete":
        task_id = arg2
        if not task_id:
            print(f"{Colors.RED}Usage: ralph task delete <task-id>{Colors.NC}")
            return 1
        task = state.get_task_by_id(task_id)
        if not task:
            print(f"{Colors.RED}Task not found: {task_id}{Colors.NC}")
            return 1
        state.tasks = [t for t in state.tasks if t.id != task_id]
        save_state(state, plan_file)
        print(f"{Colors.GREEN}Task deleted:{Colors.NC} {task_id}")
        return 0

    if action == "prioritize":
        task_id = arg2
        priority = arg3
        if not task_id or not priority:
            print(
                f"{Colors.RED}Usage: ralph task prioritize <task-id> <high|medium|low>{Colors.NC}"
            )
            return 1
        task = state.get_task_by_id(task_id)
        if not task:
            print(f"{Colors.RED}Task not found: {task_id}{Colors.NC}")
            return 1
        task.priority = priority
        save_state(state, plan_file)
        print(f"{Colors.GREEN}Task prioritized:{Colors.NC} {task_id} -> {priority}")
        return 0

    print(f"{Colors.RED}Unknown task action: {action}{Colors.NC}")
    print("Usage: ralph task [add|done|accept|reject|delete|prioritize]")
    return 1


def cmd_issue(config: dict, action: str, desc: Optional[str] = None) -> int:
    """Handle issue subcommands.

    Args:
        config: Ralph configuration dict.
        action: Issue action (add, done, done-all, done-ids).
        desc: Issue description or IDs.

    Returns:
        Exit code.
    """
    plan_file = config["plan_file"]
    state = load_state(plan_file)

    if action == "done":
        if not state.issues:
            print(f"{Colors.YELLOW}No issues{Colors.NC}")
            return 1
        issue = state.issues[0]
        state.issues = state.issues[1:]
        save_state(state, plan_file)
        print(f"{Colors.GREEN}Issue resolved:{Colors.NC} {issue.id}")
        return 0

    if action == "done-all":
        if not state.issues:
            print(f"{Colors.YELLOW}No issues{Colors.NC}")
            return 1
        count = len(state.issues)
        state.issues = []
        save_state(state, plan_file)
        print(f"{Colors.GREEN}All issues resolved:{Colors.NC} {count} issues cleared")
        return 0

    if action == "done-ids":
        if not desc:
            print(f"{Colors.RED}Usage: ralph issue done-ids <id1> <id2> ...{Colors.NC}")
            return 1
        ids_to_remove = set(desc.split())
        if not state.issues:
            print(f"{Colors.YELLOW}No issues{Colors.NC}")
            return 1
        original_count = len(state.issues)
        state.issues = [i for i in state.issues if i.id not in ids_to_remove]
        removed_count = original_count - len(state.issues)
        if removed_count > 0:
            save_state(state, plan_file)
            print(
                f"{Colors.GREEN}Issues resolved:{Colors.NC} {removed_count} issues cleared"
            )
        else:
            print(f"{Colors.YELLOW}No matching issue IDs found{Colors.NC}")
            return 1
        return 0

    if action == "add":
        if not desc:
            print(f'{Colors.RED}Usage: ralph issue add "description"{Colors.NC}')
            return 1
        if not state.spec:
            print(
                f"{Colors.RED}No spec set. Run 'ralph set-spec <file>' first.{Colors.NC}"
            )
            return 1
        from ralph.models import Issue
        from ralph.utils import id_generate

        issue = Issue(id=id_generate("i"), desc=desc, spec=state.spec)
        state.add_issue(issue)
        save_state(state, plan_file)
        print(f"{Colors.GREEN}Issue added:{Colors.NC} {issue.id} - {desc}")
        return 0

    print(f"{Colors.RED}Unknown issue action: {action}{Colors.NC}")
    print("Usage: ralph issue [done|done-all|done-ids|add]")
    return 1


def cmd_stream() -> int:
    """Stream command - pipe opencode JSON for pretty output.

    Reads from stdin and pretty-prints JSON stream.

    Returns:
        Exit code.
    """
    import select

    print(f"{Colors.CYAN}Waiting for JSON stream on stdin...{Colors.NC}")
    print(f"{Colors.DIM}(Pipe opencode output here){Colors.NC}")

    try:
        while True:
            if select.select([sys.stdin], [], [], 0.1)[0]:
                line = sys.stdin.readline()
                if not line:
                    break
                try:
                    data = json.loads(line)
                    if "type" in data:
                        msg_type = data.get("type", "")
                        if msg_type == "assistant":
                            content = data.get("content", "")
                            print(content, end="", flush=True)
                        elif msg_type == "tool_use":
                            tool = data.get("name", "unknown")
                            print(
                                f"\n{Colors.DIM}[Tool: {tool}]{Colors.NC}", flush=True
                            )
                except json.JSONDecodeError:
                    print(line, end="", flush=True)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Stream ended.{Colors.NC}")

    return 0


def cmd_watch(config: dict) -> int:
    """Live progress dashboard.

    Args:
        config: Ralph configuration dict.

    Returns:
        Exit code.
    """
    print(
        f"{Colors.YELLOW}Watch mode not yet implemented in refactored ralph.{Colors.NC}"
    )
    print("Use 'ralph status' or 'ralph query' for now.")
    return 0


def cmd_plan(config: dict, spec_file: str, args: argparse.Namespace) -> int:
    """Plan mode - generate implementation plan from spec.

    Args:
        config: Ralph configuration dict.
        spec_file: Spec file to plan.
        args: Command-line arguments.

    Returns:
        Exit code.
    """
    print(
        f"{Colors.YELLOW}Plan mode not yet implemented in refactored ralph.{Colors.NC}"
    )
    print(f"Spec: {spec_file}")
    return 0


def cmd_construct(config: dict, iterations: int, args: argparse.Namespace) -> int:
    """Construct mode - main development loop.

    Args:
        config: Ralph configuration dict.
        iterations: Maximum iterations (0 = unlimited).
        args: Command-line arguments.

    Returns:
        Exit code.
    """
    print(
        f"{Colors.YELLOW}Construct mode not yet implemented in refactored ralph.{Colors.NC}"
    )
    print(f"Iterations: {iterations if iterations else 'unlimited'}")
    return 0


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser with all subcommands.

    Returns:
        Configured ArgumentParser instance.
    """
    gcfg = get_global_config()

    parser = argparse.ArgumentParser(
        description="Ralph Wiggum - Autonomous AI Development Loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ralph init                    Initialize in current repo
  ralph plan spec.md            Plan tasks for a specific spec
  ralph construct               Construct mode, unlimited (Ctrl+C to stop)
  ralph construct 10            Construct mode, max 10 iterations
  ralph config                  Show global config (model, timeouts, etc.)
  ralph query                   Show current state as JSON
  ralph query stage             Show current stage (PLAN/BUILD/VERIFY/etc)
  ralph query iteration         Show current iteration number
  ralph task done               Mark first pending task as done
  ralph task add "description"  Add a new task
  ralph task accept             Accept all done tasks (after verification)
  ralph issue add "description" Add a discovered issue
  ralph issue done              Resolve first issue
  ralph set-spec spec.md        Set current spec
  ralph watch                   Live progress dashboard
  ralph stream                  Pipe opencode JSON for pretty output
        """,
    )

    parser.add_argument(
        "command",
        nargs="?",
        default="construct",
        help="Command: init, plan, construct, config, query, task, issue, set-spec, status, watch, stream",
    )
    parser.add_argument("arg", nargs="?", default=None, help="Subcommand or argument")
    parser.add_argument(
        "arg2",
        nargs="?",
        default=None,
        help="Additional argument (e.g., task description)",
    )
    parser.add_argument(
        "arg3", nargs="?", default=None, help="Third argument (e.g., reject reason)"
    )
    parser.add_argument(
        "--max-cost", type=float, default=0, help="Stop when cost exceeds $N"
    )
    parser.add_argument(
        "--max-failures",
        type=int,
        default=gcfg.max_failures,
        help=f"Circuit breaker: stop after N consecutive failures (default: {gcfg.max_failures})",
    )
    parser.add_argument(
        "--completion-promise",
        type=str,
        default="",
        help="Stop when output contains this text",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=gcfg.stage_timeout_ms,
        help=f"Kill stage after N milliseconds (default: {gcfg.stage_timeout_ms}ms)",
    )
    parser.add_argument(
        "--context-limit",
        type=int,
        default=gcfg.context_window,
        help=f"Context window size in tokens (default: {gcfg.context_window})",
    )
    parser.add_argument(
        "--no-ui",
        action="store_true",
        help="Disable interactive dashboard, show streaming output",
    )
    parser.add_argument("--all", action="store_true", help="For log: show all history")
    parser.add_argument(
        "--done", action="store_true", help="For query tasks: show only done tasks"
    )
    parser.add_argument(
        "--spec", type=str, default=None, help="For log: filter by spec"
    )
    parser.add_argument(
        "--branch", type=str, default=None, help="For log: filter by branch"
    )
    parser.add_argument(
        "--since", type=str, default=None, help="For log: filter since date/commit"
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="For construct: max iterations (0 = unlimited)",
    )
    parser.add_argument(
        "--profile",
        "-p",
        type=str,
        default=None,
        help="Cost profile: budget, balanced, hybrid, cost_smart, quality (or set RALPH_PROFILE)",
    )
    parser.add_argument("--version", action="store_true", help="Show version and exit")

    return parser


def main() -> int:
    """Main entry point for the Ralph CLI.

    Parses arguments and dispatches to the appropriate command handler.

    Returns:
        Exit code.
    """
    parser = create_parser()
    args = parser.parse_args()

    if args.version:
        from ralph import __version__

        print(f"ralph {__version__}")
        return 0

    if args.command and args.command.isdigit():
        args.arg = args.command
        args.command = "construct"

    iterations = 0
    if args.max_iterations is not None:
        iterations = args.max_iterations
    elif args.arg and args.arg.isdigit():
        iterations = int(args.arg)

    if args.command == "stream":
        return cmd_stream()

    repo_root = find_repo_root()
    if not repo_root:
        print(f"{Colors.RED}Error: Not in a git repository{Colors.NC}")
        return 1

    config = get_ralph_config(repo_root)

    if args.command == "init":
        from ralph.commands import cmd_init

        return cmd_init(repo_root)

    if args.command == "config":
        return cmd_config_show()

    if args.command == "status":
        return cmd_status(config)

    if args.command == "query":
        return cmd_query(config, args.arg, done_only=args.done)

    if args.command == "task":
        if not args.arg:
            print(
                f"{Colors.RED}Usage: ralph task [done|add|accept|reject|delete|prioritize]{Colors.NC}"
            )
            return 1
        return cmd_task(config, args.arg, args.arg2, args.arg3)

    if args.command == "issue":
        if not args.arg:
            print(
                f"{Colors.RED}Usage: ralph issue [done|done-all|done-ids|add]{Colors.NC}"
            )
            return 1
        return cmd_issue(config, args.arg, args.arg2)

    if args.command == "set-spec":
        if not args.arg:
            print(f"{Colors.RED}Usage: ralph set-spec <spec.md>{Colors.NC}")
            return 1
        plan_file = config["plan_file"]
        state = load_state(plan_file)
        specs_dir = config["specs_dir"]
        spec_path = Path(args.arg)
        if not spec_path.is_absolute() and not spec_path.exists():
            spec_path = specs_dir / args.arg
            if not spec_path.exists() and not args.arg.endswith(".md"):
                spec_path = specs_dir / f"{args.arg}.md"
        if not spec_path.exists():
            print(f"{Colors.RED}Spec not found: {args.arg}{Colors.NC}")
            return 1
        state.spec = spec_path.name
        state.tasks = []
        state.tombstones = []
        save_state(state, plan_file)
        print(f"{Colors.GREEN}Spec set:{Colors.NC} {spec_path.name}")
        return 0

    if args.command == "watch":
        return cmd_watch(config)

    if args.command == "plan":
        if not args.arg:
            specs_dir = config["specs_dir"]
            specs = list(specs_dir.glob("*.md")) if specs_dir.exists() else []
            if not specs:
                print(f"{Colors.RED}No specs found in ralph/specs/{Colors.NC}")
                print("Create a spec file first, e.g.: ralph/specs/my-feature.md")
                return 1
            print(f"{Colors.YELLOW}Usage: ralph plan <spec.md>{Colors.NC}")
            print()
            print("Available specs:")
            for spec in sorted(specs):
                print(f"  {spec.name}")
            return 1
        return cmd_plan(config, args.arg, args)

    if args.command in ("construct", "build", ""):
        return cmd_construct(config, iterations, args)

    if args.command == "help":
        parser.print_help()
        return 0

    print(f"{Colors.RED}Unknown command: {args.command}{Colors.NC}")
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
