"""Ralph construct command.

Construct mode - main development loop.
"""

import argparse

from ralph.utils import Colors

__all__ = ["cmd_construct"]


def cmd_construct(config: dict, iterations: int, args: argparse.Namespace) -> int:
    """Construct mode - main development loop.

    Args:
        config: Ralph configuration dict.
        iterations: Maximum iterations (0 = unlimited).
        args: Command-line arguments.

    Returns:
        Exit code (0 for success).
    """
    print(
        f"{Colors.YELLOW}Construct mode not yet implemented in refactored ralph.{Colors.NC}"
    )
    print(f"Iterations: {iterations if iterations else 'unlimited'}")
    return 0
