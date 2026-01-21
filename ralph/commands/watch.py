"""Ralph watch command.

Live progress dashboard for monitoring construct mode.
"""

from ralph.utils import Colors

__all__ = ["cmd_watch"]


def cmd_watch(config: dict) -> int:
    """Live progress dashboard.

    Args:
        config: Ralph configuration dict.

    Returns:
        Exit code (0 for success).
    """
    print(
        f"{Colors.YELLOW}Watch mode not yet implemented in refactored ralph.{Colors.NC}"
    )
    print("Use 'ralph status' or 'ralph query' for now.")
    return 0
