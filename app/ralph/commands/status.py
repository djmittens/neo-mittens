"""Ralph status command.

Shows the current status of Ralph for a repository.
"""

from pathlib import Path

from ralph.state import load_state
from ralph.utils import Colors

__all__ = ["cmd_status"]


def cmd_status(config: dict) -> int:
    """Show current Ralph status.

    Args:
        config: Ralph configuration dict with ralph_dir, plan_file, etc.

    Returns:
        Exit code (0 for success, 1 for error).
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
