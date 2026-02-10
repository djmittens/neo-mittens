"""Utility functions and color definitions for Ralph CLI."""

import random
import string
import time
from contextlib import contextmanager
from typing import Generator, Optional


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


class PipelineTimer:
    """Lightweight timing accumulator for pipeline phases.

    Collects elapsed times per named phase so the construct loop
    can print a breakdown at the end of each iteration and session.

    Usage::

        timer = PipelineTimer()
        with timer.phase("acp_session_new"):
            client.prompt(...)
        with timer.phase("reconcile"):
            reconcile_build(...)
        timer.print_summary()
    """

    def __init__(self) -> None:
        self._phases: dict[str, list[float]] = {}

    @contextmanager
    def phase(self, name: str) -> Generator[None, None, None]:
        """Time a named phase.

        Args:
            name: Phase identifier (e.g. "acp_prompt", "reconcile",
                "git_sync", "tix_query").
        """
        t0 = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - t0
            self._phases.setdefault(name, []).append(elapsed)

    def record(self, name: str, elapsed: float) -> None:
        """Record an externally-measured duration.

        Args:
            name: Phase identifier.
            elapsed: Duration in seconds.
        """
        self._phases.setdefault(name, []).append(elapsed)

    def phase_total(self, name: str) -> float:
        """Total seconds for a phase across all calls."""
        return sum(self._phases.get(name, []))

    def phase_count(self, name: str) -> int:
        """Number of calls for a phase."""
        return len(self._phases.get(name, []))

    def summary(self) -> str:
        """Return a one-line summary of all phases, sorted by total time.

        Format: ``phase1=1.23s(x3) phase2=0.45s(x1)``
        """
        items = []
        for name in sorted(
            self._phases, key=lambda n: sum(self._phases[n]), reverse=True,
        ):
            total = sum(self._phases[name])
            count = len(self._phases[name])
            if total < 0.001:
                continue
            items.append(f"{name}={total:.2f}s(x{count})")
        return " ".join(items)

    def print_summary(self, prefix: str = "  Timing:") -> None:
        """Print the summary to stdout if any phases were recorded."""
        s = self.summary()
        if s:
            print(f"{prefix} {s}")

    def reset(self) -> None:
        """Clear all recorded phases."""
        self._phases.clear()
