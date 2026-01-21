"""Context metrics, pressure tracking, and compaction for Ralph sessions."""

from dataclasses import dataclass
from typing import Optional


# Threshold constants for context pressure management
WARNING_PCT = 70
COMPACT_PCT = 85
KILL_PCT = 95


@dataclass
class Metrics:
    """In-memory metrics for the current session.

    Tracks cumulative costs, token usage, and iteration outcomes during a
    Ralph construct session.

    Attributes:
        total_cost: Total cost in dollars for the session.
        total_iterations: Number of iterations completed.
        total_tokens_in: Total input tokens consumed.
        total_tokens_out: Total output tokens generated.
        failures: Number of failed iterations.
        successes: Number of successful iterations.
        kills_timeout: Number of iterations killed due to timeout.
        kills_context: Number of iterations killed due to context limit.
        started_at: ISO timestamp when session started.
        last_kill_reason: Reason for the last kill ("timeout" or "context_limit").
        last_kill_activity: What the agent was doing when killed.
    """

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


@dataclass
class IterationKillInfo:
    """Information about why an iteration was killed.

    When an iteration is terminated (due to timeout, context limit, or
    compaction failure), this class captures the relevant details for
    diagnosing the issue and informing the next iteration.

    Attributes:
        reason: Kill reason ("timeout", "context_limit", "compaction_failed", or "none").
        task_name: Name of the task being executed when killed.
        tokens_used: Number of tokens consumed before kill.
        context_limit: Maximum context window size in tokens.
        timeout_seconds: Timeout threshold in seconds.
        elapsed_seconds: Actual elapsed time before kill.
        last_activity: Description of what the agent was doing when killed.
    """

    reason: str
    task_name: Optional[str] = None
    tokens_used: int = 0
    context_limit: int = 0
    timeout_seconds: int = 0
    elapsed_seconds: int = 0
    last_activity: Optional[str] = None

    def to_prompt_injection(self) -> str:
        """Generate prompt text to inject into the next iteration.

        Creates a formatted message explaining why the previous iteration
        was killed and providing guidance for the next iteration.

        Returns:
            Formatted prompt text with kill reason and required actions.
        """
        if self.reason == "none":
            return ""

        lines = [
            "# CRITICAL: Previous Iteration Failed",
            "",
        ]

        if self.reason == "timeout":
            lines.extend(
                [
                    f"The previous iteration was KILLED after {self.elapsed_seconds}s "
                    f"(timeout: {self.timeout_seconds}s).",
                    f"Task: {self.task_name or 'unknown'}",
                    "",
                    f"Last activity before kill: {self.last_activity or 'unknown'}",
                    "",
                    "## Required Actions:",
                    "1. DO NOT repeat the same approach - it will fail again",
                    "2. Break down the problem into SMALLER steps",
                    "3. If investigating code, use targeted searches instead of reading entire files",
                    "4. If the task is too complex, create sub-tasks using `ralph task add`",
                    "5. Complete ONE small step, then EXIT to let the next iteration continue",
                    "",
                ]
            )
        elif self.reason in ("context_limit", "compaction_failed"):
            pct_used = (
                (self.tokens_used / self.context_limit * 100)
                if self.context_limit > 0
                else 0
            )
            reason_text = (
                "compaction failed (still >80% after attempt)"
                if self.reason == "compaction_failed"
                else "context overflow"
            )
            lines.extend(
                [
                    f"The previous iteration was KILLED due to {reason_text} "
                    f"({self.tokens_used:,} tokens, {pct_used:.0f}% of {self.context_limit:,} limit).",
                    f"Task: {self.task_name or 'unknown'}",
                    "",
                    f"Last activity before kill: {self.last_activity or 'unknown'}",
                    "",
                    "## Required Actions - YOU MUST USE SUBAGENTS:",
                    "",
                    "You are reading too much code directly. USE THE TASK TOOL to spawn subagents:",
                    "",
                    "```",
                    'Task: "Research how [X] works in this codebase. Find the relevant files, '
                    "understand the implementation, and report back: 1) which files, 2) how it "
                    'works, 3) what needs to change"',
                    "```",
                    "",
                    "Each subagent gets a FRESH context window. Spawn multiple subagents in "
                    "parallel for different research questions.",
                    "",
                    "DO NOT:",
                    "- Read files directly (use subagents)",
                    "- Explore broadly (be specific in subagent prompts)",
                    "- Try to understand everything at once",
                    "",
                    "DO:",
                    "- Spawn a subagent for each research question",
                    "- Wait for subagent results before proceeding",
                    "- Make targeted edits based on subagent findings",
                    "",
                ]
            )

        lines.append("---\n")
        return "\n".join(lines)


