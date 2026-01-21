"""Ralph Wiggum Textual TUI Dashboard.

Uses Textual framework for smooth, optimized rendering with built-in:
- Double-buffered rendering with character-level diffing
- Smooth scrolling with mouse wheel support
- Full ANSI color and emoji preservation
- Reactive UI updates
"""

import asyncio
import os
import re
import select
import subprocess
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static, RichLog
from textual.reactive import reactive
from textual.binding import Binding
from textual import work
from rich.text import Text
from rich.markup import escape

from ralph.tui.art import RALPH_ART
from ralph.state import load_state

if TYPE_CHECKING:
    from ralph.state import RalphState

__all__ = ["RalphDashboard", "OutputLog", "create_textual_app"]

DEFAULT_CONTEXT_WINDOW = 200_000


def get_current_branch() -> str:
    """Get current git branch name.

    Returns:
        The current git branch name, or 'unknown' on error.
    """
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


def count_running_opencode(repo_root: Path) -> int:
    """Count opencode processes spawned by ralph in this repo.

    Args:
        repo_root: The repository root directory to check.

    Returns:
        Number of running opencode processes.
    """
    count = 0
    try:
        result = subprocess.run(
            ["pgrep", "-x", "opencode"], capture_output=True, text=True
        )
        for pid in result.stdout.strip().split("\n"):
            if not pid:
                continue
            try:
                cwd = Path(f"/proc/{pid}/cwd").resolve()
                if not str(cwd).startswith(str(repo_root)):
                    continue
                ppid = Path(f"/proc/{pid}/stat").read_text().split()[3]
                parent_cmdline = (
                    Path(f"/proc/{ppid}/cmdline")
                    .read_bytes()
                    .decode("utf-8", errors="replace")
                )
                if "ralph" in parent_cmdline:
                    count += 1
            except (OSError, PermissionError, FileNotFoundError):
                pass
    except subprocess.CalledProcessError:
        pass
    return count


