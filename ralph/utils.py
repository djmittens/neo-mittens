"""ANSI color utilities, ID generation, and miscellaneous utilities."""

import random
import re
import string
import time
from typing import Optional


class Colors:
    """ANSI color codes for terminal output."""

    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    MAGENTA = "\033[0;35m"
    CYAN = "\033[0;36m"
    WHITE = "\033[0;37m"
    NC = "\033[0m"  # No Color

    # Extended colors for Ralph ASCII art
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_WHITE = "\033[97m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    DIM = "\033[2m"
    PINK = "\033[38;5;218m"
    SKIN = "\033[38;5;223m"
    HAIR = "\033[38;5;220m"
    SHIRT_BLUE = "\033[38;5;39m"
    SHIRT_DARK = "\033[38;5;25m"


# Dictionary version for dynamic access
COLORS = {
    "red": Colors.RED,
    "green": Colors.GREEN,
    "yellow": Colors.YELLOW,
    "blue": Colors.BLUE,
    "magenta": Colors.MAGENTA,
    "cyan": Colors.CYAN,
    "white": Colors.WHITE,
    "nc": Colors.NC,
    "bright_yellow": Colors.BRIGHT_YELLOW,
    "bright_red": Colors.BRIGHT_RED,
    "bright_white": Colors.BRIGHT_WHITE,
    "bright_blue": Colors.BRIGHT_BLUE,
    "bright_magenta": Colors.BRIGHT_MAGENTA,
    "dim": Colors.DIM,
    "pink": Colors.PINK,
    "skin": Colors.SKIN,
    "hair": Colors.HAIR,
    "shirt_blue": Colors.SHIRT_BLUE,
    "shirt_dark": Colors.SHIRT_DARK,
}


def colored(text: str, color: str) -> str:
    """Apply ANSI color to text.

    Args:
        text: The text to colorize.
        color: Color name (e.g., 'red', 'green', 'blue') or a raw ANSI code.

    Returns:
        The text wrapped in ANSI color codes with reset at the end.

    Example:
        >>> colored("Hello", "red")
        '\\033[0;31mHello\\033[0m'
    """
    color_code = COLORS.get(color.lower(), color)
    return f"{color_code}{text}{Colors.NC}"


def id_generate(prefix: str = "t") -> str:
    """Generate a unique ID with timestamp and random suffix.

    Format: {prefix}-{timestamp_base36}{random} (e.g., t-k5x9ab, i-k5x9cd)

    The timestamp component (2 chars) provides uniqueness across time,
    while the random suffix (4 chars) provides uniqueness within the same second.
    This reduces collision probability when multiple Ralph instances run in parallel.

    Args:
        prefix: Single character prefix ('t' for task, 'i' for issue).

    Returns:
        A unique identifier string.
    """
    chars = string.ascii_lowercase + string.digits
    # Use last 2 chars of base36 timestamp for some time-based uniqueness
    timestamp_part = int(time.time()) % (36 * 36)  # 0-1295, fits in 2 base36 chars
    ts_chars = ""
    for _ in range(2):
        ts_chars = chars[timestamp_part % 36] + ts_chars
        timestamp_part //= 36

    # Add 4 random chars
    random_part = "".join(random.choice(chars) for _ in range(4))
    return f"{prefix}-{ts_chars}{random_part}"


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text.

    Args:
        text: Text potentially containing ANSI escape sequences.

    Returns:
        The text with all ANSI escape codes removed.
    """
    return re.sub(r"\x1b\[[0-9;]*m", "", text)
