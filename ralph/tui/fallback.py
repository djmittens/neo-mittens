"""ANSI fallback dashboard for terminals without Textual support.

This module provides a simpler ANSI-based dashboard that works in any terminal.
It displays the same information as the Textual dashboard but uses standard
ANSI escape codes for rendering.
"""

import select
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Optional
from ralph.state import load_state
from ralph.tui.art import RALPH_ART, RALPH_WIDTH
from ralph.tui.dashboard import parse_cost_line
from ralph.utils import Colors

if TYPE_CHECKING:
    from ralph.state import RalphState

__all__ = [
    "DashboardState",
    "FallbackDashboard",
    "render_dashboard",
    "SKELETON_FRAMES",
    "DEFAULT_CONTEXT_WINDOW",
]

DEFAULT_CONTEXT_WINDOW = 200_000

SKELETON_FRAMES = [
    "\033[90m░░░░░░░░░░░░░░░░░░░░\033[0m",
    "\033[90m█░░░░░░░░░░░░░░░░░░░\033[0m",
    "\033[90m▓█░░░░░░░░░░░░░░░░░░\033[0m",
    "\033[90m▒▓█░░░░░░░░░░░░░░░░░\033[0m",
    "\033[90m░▒▓█░░░░░░░░░░░░░░░░\033[0m",
    "\033[90m░░▒▓█░░░░░░░░░░░░░░░\033[0m",
    "\033[90m░░░▒▓█░░░░░░░░░░░░░░\033[0m",
    "\033[90m░░░░▒▓█░░░░░░░░░░░░░\033[0m",
    "\033[90m░░░░░▒▓█░░░░░░░░░░░░\033[0m",
    "\033[90m░░░░░░▒▓█░░░░░░░░░░░\033[0m",
    "\033[90m░░░░░░░▒▓█░░░░░░░░░░\033[0m",
    "\033[90m░░░░░░░░▒▓█░░░░░░░░░\033[0m",
    "\033[90m░░░░░░░░░▒▓█░░░░░░░░\033[0m",
    "\033[90m░░░░░░░░░░▒▓█░░░░░░░\033[0m",
    "\033[90m░░░░░░░░░░░▒▓█░░░░░░\033[0m",
    "\033[90m░░░░░░░░░░░░▒▓█░░░░░\033[0m",
    "\033[90m░░░░░░░░░░░░░▒▓█░░░░\033[0m",
    "\033[90m░░░░░░░░░░░░░░▒▓█░░░\033[0m",
    "\033[90m░░░░░░░░░░░░░░░▒▓█░░\033[0m",
    "\033[90m░░░░░░░░░░░░░░░░▒▓█░\033[0m",
    "\033[90m░░░░░░░░░░░░░░░░░▒▓█\033[0m",
    "\033[90m░░░░░░░░░░░░░░░░░░▒▓\033[0m",
    "\033[90m░░░░░░░░░░░░░░░░░░░▒\033[0m",
    "\033[90m░░░░░░░░░░░░░░░░░░░░\033[0m",
]


@dataclass
class DashboardState:
    """State for rendering the dashboard."""

    config: Any  # Dict with plan_file, repo_root, etc.
    branch: str
    cost: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    context_tokens: int = 0
    context_limit: int = DEFAULT_CONTEXT_WINDOW
    iteration: Optional[int] = None
    output_lines: list[str] = field(default_factory=list)
    is_running: bool = False
    running_count: int = 0
    footer_text: str = "Watching..."
    scroll_offset: int = 0
    auto_scroll: bool = True
    stage: str = ""
    kills_timeout: int = 0
    kills_context: int = 0
    last_kill_reason: str = ""
    last_kill_activity: str = ""
    skeleton_frame: Optional[int] = None
    ralph_state: Optional["RalphState"] = None