@dataclass
class ToolSummaries:
    """Summarized tool activity from conversation.

    Captures a summary of the tool usage during an iteration for context
    compaction. This allows resuming work with knowledge of what has been
    explored and modified.

    Attributes:
        files_read: Mapping of file paths to content summaries.
        files_edited: List of file paths that were modified.
        searches_performed: List of search query summaries.
        tests_run: List of test execution summaries.
        subagents_spawned: List of subagent task descriptions.
    """

    files_read: dict
    files_edited: list
    searches_performed: list
    tests_run: list
    subagents_spawned: list


@dataclass
class CompactedContext:
    """Compacted context for resuming execution after context pressure.

    When an iteration approaches the context limit, the context is compacted
    into this structure. It preserves the essential information needed to
    resume work without the full conversation history.

    Attributes:
        task_name: Name of the current task.
        task_notes: Implementation notes for the task.
        task_accept: Acceptance criteria for the task.
        progress_summary: Summary of work completed so far.
        uncommitted_changes: Git diff of uncommitted changes.
        key_files: List of important file paths for this task.
        blockers: List of blocking issues discovered.
        next_step: Description of what to do next.
        key_decisions: List of decisions made during execution.
        tool_summaries: Optional summarized tool activity.
    """

    task_name: str
    task_notes: Optional[str]
    task_accept: Optional[str]
    progress_summary: str
    uncommitted_changes: str
    key_files: list
    blockers: list
    next_step: str
    key_decisions: list
    tool_summaries: Optional[ToolSummaries] = None

    def to_prompt(self) -> str:
        """Generate the compacted context prompt for resumption.

        Creates a formatted prompt that summarizes the work done so far,
        key files and decisions, and provides guidance for continuing.

        Returns:
            Formatted prompt text for resuming from compacted context.
        """
        lines = [
            "=== COMPACTED CONTEXT ===",
            "",
            f"Task: {self.task_name}",
            "",
        ]

        if self.task_notes:
            lines.append(f"Notes: {self.task_notes}")
            lines.append("")

        if self.task_accept:
            lines.append(f"Accept criteria: {self.task_accept}")
            lines.append("")

        lines.extend(
            [
                f"Progress: {self.progress_summary}",
                "",
                "Current state: Execution was compacted due to context pressure",
                "",
            ]
        )

        if self.key_files:
            lines.append(f"Key files: {', '.join(self.key_files)}")
            lines.append("")

        if self.uncommitted_changes:
            truncated = len(self.uncommitted_changes) > 2000
            lines.extend(
                [
                    "Uncommitted changes:",
                    "```",
                    self.uncommitted_changes[:2000],
                    "```" if not truncated else "``` (truncated)",
                    "",
                ]
            )

        if self.blockers:
            lines.append(f"Blockers: {'; '.join(self.blockers)}")
            lines.append("")

        if self.key_decisions:
            lines.append("Key decisions made:")
            for decision in self.key_decisions:
                lines.append(f"  - {decision}")
            lines.append("")

        if self.tool_summaries:
            ts = self.tool_summaries

            if ts.searches_performed:
                lines.append("Exploration performed:")
                for search in ts.searches_performed[:10]:
                    lines.append(f"  - {search}")
                lines.append("")

            if ts.files_read:
                lines.append("Files read:")
                for path, summary in list(ts.files_read.items())[:15]:
                    lines.append(f"  - {path}: {summary}")
                lines.append("")

            if ts.files_edited:
                lines.append(f"Files edited: {', '.join(ts.files_edited[:20])}")
                lines.append("")

            if ts.tests_run:
                lines.append("Tests run:")
                for test in ts.tests_run[:5]:
                    lines.append(f"  - {test}")
                lines.append("")

            if ts.subagents_spawned:
                lines.append("Subagent tasks:")
                for task in ts.subagents_spawned[:10]:
                    lines.append(f"  - {task}")
                lines.append("")

        lines.extend(
            [
                f"Next step: {self.next_step}",
                "",
                "=== END COMPACTED ===",
                "",
                "## IMPORTANT: You are resuming from a compacted context",
                "",
                "The previous execution was stopped due to context pressure. "
                "Your context has been compacted.",
                "Continue from where you left off. Do NOT re-explore the codebase - "
                "use the information above.",
                "",
                "If you need to explore more code, use subagents (Task tool) to avoid "
                "filling context again.",
                "",
            ]
        )

        return "\n".join(lines)
