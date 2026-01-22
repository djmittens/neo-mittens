"""Context management and metrics tracking for Ralph."""

from dataclasses import dataclass, field
from typing import Optional

# Threshold constants for context pressure
WARNING_PCT = 70
COMPACT_PCT = 85
KILL_PCT = 95


@dataclass
class Metrics:
    """In-memory metrics for the current session."""

    total_cost: float = 0.0
    total_iterations: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    failures: int = 0
    successes: int = 0
    kills_timeout: int = 0
    kills_context: int = 0
    started_at: Optional[str] = None
    last_kill_reason: str = ""
    last_kill_activity: str = ""

    @property
    def tokens_used(self) -> int:
        """Total tokens used (in + out)."""
        return self.total_tokens_in + self.total_tokens_out

    @property
    def cost(self) -> float:
        """Alias for total_cost."""
        return self.total_cost

    @property
    def iterations(self) -> int:
        """Alias for total_iterations."""
        return self.total_iterations


@dataclass
class IterationKillInfo:
    """Information about why an iteration was killed."""

    reason: str  # "timeout", "context_limit", "compaction_failed", or "none"
    task_name: Optional[str] = None
    tokens_used: int = 0
    context_limit: int = 0
    timeout_seconds: int = 0
    elapsed_seconds: int = 0
    last_activity: Optional[str] = None

    def to_prompt_injection(self) -> str:
        """Generate prompt text for the next iteration after a kill."""
        if self.reason == "none":
            return ""

        lines = ["## Context from Previous Attempt", ""]

        if self.reason == "timeout":
            lines.append(
                f"Previous attempt timed out after {self.elapsed_seconds}s "
                f"(limit: {self.timeout_seconds}s)."
            )
        elif self.reason == "context_limit":
            pct = (
                (self.tokens_used / self.context_limit * 100)
                if self.context_limit > 0
                else 0
            )
            lines.append(
                f"Previous attempt exceeded context limit: "
                f"{pct:.0f}% ({self.tokens_used:,}/{self.context_limit:,} tokens)."
            )
        elif self.reason == "compaction_failed":
            lines.append("Previous attempt failed to compact context successfully.")

        if self.task_name:
            lines.append(f"Task: {self.task_name}")
        if self.last_activity:
            lines.append(f"Last activity: {self.last_activity}")

        lines.append("")
        lines.append("Continue from where the previous attempt left off.")

        return "\n".join(lines)


@dataclass
class ToolSummaries:
    """Summarized tool activity from conversation."""

    files_read: dict = field(default_factory=dict)
    files_edited: list = field(default_factory=list)
    searches_performed: list = field(default_factory=list)
    tests_run: list = field(default_factory=list)
    subagents_spawned: list = field(default_factory=list)


@dataclass
class CompactedContext:
    """Compacted context for resuming execution after context pressure."""

    task_name: str
    task_notes: Optional[str] = None
    task_accept: Optional[str] = None
    progress_summary: str = ""
    uncommitted_changes: str = ""
    key_files: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    next_step: str = ""
    key_decisions: list = field(default_factory=list)
    tool_summaries: Optional[ToolSummaries] = None

    def _format_header(self) -> list[str]:
        """Format the header section with task info."""
        lines = ["## Compacted Context", "", f"**Task:** {self.task_name}"]
        if self.task_notes:
            lines.append(f"**Notes:** {self.task_notes}")
        if self.task_accept:
            lines.append(f"**Accept Criteria:** {self.task_accept}")
        lines.append("")
        return lines

    def _format_body(self) -> list[str]:
        """Format the body section with progress and state."""
        lines = []
        if self.progress_summary:
            lines.append(f"**Progress:** {self.progress_summary}")
        if self.uncommitted_changes:
            lines.append(f"**Uncommitted Changes:** {self.uncommitted_changes}")
        return lines

    def _format_lists(self) -> list[str]:
        """Format list sections: key files, blockers, decisions."""
        lines = []
        for label, items in [
            ("Key Files", self.key_files),
            ("Blockers", self.blockers),
            ("Key Decisions", self.key_decisions),
        ]:
            if items:
                lines.append(f"**{label}:**")
                lines.extend(f"  - {item}" for item in items)
        return lines

    def _format_footer(self) -> list[str]:
        """Format the footer with next step and tool summaries."""
        lines = []
        if self.next_step:
            lines.append(f"**Next Step:** {self.next_step}")
        if self.tool_summaries:
            ts = self.tool_summaries
            if ts.files_edited:
                lines.append(f"**Files Edited:** {', '.join(ts.files_edited)}")
            if ts.tests_run:
                lines.append(f"**Tests Run:** {len(ts.tests_run)} test(s)")
        return lines

    def to_prompt(self) -> str:
        """Generate the compacted context prompt."""
        lines = self._format_header()
        lines.extend(self._format_body())
        lines.extend(self._format_lists())
        lines.extend(self._format_footer())
        return "\n".join(lines)


def context_pressure(metrics: Metrics, config) -> float:
    """Calculate context pressure as a percentage.

    Args:
        metrics: Current session metrics
        config: GlobalConfig with context_window field

    Returns:
        Percentage of context used (0-100+)
    """
    context_limit = getattr(config, "context_window", 200_000)
    if context_limit <= 0:
        return 0.0
    return (metrics.tokens_used / context_limit) * 100
