"""Ralph plan command.

Plan mode - generate implementation plan from spec.
"""

import argparse

from ralph.utils import Colors

__all__ = ["cmd_plan"]


def cmd_plan(config: dict, spec_file: str, args: argparse.Namespace) -> int:
    """Plan mode - generate implementation plan from spec.

    Args:
        config: Ralph configuration dict.
        spec_file: Spec file to plan.
        args: Command-line arguments.

    Returns:
        Exit code (0 for success).
    """
    print(
        f"{Colors.YELLOW}Plan mode not yet implemented in refactored ralph.{Colors.NC}"
    )
    print(f"Spec: {spec_file}")
    return 0
