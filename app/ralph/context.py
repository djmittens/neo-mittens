"""Context management and metrics tracking for Ralph."""

import hashlib
import time
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
    total_tokens_cached: int = 0  # Cache reads (separate from input)
    total_tokens_out: int = 0
    failures: int = 0
    successes: int = 0
    kills_timeout: int = 0
    kills_context: int = 0
    kills_loop: int = 0  # New: killed due to loop detection
    started_at: Optional[str] = None
    last_kill_reason: str = ""

    # Progress tracking
    last_progress_time: float = 0.0  # Unix timestamp of last progress
    tasks_completed: int = 0
    commits_made: int = 0

    # API call tracking (for Max plan quota management)
    api_calls_remote: int = 0  # Calls to cloud providers (cost quota)
    api_calls_local: int = 0  # Calls to local models (free)

    # Validation retry tracking
    validation_retries: int = 0

    # Model/finish tracking from opencode step_finish events
    last_model: str = ""  # Actual model that served the last request
    last_finish_reason: str = ""  # "stop", "length", "tool_use"

    @property
    def tokens_used(self) -> int:
        """Total tokens used (in + cached + out)."""
        return self.total_tokens_in + self.total_tokens_cached + self.total_tokens_out

    @property
    def cost(self) -> float:
        """Alias for total_cost."""
        return self.total_cost

    @property
    def iterations(self) -> int:
        """Alias for total_iterations."""
        return self.total_iterations

    def record_progress(self) -> None:
        """Record that progress was made (task completed, commit, etc.)."""
        self.last_progress_time = time.time()

    def seconds_since_progress(self) -> float:
        """Return seconds since last progress, or 0 if never recorded."""
        if self.last_progress_time <= 0:
            return 0.0
        return time.time() - self.last_progress_time


class LoopDetector:
    """Detects runaway loops by tracking repeated outputs."""

    def __init__(self, threshold: int = 3):
        """Initialize loop detector.

        Args:
            threshold: Number of identical outputs before triggering abort.
        """
        self.threshold = threshold
        self.output_hashes: list[str] = []
        self.consecutive_identical: int = 0
        self.last_hash: str = ""

    def check_output(self, output: str) -> bool:
        """Check if output indicates a loop.

        Args:
            output: Stage output to check.

        Returns:
            True if loop detected (should abort), False otherwise.
        """
        # Hash the output for efficient comparison
        output_hash = hashlib.md5(output.encode()).hexdigest()

        if output_hash == self.last_hash:
            self.consecutive_identical += 1
        else:
            self.consecutive_identical = 1
            self.last_hash = output_hash

        self.output_hashes.append(output_hash)

        return self.consecutive_identical >= self.threshold

    def reset(self) -> None:
        """Reset the detector state."""
        self.output_hashes.clear()
        self.consecutive_identical = 0
        self.last_hash = ""


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
        """Format the header section with task info and metadata."""
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


@dataclass
class SessionSummary:
    """Summary of a Ralph session for logging/auditing."""

    started_at: str
    ended_at: str
    duration_seconds: float
    total_iterations: int
    tasks_completed: int
    commits_made: int
    total_tokens_in: int
    total_tokens_cached: int
    total_tokens_out: int
    total_cost: float
    failures: int
    successes: int
    kills_timeout: int
    kills_context: int
    kills_loop: int
    api_calls_remote: int
    api_calls_local: int
    exit_reason: str  # "complete", "max_iterations", "interrupted", "loop_detected", etc.
    spec: str
    profile: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "total_iterations": self.total_iterations,
            "tasks_completed": self.tasks_completed,
            "commits_made": self.commits_made,
            "tokens": {
                "input": self.total_tokens_in,
                "cached": self.total_tokens_cached,
                "output": self.total_tokens_out,
                "total": self.total_tokens_in + self.total_tokens_cached + self.total_tokens_out,
            },
            "cost": self.total_cost,
            "api_calls": {
                "remote": self.api_calls_remote,
                "local": self.api_calls_local,
            },
            "outcomes": {
                "successes": self.successes,
                "failures": self.failures,
            },
            "kills": {
                "timeout": self.kills_timeout,
                "context": self.kills_context,
                "loop": self.kills_loop,
            },
            "exit_reason": self.exit_reason,
            "spec": self.spec,
            "profile": self.profile,
        }

    @classmethod
    def from_metrics(
        cls,
        metrics: "Metrics",
        exit_reason: str,
        spec: str,
        profile: str,
        ended_at: str,
    ) -> "SessionSummary":
        """Create summary from metrics."""
        started = metrics.started_at or ended_at
        # Calculate duration if we have timestamps
        duration = 0.0
        try:
            from datetime import datetime

            start_dt = datetime.fromisoformat(started)
            end_dt = datetime.fromisoformat(ended_at)
            duration = (end_dt - start_dt).total_seconds()
        except (ValueError, TypeError):
            pass

        return cls(
            started_at=started,
            ended_at=ended_at,
            duration_seconds=duration,
            total_iterations=metrics.total_iterations,
            tasks_completed=metrics.tasks_completed,
            commits_made=metrics.commits_made,
            total_tokens_in=metrics.total_tokens_in,
            total_tokens_cached=metrics.total_tokens_cached,
            total_tokens_out=metrics.total_tokens_out,
            total_cost=metrics.total_cost,
            failures=metrics.failures,
            successes=metrics.successes,
            kills_timeout=metrics.kills_timeout,
            kills_context=metrics.kills_context,
            kills_loop=metrics.kills_loop,
            api_calls_remote=metrics.api_calls_remote,
            api_calls_local=metrics.api_calls_local,
            exit_reason=exit_reason,
            spec=spec,
            profile=profile,
        )