class FallbackDashboard:
    """Shared ANSI fallback dashboard for watch and build modes."""

    def __init__(self, config: Any, iteration: Optional[int] = None) -> None:
        """Initialize the fallback dashboard.

        Args:
            config: Ralph configuration.
            iteration: Optional current iteration number.
        """
        self.config = config
        self.iteration = iteration
        self.output_lines: deque[str] = deque(maxlen=2000)
        self.scroll_offset = 0
        self.auto_scroll = True
        self.old_settings = None
        self.term_width = 80
        self.term_height = 24

        self.cost = 0.0
        self.tokens_in = 0
        self.tokens_out = 0
        self.context_tokens = 0
        self.context_limit = DEFAULT_CONTEXT_WINDOW
        self.branch = ""
        self.is_running = False
        self.running_count = 0
        self.kills_timeout = 0
        self.kills_context = 0
        self.last_kill_reason = ""
        self.last_kill_activity = ""
        self.skeleton_frame: Optional[int] = None
        self.ralph_state: Optional["RalphState"] = None

    def get_input(self) -> Optional[str | tuple[str, int]]:
        """Non-blocking keyboard input with coalescing for scroll keys.

        Returns:
            None if no input, str for single actions, or ('scroll', delta) tuple.
        """
        scroll_delta = 0
        last_action: Optional[str] = None

        try:
            while True:
                ready, _, _ = select.select([sys.stdin], [], [], 0)
                if not ready:
                    break

                ch = sys.stdin.read(1)
                if ch in ("q", "Q"):
                    return "quit"
                elif ch == "j":
                    scroll_delta += 1
                elif ch == "k":
                    scroll_delta -= 1
                elif ch == "g":
                    last_action = "scroll_top"
                    scroll_delta = 0
                elif ch == "G":
                    last_action = "scroll_bottom"
                    scroll_delta = 0
                elif ch == "d":
                    last_action = "page_down"
                elif ch == "u":
                    last_action = "page_up"
                elif ch in ("f", "F"):
                    last_action = "toggle_follow"
                elif ch == "\x1b":
                    ready2, _, _ = select.select([sys.stdin], [], [], 0.01)
                    if ready2:
                        seq = sys.stdin.read(2)
                        if seq == "[A":
                            scroll_delta -= 1
                        elif seq == "[B":
                            scroll_delta += 1
                        elif seq == "[5":
                            sys.stdin.read(1)
                            last_action = "page_up"
                        elif seq == "[6":
                            sys.stdin.read(1)
                            last_action = "page_down"
        except Exception:
            pass

        if scroll_delta != 0:
            return ("scroll", scroll_delta)
        return last_action

    def handle_action(self, action: Optional[str | tuple[str, int]]) -> bool:
        """Handle a keyboard action.

        Args:
            action: Either a string action or ('scroll', delta) tuple.

        Returns:
            True if should quit, False otherwise.
        """
        import shutil

        self.term_width, self.term_height = shutil.get_terminal_size((80, 24))
        viewport_height = max(1, self.term_height - 20)
        max_offset = max(0, len(self.output_lines) - viewport_height)

        if isinstance(action, tuple) and action[0] == "scroll":
            delta = action[1]
            self.scroll_offset = max(0, min(self.scroll_offset + delta, max_offset))
            self.auto_scroll = self.scroll_offset >= max_offset
            return False

        if action == "quit":
            return True
        elif action == "scroll_top":
            self.scroll_offset = 0
            self.auto_scroll = False
        elif action == "scroll_bottom":
            self.scroll_offset = max_offset
            self.auto_scroll = True
        elif action == "page_down":
            self.scroll_offset = min(
                self.scroll_offset + viewport_height // 2, max_offset
            )
            self.auto_scroll = self.scroll_offset >= max_offset
        elif action == "page_up":
            self.scroll_offset = max(self.scroll_offset - viewport_height // 2, 0)
            self.auto_scroll = False
        elif action == "toggle_follow":
            self.auto_scroll = not self.auto_scroll
            if self.auto_scroll:
                self.scroll_offset = max_offset
        return False

    def render(self) -> None:
        """Render the dashboard to the terminal."""
        import shutil

        self.term_width, self.term_height = shutil.get_terminal_size((80, 24))
        viewport_height = max(1, self.term_height - 20)

        if self.auto_scroll:
            self.scroll_offset = max(0, len(self.output_lines) - viewport_height)

        visible_output = list(self.output_lines)[
            self.scroll_offset : self.scroll_offset + viewport_height
        ]

        if len(self.output_lines) > viewport_height:
            scroll_info = f"[{self.scroll_offset + 1}-{min(self.scroll_offset + viewport_height, len(self.output_lines))}/{len(self.output_lines)}]"
            scroll_info += " FOLLOW" if self.auto_scroll else " SCROLL"
        else:
            scroll_info = "FOLLOW" if self.auto_scroll else ""

        state = DashboardState(
            config=self.config,
            branch=self.branch,
            cost=self.cost,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            context_tokens=self.context_tokens,
            context_limit=self.context_limit,
            iteration=self.iteration,
            output_lines=visible_output,
            is_running=self.is_running,
            running_count=self.running_count,
            footer_text=f"q:quit j/k:scroll g/G:top/bot f:follow | {scroll_info}",
            kills_timeout=self.kills_timeout,
            kills_context=self.kills_context,
            last_kill_reason=self.last_kill_reason,
            last_kill_activity=self.last_kill_activity,
            skeleton_frame=self.skeleton_frame,
            ralph_state=self.ralph_state,
        )

        sys.stdout.write("\033[H")
        lines = render_dashboard(state, self.term_width, self.term_height)
        sys.stdout.write("\n".join(lines))
        sys.stdout.flush()

    def enter(self) -> None:
        """Enter dashboard mode - set up terminal."""
        import termios

        self.old_settings = termios.tcgetattr(sys.stdin)
        new_settings = termios.tcgetattr(sys.stdin)
        new_settings[3] = new_settings[3] & ~termios.ECHO
        new_settings[3] = new_settings[3] & ~termios.ICANON
        termios.tcsetattr(sys.stdin, termios.TCSANOW, new_settings)

        sys.stdout.write("\033[?1049h")
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

    def exit(self) -> None:
        """Exit dashboard mode - restore terminal."""
        import termios

        if self.old_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
        sys.stdout.write("\033[?25h")
        sys.stdout.write("\033[?1049l")
        sys.stdout.flush()

    def add_line(self, line: str) -> None:
        """Add an output line to the dashboard.

        Args:
            line: The line to add.
        """
        if line.startswith("\x01HEARTBEAT:"):
            try:
                self.skeleton_frame = int(line.split(":")[1])
            except (IndexError, ValueError):
                self.skeleton_frame = 0
            return
        if line.startswith("\x00"):
            return
        self.skeleton_frame = None
        self.output_lines.append(line)
        cost_info = parse_cost_line(line)
        if cost_info:
            self.cost = cost_info[0]
            self.tokens_in = cost_info[1]
            self.tokens_out = cost_info[2]
            self.context_tokens = cost_info[1]

    def run_loop(
        self,
        poll_data: Callable[[], Optional[list[str]]],
        on_quit: Optional[Callable[[], Optional[object]]] = None,
        update_state: Optional[Callable[["FallbackDashboard"], None]] = None,
    ) -> Optional[object]:
        """Unified main loop for dashboard rendering.

        Args:
            poll_data: Callable that returns list of new lines. Raise StopIteration to exit.
            on_quit: Optional callable when user presses quit.
            update_state: Optional callable to update dashboard state each iteration.

        Returns:
            Return value from on_quit, or None if loop exits normally.
        """
        from pathlib import Path

        ANIMATION_FPS = 30
        FRAME_DURATION = 1.0 / ANIMATION_FPS
        SKELETON_DELAY = 0.5
        STATE_REFRESH_INTERVAL = 1.0

        last_activity_time = time.time()
        animation_start_time = 0.0
        last_output_count = len(self.output_lines)
        last_state_refresh = 0.0

        self.enter()

        try:
            while True:
                now = time.time()

                try:
                    new_lines = poll_data()
                except StopIteration:
                    break

                if new_lines:
                    for line in new_lines:
                        self.add_line(line)
                    last_activity_time = now

                if len(self.output_lines) != last_output_count:
                    self.skeleton_frame = None
                    last_output_count = len(self.output_lines)
                    last_activity_time = now
                elif now - last_activity_time > SKELETON_DELAY and self.is_running:
                    if self.skeleton_frame is None:
                        animation_start_time = now
                    elapsed = now - animation_start_time
                    self.skeleton_frame = int(elapsed * ANIMATION_FPS) % len(
                        SKELETON_FRAMES
                    )

                if now - last_state_refresh >= STATE_REFRESH_INTERVAL:
                    plan_file = (
                        Path(self.config.plan_file)
                        if hasattr(self.config, "plan_file")
                        else None
                    )
                    if plan_file:
                        self.ralph_state = load_state(plan_file)
                    last_state_refresh = now

                if update_state:
                    update_state(self)

                action = self.get_input()
                if action:
                    if action == "quit":
                        if on_quit:
                            return on_quit()
                        break
                    self.handle_action(action)

                self.render()

                if self.skeleton_frame is not None:
                    time.sleep(FRAME_DURATION)
                else:
                    time.sleep(0.05)

        except KeyboardInterrupt:
            if on_quit:
                return on_quit()
            raise
        finally:
            self.exit()

        return None


def render_dashboard(
    state: DashboardState, term_width: int, term_height: int
) -> list[str]:
    """Render the dashboard and return lines.

    Args:
        state: Current dashboard state.
        term_width: Terminal width in characters.
        term_height: Terminal height in characters.

    Returns:
        List of lines to display.
    """
    from pathlib import Path

    CLEAR_LINE = "\033[K"

    def truncate(text: str, max_width: int, prefix_len: int = 0) -> str:
        visible_max = max_width - prefix_len - 3
        if len(text) > visible_max:
            return text[:visible_max] + "..."
        return text

    lines: list[str] = []

    def add(text: str = "") -> None:
        lines.append(f"{text}{CLEAR_LINE}")

    header_bar = "═" * (term_width - 1)
    section_bar = "─" * (term_width - 1)
    footer_bar = "─" * (term_width - 1)

    add(f"{Colors.BLUE}{header_bar}{Colors.NC}")

    kills_str = ""
    if state.kills_timeout > 0 or state.kills_context > 0:
        parts = []
        if state.kills_timeout > 0:
            parts.append(f"T:{state.kills_timeout}")
        if state.kills_context > 0:
            parts.append(f"C:{state.kills_context}")
        kills_str = f" | {Colors.RED}Kills: {' '.join(parts)}{Colors.NC}"

    if state.iteration is not None:
        title = f"  RALPH WIGGUM - Iteration {state.iteration} - {datetime.now().strftime('%H:%M:%S')}{kills_str}"
    else:
        title = f"  RALPH WIGGUM - {datetime.now().strftime('%H:%M:%S')}{kills_str}"
    add(f"{Colors.BLUE}{title}{Colors.NC}")
    add(f"{Colors.BLUE}{header_bar}{Colors.NC}")
    add()

    ralph_state = state.ralph_state
    if ralph_state is None:
        plan_file = (
            Path(state.config.plan_file) if hasattr(state.config, "plan_file") else None
        )
        if plan_file:
            ralph_state = load_state(plan_file)

    status_lines: list[str] = []
    status_lines.append(f"🌿 {Colors.GREEN}Branch:{Colors.NC} {state.branch}")

    if state.is_running:
        if state.running_count > 0:
            status_lines.append(
                f"🟢 {Colors.GREEN}Status:{Colors.NC} Running ({state.running_count})"
            )
        else:
            status_lines.append(f"🟢 {Colors.GREEN}Status:{Colors.NC} Running")
    else:
        status_lines.append(f"🟡 {Colors.YELLOW}Status:{Colors.NC} Stopped")

    stage = ralph_state.get_stage() if ralph_state else "UNKNOWN"
    stage_colors = {
        "PLAN": Colors.MAGENTA,
        "BUILD": Colors.CYAN,
        "VERIFY": Colors.YELLOW,
        "INVESTIGATE": Colors.RED,
        "COMPLETE": Colors.GREEN,
    }
    stage_color = stage_colors.get(stage, Colors.WHITE)
    status_lines.append(
        f"🔧 {Colors.GREEN}Stage:{Colors.NC} {stage_color}{stage}{Colors.NC}"
    )

    if state.cost > 0:
        status_lines.append(f"💰 {Colors.CYAN}Cost:{Colors.NC} ${state.cost:.4f}")
    else:
        status_lines.append(f"💰 {Colors.CYAN}Cost:{Colors.NC} --")

    pct = (
        (state.context_tokens / state.context_limit * 100)
        if state.context_limit > 0
        else 0
    )
    if pct >= 90:
        ctx_color = Colors.RED
    elif pct >= 70:
        ctx_color = Colors.YELLOW
    else:
        ctx_color = Colors.CYAN
    status_lines.append(
        f"🧠 {ctx_color}Context:{Colors.NC} {state.context_tokens:,} / {state.context_limit:,} ({pct:.0f}%)"
    )

    if state.last_kill_reason:
        kill_msg = f"⚠️  {Colors.RED}Kill:{Colors.NC} {state.last_kill_reason}"
        if state.last_kill_activity:
            kill_msg += f" @ {state.last_kill_activity[:30]}"
        status_lines.append(kill_msg)

    pending = len(ralph_state.pending) if ralph_state else 0
    done = len(ralph_state.done) if ralph_state else 0
    status_lines.append("")
    status_lines.append(
        f"📊 {Colors.GREEN}Progress:{Colors.NC} {done} done, {pending} pending"
    )
    status_lines.append("")
    if ralph_state and ralph_state.spec:
        status_lines.append(f"📋 {Colors.GREEN}Spec:{Colors.NC} {ralph_state.spec}")
    status_lines.append(f"🎯 {Colors.GREEN}Task:{Colors.NC}")
    next_task_obj = ralph_state.get_next_task() if ralph_state else None
    next_task = next_task_obj.name if next_task_obj else None
    if next_task:
        status_lines.append(
            f"   {truncate(next_task, term_width - RALPH_WIDTH - 6, 3)}"
        )
    else:
        status_lines.append("   (no pending tasks)")

    num_art_lines = max(len(RALPH_ART), len(status_lines))
    for i in range(num_art_lines):
        ralph_line = RALPH_ART[i] if i < len(RALPH_ART) else " " * RALPH_WIDTH
        status_line = status_lines[i] if i < len(status_lines) else ""
        add(f"{ralph_line} {Colors.DIM}│{Colors.NC} {status_line}")

    left_width = RALPH_WIDTH + 1
    right_width = term_width - left_width - 1
    if right_width < 0:
        right_width = 0
    t_join_separator = "─" * left_width + "┴" + "─" * right_width
    add(f"{Colors.DIM}{t_join_separator}{Colors.NC}")

    if ralph_state and ralph_state.issues:
        add(
            f"{Colors.YELLOW}Discovered Issues:{Colors.NC} ({len(ralph_state.issues)} open)"
        )
        for issue in ralph_state.issues[:5]:
            truncated_text = truncate(issue.desc, term_width, 9)
            add(f"  {Colors.RED}OPEN{Colors.NC}   {truncated_text}")
        if len(ralph_state.issues) > 5:
            add(
                f"  {Colors.YELLOW}... and {len(ralph_state.issues) - 5} more{Colors.NC}"
            )
        add(f"{Colors.DIM}{section_bar}{Colors.NC}")

    lines_used = len(lines)
    available_lines = term_height - lines_used - 3
    add(f"{Colors.GREEN}Output:{Colors.NC}")
    if available_lines >= 1:
        display_lines = (
            state.output_lines[-available_lines:] if state.output_lines else []
        )
        for line in display_lines:
            add(f"  {truncate(line, term_width, 2)}")
        if state.skeleton_frame is not None:
            frame = SKELETON_FRAMES[state.skeleton_frame % len(SKELETON_FRAMES)]
            add(f"  {frame}")
            for _ in range(available_lines - len(display_lines) - 1):
                add()
        else:
            for _ in range(available_lines - len(display_lines)):
                add()

    add(f"{Colors.BLUE}{footer_bar}{Colors.NC}")
    add(state.footer_text)

    while len(lines) < term_height:
        add()

    return lines[:term_height]