def parse_cost_line(line: str) -> Optional[tuple]:
    """Parse a cost line from ralph-stream output.

    Args:
        line: Output line to parse.

    Returns:
        Tuple of (cost, tokens_in, tokens_out) or None if not a cost line.
    """
    match = re.search(r"Cost: \$([0-9.]+) \| Tokens: (\d+)in/(\d+)out", line)
    if match:
        return (float(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def read_runtime_iteration(config) -> Optional[int]:
    """Read current iteration number from runtime file.

    Args:
        config: Ralph configuration with runtime_file attribute.

    Returns:
        Current iteration number, or None if not running.
    """
    if hasattr(config, "runtime_file") and config.runtime_file.exists():
        try:
            return int(config.runtime_file.read_text().strip())
        except (ValueError, IOError):
            return None
    return None


class OutputLog(RichLog):
    """Scrollable output log that preserves ANSI colors."""

    BINDINGS = [
        Binding("g", "scroll_home", "Top", show=False),
        Binding("G", "scroll_end", "Bottom", show=False),
        Binding("d", "page_down", "Page Down", show=False),
        Binding("u", "page_up", "Page Up", show=False),
        Binding("ctrl+d", "page_down", "Page Down", show=False),
        Binding("ctrl+u", "page_up", "Page Up", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(
            highlight=False, markup=False, wrap=False, auto_scroll=True, **kwargs
        )
        self._follow_mode = True
        self._pending_scroll = 0
        self._scroll_timer = None

    @property
    def follow_mode(self) -> bool:
        """Whether the log auto-scrolls to follow new content."""
        return self._follow_mode

    @follow_mode.setter
    def follow_mode(self, value: bool):
        self._follow_mode = value
        self.auto_scroll = value

    def toggle_follow(self):
        """Toggle follow mode on/off."""
        self.follow_mode = not self.follow_mode
        if self.follow_mode:
            self.scroll_end(animate=False)

    def _flush_scroll(self):
        """Apply accumulated scroll and reset."""
        if self._pending_scroll != 0:
            self.scroll_relative(y=self._pending_scroll, animate=False)
            self.follow_mode = False
            self._pending_scroll = 0
        self._scroll_timer = None

    def on_key(self, event) -> None:
        """Handle j/k with coalescing for fast key repeat."""
        if event.key == "j":
            self._pending_scroll += 1
            event.prevent_default()
            event.stop()
        elif event.key == "k":
            self._pending_scroll -= 1
            event.prevent_default()
            event.stop()
        else:
            return

        if self._scroll_timer is None:
            self._scroll_timer = self.set_timer(0.016, self._flush_scroll)

    def action_page_down(self):
        """Scroll down half a page."""
        self._flush_scroll()
        self.scroll_relative(y=self.size.height // 2, animate=False)
        self.follow_mode = False

    def action_page_up(self):
        """Scroll up half a page."""
        self._flush_scroll()
        self.scroll_relative(y=-self.size.height // 2, animate=False)
        self.follow_mode = False

    def action_scroll_home(self):
        """Scroll to the top."""
        self._flush_scroll()
        self.scroll_home(animate=False)
        self.follow_mode = False

    def action_scroll_end(self):
        """Scroll to the bottom and enable follow mode."""
        self._flush_scroll()
        self.scroll_end(animate=False)
        self.follow_mode = True

    def on_mouse_scroll_down(self, event) -> None:
        """Disable follow mode on mouse scroll down."""
        self.follow_mode = False

    def on_mouse_scroll_up(self, event) -> None:
        """Disable follow mode on mouse scroll up."""
        self.follow_mode = False


class RalphArtWidget(Static):
    """Widget to display Ralph ASCII art with colors."""

    DEFAULT_CSS = """
    RalphArtWidget {
        width: auto;
        height: auto;
    }
    """

    def __init__(self, art_lines: list, **kwargs):
        super().__init__(**kwargs)
        self._art_lines = art_lines

    def render(self):
        """Render the ASCII art with ANSI colors."""
        return Text.from_ansi("\n".join(self._art_lines))


class StatusPanel(Static):
    """Status information panel."""

    DEFAULT_CSS = """
    StatusPanel {
        width: 100%;
        height: auto;
        padding: 0 1;
    }
    """

    branch = reactive("")
    status_text = reactive("")
    stage_text = reactive("")
    cost_text = reactive("")
    context_text = reactive("")
    progress_text = reactive("")
    spec_text = reactive("")
    task_text = reactive("")
    kill_text = reactive("")

    def render(self):
        """Render the status panel."""
        lines = []
        if self.branch:
            lines.append(f"[green]Branch:[/] {escape(self.branch)}")
        if self.status_text:
            lines.append(self.status_text)
        if self.stage_text:
            lines.append(self.stage_text)
        if self.cost_text:
            lines.append(self.cost_text)
        if self.context_text:
            lines.append(self.context_text)
        lines.append("")
        if self.progress_text:
            lines.append(self.progress_text)
        lines.append("")
        if self.spec_text:
            lines.append(self.spec_text)
        if self.task_text:
            lines.append("[green]Task:[/]")
            lines.append(f"  {escape(self.task_text)}")
        if self.kill_text:
            lines.append("")
            lines.append(self.kill_text)
        return Text.from_markup("\n".join(lines))


class IssuesPanel(Static):
    """Issues display panel."""

    DEFAULT_CSS = """
    IssuesPanel {
        width: 100%;
        height: auto;
        padding: 0 1;
        display: none;
    }
    IssuesPanel.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._issues = []
        self._open_count = 0
        self._fixed_count = 0

    def update_issues(self, issues: list, open_count: int, fixed_count: int):
        """Update the issues display.

        Args:
            issues: List of (status, text) tuples.
            open_count: Number of open issues.
            fixed_count: Number of fixed issues.
        """
        self._issues = issues[:5]
        self._open_count = open_count
        self._fixed_count = fixed_count
        if self._issues:
            self.add_class("visible")
        else:
            self.remove_class("visible")
        self.refresh()

    def render(self):
        """Render the issues panel."""
        if not self._issues:
            return ""
        lines = [
            f"[yellow]Issues:[/] ({self._open_count} open, {self._fixed_count} fixed)"
        ]
        for status, text in self._issues:
            text = re.sub(r"^\*\*\[[A-Z_]+\]\*\*\s*", "", text)
            if status == "fixed":
                lines.append(f"  [green]FIXED[/] {escape(text[:60])}")
            else:
                lines.append(f"  [red]OPEN[/]  {escape(text[:60])}")
        return Text.from_markup("\n".join(lines))


class RalphDashboard(App):
    """Main Ralph Wiggum dashboard application."""

    TITLE = "Ralph Wiggum"

    CSS = """
    Screen {
        background: $surface;
    }

    #header-bar {
        background: $primary;
        color: $text;
        height: 3;
        padding: 0 1;
        content-align: center middle;
    }

    #header-bar Static {
        text-style: bold;
        width: 100%;
        content-align: center middle;
    }

    #main-content {
        height: 1fr;
    }

    #info-panel {
        height: auto;
        max-height: 50%;
        padding: 1 0;
    }

    #ralph-section {
        height: auto;
        width: 100%;
        padding: 0 1;
    }

    #ralph-art {
        width: auto;
        min-width: 20;
    }

    #separator {
        width: 1;
        height: 100%;
        margin: 0 1;
    }

    #status {
        width: 1fr;
    }

    #divider {
        height: 1;
        width: 100%;
        border-top: solid $primary-lighten-2;
    }

    #issues {
        height: auto;
        max-height: 8;
    }

    #output-section {
        height: 1fr;
        border-top: solid $primary-lighten-2;
    }

    #output-header {
        height: 1;
        padding: 0 1;
        background: $surface-darken-1;
    }

    #output-log {
        height: 1fr;
        padding: 0 1;
    }

    #footer-bar {
        height: 1;
        background: $surface-darken-1;
        padding: 0 1;
    }

    .follow-on {
        color: $success;
    }

    .follow-off {
        color: $warning;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("f", "toggle_follow", "Follow"),
        Binding("j", "focus_log_down", "Down", show=False),
        Binding("k", "focus_log_up", "Up", show=False),
    ]

    def __init__(
        self,
        config,
        watch_mode: bool = False,
        iteration: Optional[int] = None,
        **kwargs,
    ):
        """Initialize the dashboard.

        Args:
            config: Ralph configuration with repo_root, plan_file, etc.
            watch_mode: Whether in watch mode (reading from FIFO).
            iteration: Current iteration number, if known.
            **kwargs: Additional arguments for App.
        """
        super().__init__(**kwargs)
        self._config = config
        self._watch_mode = watch_mode
        self._iteration = iteration
        self._cost = 0.0
        self._tokens_in = 0
        self._tokens_out = 0
        self._context_tokens = 0
        self._context_limit = DEFAULT_CONTEXT_WINDOW
        self._branch = ""
        self._is_running = False
        self._running_count = 0
        self._output_lines: deque = deque(maxlen=2000)
        self._fifo_fd = None
        self._process = None
        self._output_buffer = None
        self._stop_requested = False
        self._kills_timeout = 0
        self._kills_context = 0
        self._last_kill_reason = ""
        self._last_kill_activity = ""

    def compose(self) -> ComposeResult:
        """Compose the dashboard layout."""
        with Container(id="header-bar"):
            yield Static(self._get_title())

        with Vertical(id="main-content"):
            with Vertical(id="info-panel"):
                with Horizontal(id="ralph-section"):
                    yield RalphArtWidget(RALPH_ART if RALPH_ART else [], id="ralph-art")
                    yield Static("│", id="separator")
                    yield StatusPanel(id="status")
                yield IssuesPanel(id="issues")

            with Vertical(id="output-section"):
                yield Static("Output: [FOLLOW]", id="output-header")
                yield OutputLog(id="output-log")

        yield Static(
            " q:quit  j/k:scroll  g/G:top/bottom  f:follow  d/u:page",
            id="footer-bar",
        )

    def _get_title(self) -> str:
        """Get the title bar text."""
        ts = datetime.now().strftime("%H:%M:%S")
        kills_str = ""
        if self._kills_timeout > 0 or self._kills_context > 0:
            parts = []
            if self._kills_timeout > 0:
                parts.append(f"T:{self._kills_timeout}")
            if self._kills_context > 0:
                parts.append(f"C:{self._kills_context}")
            kills_str = f" | Kills: {' '.join(parts)}"
        if self._iteration is not None:
            return f"RALPH WIGGUM - Iteration {self._iteration} - {ts}{kills_str}"
        return f"RALPH WIGGUM - {ts}{kills_str}"

    def on_mount(self) -> None:
        """Start background tasks when app mounts."""
        self._branch = get_current_branch()
        self.set_interval(0.1, self._update_display)

        if self._watch_mode:
            self._start_fifo_reader()

        self._update_status_panel()

    def _start_fifo_reader(self):
        """Start reading from FIFO in background."""

        @work(thread=True, exclusive=True)
        async def read_fifo(self):
            while not self._stop_requested:
                if self._fifo_fd is None and hasattr(self._config, "output_fifo"):
                    if self._config.output_fifo.exists():
                        try:
                            self._fifo_fd = os.open(
                                str(self._config.output_fifo), os.O_RDWR | os.O_NONBLOCK
                            )
                        except OSError:
                            pass

                if self._fifo_fd is not None:
                    try:
                        ready, _, _ = select.select([self._fifo_fd], [], [], 0.05)
                        if ready:
                            data = os.read(self._fifo_fd, 8192)
                            if data:
                                for line in data.decode(
                                    "utf-8", errors="replace"
                                ).splitlines():
                                    if line:
                                        self._output_lines.append(line)
                                        cost_info = parse_cost_line(line)
                                        if cost_info:
                                            self._cost = cost_info[0]
                                            self._tokens_in = cost_info[1]
                                            self._tokens_out = cost_info[2]
                                            self._context_tokens = cost_info[1]
                                        self.call_from_thread(self._append_output, line)
                    except OSError:
                        if self._fifo_fd is not None:
                            try:
                                os.close(self._fifo_fd)
                            except OSError:
                                pass
                        self._fifo_fd = None
                else:
                    await asyncio.sleep(0.1)

        read_fifo(self)

    def _append_output(self, line: str):
        """Append a line to output log (called from main thread)."""
        log = self.query_one("#output-log", OutputLog)
        log.write(Text.from_ansi(line))

    def _update_display(self):
        """Periodic display update."""
        if self._watch_mode:
            self._iteration = read_runtime_iteration(self._config)

        header = self.query_one("#header-bar Static", Static)
        header.update(self._get_title())

        if self._watch_mode and hasattr(self._config, "repo_root"):
            self._running_count = count_running_opencode(self._config.repo_root)
            self._is_running = self._running_count > 0

        self._update_status_panel()
        self._update_output_header()

    def _update_status_panel(self):
        """Update the status panel."""
        status = self.query_one("#status", StatusPanel)

        plan_file = None
        if hasattr(self._config, "plan_file"):
            plan_file = self._config.plan_file
        elif isinstance(self._config, dict) and "plan_file" in self._config:
            plan_file = self._config["plan_file"]

        if plan_file and Path(plan_file).exists():
            state = load_state(plan_file)
        else:
            state = None

        status.branch = self._branch

        if self._is_running:
            if self._running_count > 0:
                status.status_text = (
                    f"[green]Status:[/] Running ({self._running_count})"
                )
            else:
                status.status_text = "[green]Status:[/] Running"
        else:
            status.status_text = "[yellow]Status:[/] Stopped"

        if state:
            stage = state.get_stage()
            stage_colors = {
                "PLAN": "magenta",
                "BUILD": "cyan",
                "VERIFY": "yellow",
                "INVESTIGATE": "red",
                "COMPLETE": "green",
            }
            color = stage_colors.get(stage, "white")
            status.stage_text = f"[green]Stage:[/] [{color}]{stage}[/]"
        else:
            status.stage_text = "[green]Stage:[/] --"

        if self._cost > 0:
            status.cost_text = f"[cyan]Cost:[/] ${self._cost:.4f}"
        else:
            status.cost_text = "[cyan]Cost:[/] --"

        if self._context_tokens > 0:
            pct = self._context_tokens / self._context_limit * 100
            if pct >= 90:
                color = "red"
            elif pct >= 70:
                color = "yellow"
            else:
                color = "cyan"
            status.context_text = (
                f"[{color}]Context:[/] {self._context_tokens:,} / "
                f"{self._context_limit:,} ({pct:.0f}%)"
            )
        else:
            status.context_text = ""

        if self._last_kill_reason:
            status.kill_text = f"[red]Last Kill:[/] {self._last_kill_reason}"
            if self._last_kill_activity:
                status.kill_text += f" @ {self._last_kill_activity}"
        else:
            status.kill_text = ""

        if state:
            pending = len(state.pending)
            done = len(state.done)
            status.progress_text = f"[green]Progress:[/] {done} done, {pending} pending"

            if state.spec:
                status.spec_text = f"[green]Spec:[/] {state.spec}"
            else:
                status.spec_text = ""

            next_task = state.get_next_task()
            if next_task:
                status.task_text = next_task.name
            else:
                status.task_text = "(no pending tasks)"

            issues_panel = self.query_one("#issues", IssuesPanel)
            open_issues = [i for i in state.issues if i.status != "fixed"]
            fixed_issues = [i for i in state.issues if i.status == "fixed"]
            issue_items = [
                ("open" if i.status != "fixed" else "fixed", i.description)
                for i in state.issues[:5]
            ]
            issues_panel.update_issues(issue_items, len(open_issues), len(fixed_issues))
        else:
            status.progress_text = "[green]Progress:[/] --"
            status.spec_text = ""
            status.task_text = "(not initialized)"

    def _update_output_header(self):
        """Update output header with scroll/follow status."""
        log = self.query_one("#output-log", OutputLog)
        header = self.query_one("#output-header", Static)

        if log.follow_mode:
            header.update("Output: [green][FOLLOW][/]")
        else:
            header.update("Output: [yellow][SCROLL][/]")

    def action_toggle_follow(self):
        """Toggle follow mode."""
        log = self.query_one("#output-log", OutputLog)
        log.toggle_follow()
        self._update_output_header()

    def action_focus_log_down(self):
        """Scroll log down."""
        log = self.query_one("#output-log", OutputLog)
        log.action_scroll_down()
        self._update_output_header()

    def action_focus_log_up(self):
        """Scroll log up."""
        log = self.query_one("#output-log", OutputLog)
        log.action_scroll_up()
        self._update_output_header()

    def action_quit(self):
        """Quit the application."""
        self._stop_requested = True
        if self._fifo_fd is not None:
            try:
                os.close(self._fifo_fd)
            except OSError:
                pass
        self.exit()

    def set_process(self, process, output_buffer):
        """Set the process to monitor (for run mode).

        Args:
            process: The subprocess to monitor.
            output_buffer: Buffer for collecting output.
        """
        self._process = process
        self._output_buffer = output_buffer
        self._is_running = True

    def add_output_line(self, line: str):
        """Add a line to output (for run mode, called from output thread).

        Args:
            line: Line to add to output.
        """
        self._output_lines.append(line)
        self.call_from_thread(self._append_output, line)

    def check_process_done(self) -> Optional[int]:
        """Check if process is done, return exit code or None.

        Returns:
            Exit code if process is done, None otherwise.
        """
        if self._process is not None:
            ret = self._process.poll()
            if ret is not None:
                self._is_running = False
                return ret
        return None


def create_textual_app():
    """Create and return the Textual app classes.

    Returns:
        Tuple of (RalphDashboard, OutputLog) classes.
    """
    return RalphDashboard, OutputLog
