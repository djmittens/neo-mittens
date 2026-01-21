"""Fallback TUI dashboard for terminal output without Textual."""

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Any

from ralph.utils import Colors


@dataclass
class DashboardState:
    """State for the dashboard display."""

    stage: str = ""
    task: str = ""
    iteration: int = 0
    tokens: int = 0
    cost: float = 0.0
    status_message: str = ""


class FallbackDashboard:
    """Simple ANSI-based dashboard for terminals without Textual support.

    Provides a basic terminal UI that refreshes on state changes.
    """

    def __init__(self, config: Optional[dict] = None):
        """Initialize the fallback dashboard.

        Args:
            config: Optional Ralph configuration dict.
        """
        self.config = config or {}
        self.ralph_state: Optional[Any] = None
        self.is_running: bool = False
        self.running_count: int = 0
        self.branch: str = ""

    def render(self) -> List[str]:
        """Render the dashboard to terminal lines.

        Returns:
            List of formatted terminal lines.
        """
        lines = []
        lines.append(f"{Colors.CYAN}{'=' * 60}{Colors.NC}")
        lines.append(f"{Colors.BOLD}Ralph Dashboard{Colors.NC}")
        lines.append(f"{Colors.CYAN}{'=' * 60}{Colors.NC}")

        if self.branch:
            lines.append(f"Branch: {Colors.GREEN}{self.branch}{Colors.NC}")

        status = (
            f"{Colors.GREEN}Running{Colors.NC}"
            if self.is_running
            else f"{Colors.GRAY}Idle{Colors.NC}"
        )
        lines.append(f"Status: {status}")

        if self.running_count > 0:
            lines.append(f"Processes: {self.running_count}")

        if self.ralph_state:
            state = self.ralph_state
            lines.append("")
            lines.append(f"Spec: {getattr(state, 'spec', 'None')}")
            lines.append(
                f"Stage: {getattr(state.config, 'stage', 'Unknown') if hasattr(state, 'config') and state.config else 'Unknown'}"
            )

            pending = getattr(state, "pending", [])
            done = getattr(state, "done", [])
            issues = getattr(state, "issues", [])

            lines.append(f"Tasks: {len(pending)} pending, {len(done)} done")
            lines.append(f"Issues: {len(issues)}")

        lines.append(f"{Colors.CYAN}{'=' * 60}{Colors.NC}")
        lines.append("Press Ctrl+C to exit")

        return lines

    def run_loop(
        self,
        poll_fn: Callable[[], List[str]],
        on_quit: Optional[Callable[[], int]] = None,
        refresh_interval: float = 1.0,
    ) -> int:
        """Run the dashboard loop.

        Args:
            poll_fn: Function to call to poll for updates.
            on_quit: Optional callback when quitting.
            refresh_interval: Seconds between refreshes.

        Returns:
            Exit code.
        """
        import time
        import sys

        try:
            while True:
                # Clear screen
                print("\033[2J\033[H", end="")

                # Poll for updates
                messages = poll_fn()

                # Render dashboard
                for line in self.render():
                    print(line)

                # Show any messages
                if messages:
                    print("")
                    for msg in messages:
                        print(f"  {msg}")

                sys.stdout.flush()
                time.sleep(refresh_interval)

        except KeyboardInterrupt:
            if on_quit:
                return on_quit()
            return 0

        return 0


def render_dashboard(state: DashboardState) -> List[str]:
    """Render a dashboard state to terminal lines.

    Args:
        state: The dashboard state to render.

    Returns:
        List of formatted terminal lines.
    """
    lines = []
    lines.append(f"{Colors.CYAN}{'=' * 60}{Colors.NC}")
    lines.append(f"Stage: {state.stage}")
    lines.append(f"Task: {state.task}")
    lines.append(f"Iteration: {state.iteration}")
    lines.append(f"Tokens: {state.tokens}")
    lines.append(f"Cost: ${state.cost:.4f}")
    if state.status_message:
        lines.append(f"Status: {state.status_message}")
    lines.append(f"{Colors.CYAN}{'=' * 60}{Colors.NC}")
    return lines
