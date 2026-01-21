"""Ralph config command.

Shows the global configuration.
"""

from ralph.config import get_global_config
from ralph.utils import Colors

__all__ = ["cmd_config"]


def cmd_config() -> int:
    """Show global configuration.

    Returns:
        Exit code (0 for success).
    """
    gcfg = get_global_config()
    print(f"{Colors.CYAN}Global Configuration:{Colors.NC}")
    print(f"  Model: {gcfg.model}")
    print(f"  Context window: {gcfg.context_window:,}")
    print(f"  Stage timeout: {gcfg.stage_timeout_ms:,}ms")
    print(f"  Max failures: {gcfg.max_failures}")
    print(f"  Profile: {gcfg.profile}")
    return 0
