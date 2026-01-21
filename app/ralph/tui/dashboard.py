from __future__ import annotations

import typing
from typing import Optional, Callable, ClassVar, Union, Any

# Lazy loading Textual imports
try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, ScrollableContainer
    from textual.widgets import Static, Header, Footer, Log, DataTable
    from textual.widgets import Button
    from textual.widget import Widget
    from textual.reactive import Reactive
    from textual.scroll_view import ScrollView
    from rich.text import Text

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

    # Stub classes to prevent import errors
    def var(x: Any) -> Any:
        return x

    class App:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class Widget:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class Static:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class Reactive:  # type: ignore
        pass

    class Widget:  # type: ignore
        pass

    class Static:  # type: ignore
        pass

    class Reactive:  # type: ignore
        pass


from ralph.utils import Colors
from ralph.tui.art import get_ralph_art


class RalphArtWidget(Static):
    """Display Ralph's ASCII art in the dashboard."""

    def on_mount(self) -> None:
        """Set initial art on mount."""
        self.update(get_ralph_art())


class StatusPanel(Static):
    """Display current Ralph workflow status."""

    stage: Reactive[str] = var("INIT")
    task_name: Reactive[str] = var("No Task")
    iteration: Reactive[int] = var(0)
    tokens_used: Reactive[int] = var(0)
    total_cost: Reactive[float] = var(0.0)

    def compose(self) -> ComposeResult:
        yield Static("Status", classes="panel-title")
        yield DataTable(id="status-table")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Metric", "Value")
        table.add_rows(
            [
                ["Stage", self.stage],
                ["Task", self.task_name],
                ["Iteration", str(self.iteration)],
                ["Tokens", str(self.tokens_used)],
                ["Total Cost", f"${self.total_cost:.2f}"],
            ]
        )

    def update_status(
        self,
        stage: str,
        task_name: str,
        iteration: int,
        tokens_used: int,
        total_cost: float,
    ) -> None:
        """Update the status panel with current workflow metrics."""
        self.stage = stage
        self.task_name = task_name
        self.iteration = iteration
        self.tokens_used = tokens_used
        self.total_cost = total_cost

        table = self.query_one(DataTable)
        table.update_cell_at((0, 1), str(stage))
        table.update_cell_at((1, 1), task_name)
        table.update_cell_at((2, 1), str(iteration))
        table.update_cell_at((3, 1), str(tokens_used))
        table.update_cell_at((4, 1), f"${total_cost:.2f}")


class IssuesPanel(Static):
    """Display list of current issues in Ralph workflow."""

    issues: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Static("Issues", classes="panel-title")
        yield ScrollableContainer(id="issues-list")

    def add_issue(self, issue: dict) -> None:
        """Add a new issue to the panel."""
        self.issues.append(issue)
        issues_list = self.query_one("#issues-list")
        issues_list.mount(Static(f"- {issue['description']}"))

    def clear_issues(self) -> None:
        """Clear all issues."""
        self.issues.clear()
        issues_list = self.query_one("#issues-list")
        issues_list.remove_children()


if TEXTUAL_AVAILABLE:

    class OutputLog(Log):
        """Custom log widget with enhanced output tracking."""

        max_lines: ClassVar[int] = 1000
        auto_scroll: Reactive[bool] = var(True)

        def on_mount(self) -> None:
            """Set initial auto-scroll behavior."""
            self.styles.color = "white"

        def write(self, message: str, level: str = "info") -> None:
            """
            Write a message to the log with optional log level styling.

            Args:
                message: Log message to display
                level: Log level (info, warning, error)
            """
            color_map = {"info": "white", "warning": "yellow", "error": "red"}
            styled_msg = Text(message, style=color_map.get(level, "white"))
            self.write_line(styled_msg)

            # Maintain max lines
            lines = getattr(self, "lines", [])
            if len(lines) > self.max_lines:
                self.lines = lines[-self.max_lines :]  # type: ignore[attr-defined]

    class RalphDashboard(App):
        """
        Main dashboard for Ralph workflow tracking.
        Provides real-time insights into the workflow process.
        """

        CSS = """
        Screen {
            layout: grid;
            grid-columns: 1fr 1fr;
            grid-rows: 3fr 1fr;
            background: $surface;
        }
        
        #art-panel {
            grid-column: 1;
            grid-row: 1;
            border: tall $background;
        }
        
        #status-panel {
            grid-column: 2;
            grid-row: 1;
            border: tall $background;
            overflow-y: auto;
        }
        
        #output-log {
            grid-column: 1 / 3;
            grid-row: 2;
            border: tall $background;
            background: $panel;
        }
        
        #issues-panel {
            grid-column: 1 / 3;
            grid-row: 3;
            border: tall $background;
            max-height: 20%;
        }
        
        .panel-title {
            text-align: center;
            background: $boost;
            color: $text-muted;
            padding: 1 2;
        }
        """

        def compose(self) -> ComposeResult:
            """Compose the dashboard layout."""
            yield Header()
            with Container():
                yield RalphArtWidget(id="art-panel")
                yield StatusPanel(id="status-panel")
                yield OutputLog(id="output-log")
                yield IssuesPanel(id="issues-panel")
            yield Footer()

else:

    class OutputLog:  # type: ignore
        """Stub OutputLog when textual not available."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class RalphDashboard:  # type: ignore
        """Stub RalphDashboard when textual not available."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError(
                "Textual library not available. Install with: pip install textual"
            )


def _create_textual_app() -> typing.Tuple[typing.Type[App], typing.Type]:
    """
    Create a Textual app for Ralph workflow dashboard.
    Kept for backwards compatibility.

    Returns:
        A tuple of RalphDashboard class and OutputLog class.
    """
    if not TEXTUAL_AVAILABLE:
        raise ImportError("Textual library not available. Dashboard cannot be created.")

    return RalphDashboard, OutputLog


# Export classes at module level
__all__ = ["RalphDashboard", "OutputLog", "_create_textual_app", "TEXTUAL_AVAILABLE"]
