"""Ralph issue command.

Issue subcommands: add, done, done-all, done-ids.
"""

from typing import Optional

from ralph.models import Issue
from ralph.state import load_state, save_state
from ralph.utils import Colors, gen_id

__all__ = ["cmd_issue"]


def cmd_issue(config: dict, action: str, desc: Optional[str] = None) -> int:
    """Handle issue subcommands.

    Args:
        config: Ralph configuration dict.
        action: Issue action (add, done, done-all, done-ids).
        desc: Issue description or IDs.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    plan_file = config["plan_file"]
    state = load_state(plan_file)

    if action == "done":
        return _issue_done(state, plan_file)

    if action == "done-all":
        return _issue_done_all(state, plan_file)

    if action == "done-ids":
        return _issue_done_ids(state, plan_file, desc)

    if action == "add":
        return _issue_add(state, plan_file, desc)

    print(f"{Colors.RED}Unknown issue action: {action}{Colors.NC}")
    print("Usage: ralph issue [done|done-all|done-ids|add]")
    return 1


def _issue_done(state, plan_file) -> int:
    """Resolve the first issue."""
    if not state.issues:
        print(f"{Colors.YELLOW}No issues{Colors.NC}")
        return 1
    issue = state.issues[0]
    state.issues = state.issues[1:]
    save_state(state, plan_file)
    print(f"{Colors.GREEN}Issue resolved:{Colors.NC} {issue.id}")
    return 0


def _issue_done_all(state, plan_file) -> int:
    """Resolve all issues."""
    if not state.issues:
        print(f"{Colors.YELLOW}No issues{Colors.NC}")
        return 1
    count = len(state.issues)
    state.issues = []
    save_state(state, plan_file)
    print(f"{Colors.GREEN}All issues resolved:{Colors.NC} {count} issues cleared")
    return 0


def _issue_done_ids(state, plan_file, desc: Optional[str]) -> int:
    """Resolve issues by ID."""
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


def _issue_add(state, plan_file, desc: Optional[str]) -> int:
    """Add a new issue."""
    if not desc:
        print(f'{Colors.RED}Usage: ralph issue add "description"{Colors.NC}')
        return 1
    if not state.spec:
        print(f"{Colors.RED}No spec set. Run 'ralph set-spec <file>' first.{Colors.NC}")
        return 1
    issue = Issue(id=gen_id("i"), desc=desc, spec=state.spec)
    state.add_issue(issue)
    save_state(state, plan_file)
    print(f"{Colors.GREEN}Issue added:{Colors.NC} {issue.id} - {desc}")
    return 0
