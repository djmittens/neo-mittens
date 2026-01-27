"""Utility functions and color definitions for Ralph CLI."""

import random
import string
import time


class Colors:
    """ANSI color codes for terminal output."""

    # Basic colors
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    MAGENTA = "\033[0;35m"
    CYAN = "\033[0;36m"
    WHITE = "\033[0;37m"

    # Reset/control
    RESET = "\033[0m"
    NC = "\033[0m"  # No Color (alias for RESET)
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Bright/extended colors
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_WHITE = "\033[97m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_BLACK = "\033[90m"
    GRAY = "\033[90m"  # Alias for BRIGHT_BLACK

    # Ralph ASCII art specific colors
    PINK = "\033[38;5;218m"
    SKIN = "\033[38;5;223m"
    HAIR = "\033[38;5;220m"
    SHIRT_BLUE = "\033[38;5;39m"
    SHIRT_DARK = "\033[38;5;25m"

    # Background colors
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"
    BG_BLACK = "\033[40m"


def gen_id(prefix: str = "t") -> str:
    """Generate a unique ID with timestamp and random suffix.

    Format: {prefix}-{timestamp_base36}{random} (e.g., t-k5x9ab, i-k5x9cd)

    Uses microsecond-precision timestamp (4 chars) plus random suffix (2 chars)
    to minimize collision probability even when generating many IDs quickly.

    Args:
        prefix: Single character prefix for the ID type ('t' for task, 'i' for issue)

    Returns:
        Unique ID string in format {prefix}-{6 alphanumeric chars}
    """
    chars = string.ascii_lowercase + string.digits

    # Use microseconds for better uniqueness in tight loops
    # time.time() * 1000000 gives microseconds, mod 36^4 fits in 4 base36 chars
    timestamp_part = int(time.time() * 1000000) % (36 ** 4)
    ts_chars = ""
    for _ in range(4):
        ts_chars = chars[timestamp_part % 36] + ts_chars
        timestamp_part //= 36

    # Add 2 random chars for extra uniqueness
    random_part = "".join(random.choice(chars) for _ in range(2))
    return f"{prefix}-{ts_chars}{random_part}"
