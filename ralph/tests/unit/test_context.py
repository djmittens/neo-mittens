"""Unit tests for ralph.context module."""

import pytest

from ralph.context import (
    COMPACT_PCT,
    KILL_PCT,
    WARNING_PCT,
    CompactedContext,
    IterationKillInfo,
    Metrics,
    ToolSummaries,
)


class TestThresholdConstants:
    """Tests for context pressure threshold constants."""

    def test_warning_pct(self) -> None:
        """Test WARNING_PCT is 70."""
        assert WARNING_PCT == 70

    def test_compact_pct(self) -> None:
        """Test COMPACT_PCT is 85."""
        assert COMPACT_PCT == 85

    def test_kill_pct(self) -> None:
        """Test KILL_PCT is 95."""
        assert KILL_PCT == 95

    def test_threshold_ordering(self) -> None:
        """Test thresholds are in correct order: WARNING < COMPACT < KILL."""
        assert WARNING_PCT < COMPACT_PCT < KILL_PCT


class TestMetrics:
    """Tests for the Metrics dataclass."""

    def test_metrics_creation_defaults(self) -> None:
        """Test creating metrics with all defaults."""
        metrics = Metrics()
        assert metrics.total_cost == 0.0
        assert metrics.total_iterations == 0
        assert metrics.total_tokens_in == 0
        assert metrics.total_tokens_out == 0
        assert metrics.failures == 0
        assert metrics.successes == 0
        assert metrics.kills_timeout == 0
        assert metrics.kills_context == 0
        assert metrics.started_at is None
        assert metrics.last_kill_reason == ""
        assert metrics.last_kill_activity == ""

    def test_metrics_creation_with_values(self) -> None:
        """Test creating metrics with custom values."""
        metrics = Metrics(
            total_cost=1.50,
            total_iterations=5,
            total_tokens_in=10000,
            total_tokens_out=5000,
            failures=1,
            successes=4,
            kills_timeout=0,
            kills_context=1,
            started_at="2025-01-20T10:00:00Z",
            last_kill_reason="context_limit",
            last_kill_activity="Reading large file",
        )
        assert metrics.total_cost == 1.50
        assert metrics.total_iterations == 5
        assert metrics.total_tokens_in == 10000
        assert metrics.total_tokens_out == 5000
        assert metrics.failures == 1
        assert metrics.successes == 4
        assert metrics.kills_timeout == 0
        assert metrics.kills_context == 1
        assert metrics.started_at == "2025-01-20T10:00:00Z"
        assert metrics.last_kill_reason == "context_limit"
        assert metrics.last_kill_activity == "Reading large file"

    def test_metrics_partial_values(self) -> None:
        """Test creating metrics with partial values."""
        metrics = Metrics(total_cost=2.0, total_iterations=3)
        assert metrics.total_cost == 2.0
        assert metrics.total_iterations == 3
        assert metrics.total_tokens_in == 0
        assert metrics.failures == 0

    def test_metrics_cost_as_float(self) -> None:
        """Test that cost can be a fractional value."""
        metrics = Metrics(total_cost=0.00125)
        assert metrics.total_cost == 0.00125

    def test_metrics_mutability(self) -> None:
        """Test that metrics can be mutated."""
        metrics = Metrics()
        metrics.total_iterations += 1
        metrics.total_cost += 0.50
        metrics.successes += 1
        assert metrics.total_iterations == 1
        assert metrics.total_cost == 0.50
        assert metrics.successes == 1


class TestIterationKillInfo:
    """Tests for the IterationKillInfo dataclass."""

    def test_kill_info_creation_minimal(self) -> None:
        """Test creating kill info with minimal fields."""
        info = IterationKillInfo(reason="none")
        assert info.reason == "none"
        assert info.task_name is None
        assert info.tokens_used == 0
        assert info.context_limit == 0
        assert info.timeout_seconds == 0
        assert info.elapsed_seconds == 0
        assert info.last_activity is None

    def test_kill_info_timeout(self) -> None:
        """Test creating kill info for timeout."""
        info = IterationKillInfo(
            reason="timeout",
            task_name="Long running task",
            timeout_seconds=300,
            elapsed_seconds=310,
            last_activity="Running tests",
        )
        assert info.reason == "timeout"
        assert info.task_name == "Long running task"
        assert info.timeout_seconds == 300
        assert info.elapsed_seconds == 310
        assert info.last_activity == "Running tests"

    def test_kill_info_context_limit(self) -> None:
        """Test creating kill info for context limit."""
        info = IterationKillInfo(
            reason="context_limit",
            task_name="Reading codebase",
            tokens_used=180000,
            context_limit=200000,
            last_activity="Exploring source files",
        )
        assert info.reason == "context_limit"
        assert info.task_name == "Reading codebase"
        assert info.tokens_used == 180000
        assert info.context_limit == 200000
        assert info.last_activity == "Exploring source files"

    def test_kill_info_compaction_failed(self) -> None:
        """Test creating kill info for compaction failure."""
        info = IterationKillInfo(
            reason="compaction_failed",
            task_name="Complex task",
            tokens_used=175000,
            context_limit=200000,
            last_activity="Attempting compaction",
        )
        assert info.reason == "compaction_failed"

    def test_to_prompt_injection_none(self) -> None:
        """Test to_prompt_injection returns empty string for 'none' reason."""
        info = IterationKillInfo(reason="none")
        result = info.to_prompt_injection()
        assert result == ""

    def test_to_prompt_injection_timeout(self) -> None:
        """Test to_prompt_injection for timeout reason."""
        info = IterationKillInfo(
            reason="timeout",
            task_name="Slow task",
            timeout_seconds=300,
            elapsed_seconds=305,
            last_activity="Running build",
        )
        result = info.to_prompt_injection()
        assert "CRITICAL: Previous Iteration Failed" in result
        assert "KILLED after 305s" in result
        assert "timeout: 300s" in result
        assert "Task: Slow task" in result
        assert "Last activity before kill: Running build" in result
        assert "DO NOT repeat the same approach" in result
        assert "Break down the problem into SMALLER steps" in result

    def test_to_prompt_injection_context_limit(self) -> None:
        """Test to_prompt_injection for context_limit reason."""
        info = IterationKillInfo(
            reason="context_limit",
            task_name="Large exploration",
            tokens_used=190000,
            context_limit=200000,
            last_activity="Reading many files",
        )
        result = info.to_prompt_injection()
        assert "CRITICAL: Previous Iteration Failed" in result
        assert "context overflow" in result
        assert "190,000 tokens" in result
        assert "95%" in result  # 190000/200000 = 95%
        assert "200,000 limit" in result
        assert "Task: Large exploration" in result
        assert "Last activity before kill: Reading many files" in result
        assert "USE THE TASK TOOL to spawn subagents" in result
        assert "Each subagent gets a FRESH context window" in result

    def test_to_prompt_injection_compaction_failed(self) -> None:
        """Test to_prompt_injection for compaction_failed reason."""
        info = IterationKillInfo(
            reason="compaction_failed",
            task_name="Complex task",
            tokens_used=170000,
            context_limit=200000,
            last_activity="Compacting context",
        )
        result = info.to_prompt_injection()
        assert "CRITICAL: Previous Iteration Failed" in result
        assert "compaction failed" in result
        assert "still >80% after attempt" in result
        assert "Task: Complex task" in result
        assert "USE THE TASK TOOL" in result

    def test_to_prompt_injection_unknown_task(self) -> None:
        """Test to_prompt_injection with unknown task name."""
        info = IterationKillInfo(
            reason="timeout",
            task_name=None,
            timeout_seconds=300,
            elapsed_seconds=310,
        )
        result = info.to_prompt_injection()
        assert "Task: unknown" in result

    def test_to_prompt_injection_unknown_activity(self) -> None:
        """Test to_prompt_injection with unknown last activity."""
        info = IterationKillInfo(
            reason="timeout",
            task_name="Some task",
            timeout_seconds=300,
            elapsed_seconds=310,
            last_activity=None,
        )
        result = info.to_prompt_injection()
        assert "Last activity before kill: unknown" in result

    def test_to_prompt_injection_zero_context_limit(self) -> None:
        """Test to_prompt_injection handles zero context limit gracefully."""
        info = IterationKillInfo(
            reason="context_limit",
            task_name="Task",
            tokens_used=1000,
            context_limit=0,
        )
        result = info.to_prompt_injection()
        assert "0%" in result  # Should handle division by zero


class TestToolSummaries:
    """Tests for the ToolSummaries dataclass."""

    def test_tool_summaries_creation(self) -> None:
        """Test creating tool summaries with all fields."""
        summaries = ToolSummaries(
            files_read={"src/main.py": "Main entry point", "src/utils.py": "Utilities"},
            files_edited=["src/main.py"],
            searches_performed=["grep for 'error'", "find .py files"],
            tests_run=["pytest src/tests/"],
            subagents_spawned=["Research task A"],
        )
        assert summaries.files_read == {
            "src/main.py": "Main entry point",
            "src/utils.py": "Utilities",
        }
        assert summaries.files_edited == ["src/main.py"]
        assert summaries.searches_performed == ["grep for 'error'", "find .py files"]
        assert summaries.tests_run == ["pytest src/tests/"]
        assert summaries.subagents_spawned == ["Research task A"]

    def test_tool_summaries_empty(self) -> None:
        """Test creating tool summaries with empty collections."""
        summaries = ToolSummaries(
            files_read={},
            files_edited=[],
            searches_performed=[],
            tests_run=[],
            subagents_spawned=[],
        )
        assert summaries.files_read == {}
        assert summaries.files_edited == []
        assert summaries.searches_performed == []
        assert summaries.tests_run == []
        assert summaries.subagents_spawned == []

    def test_tool_summaries_mutability(self) -> None:
        """Test that tool summaries collections can be mutated."""
        summaries = ToolSummaries(
            files_read={},
            files_edited=[],
            searches_performed=[],
            tests_run=[],
            subagents_spawned=[],
        )
        summaries.files_read["new_file.py"] = "New file"
        summaries.files_edited.append("new_file.py")
        assert "new_file.py" in summaries.files_read
        assert "new_file.py" in summaries.files_edited


class TestCompactedContext:
    """Tests for the CompactedContext dataclass."""

    def test_compacted_context_creation_minimal(self) -> None:
        """Test creating compacted context with minimal required fields."""
        ctx = CompactedContext(
            task_name="Test task",
            task_notes=None,
            task_accept=None,
            progress_summary="Started work",
            uncommitted_changes="",
            key_files=[],
            blockers=[],
            next_step="Continue implementation",
            key_decisions=[],
        )
        assert ctx.task_name == "Test task"
        assert ctx.task_notes is None
        assert ctx.task_accept is None
        assert ctx.progress_summary == "Started work"
        assert ctx.uncommitted_changes == ""
        assert ctx.key_files == []
        assert ctx.blockers == []
        assert ctx.next_step == "Continue implementation"
        assert ctx.key_decisions == []
        assert ctx.tool_summaries is None

    def test_compacted_context_creation_full(self) -> None:
        """Test creating compacted context with all fields."""
        summaries = ToolSummaries(
            files_read={"src/main.py": "Entry point"},
            files_edited=["src/main.py"],
            searches_performed=["searched for X"],
            tests_run=["pytest"],
            subagents_spawned=["Research task"],
        )
        ctx = CompactedContext(
            task_name="Full task",
            task_notes="Implementation notes",
            task_accept="Tests pass",
            progress_summary="50% complete",
            uncommitted_changes="diff output here",
            key_files=["src/main.py", "src/utils.py"],
            blockers=["Dependency issue"],
            next_step="Fix the dependency",
            key_decisions=["Use approach A"],
            tool_summaries=summaries,
        )
        assert ctx.task_name == "Full task"
        assert ctx.task_notes == "Implementation notes"
        assert ctx.task_accept == "Tests pass"
        assert ctx.progress_summary == "50% complete"
        assert ctx.uncommitted_changes == "diff output here"
        assert ctx.key_files == ["src/main.py", "src/utils.py"]
        assert ctx.blockers == ["Dependency issue"]
        assert ctx.next_step == "Fix the dependency"
        assert ctx.key_decisions == ["Use approach A"]
        assert ctx.tool_summaries is not None

    def test_to_prompt_minimal(self) -> None:
        """Test to_prompt with minimal compacted context."""
        ctx = CompactedContext(
            task_name="Minimal task",
            task_notes=None,
            task_accept=None,
            progress_summary="Just started",
            uncommitted_changes="",
            key_files=[],
            blockers=[],
            next_step="Continue work",
            key_decisions=[],
        )
        result = ctx.to_prompt()
        assert "=== COMPACTED CONTEXT ===" in result
        assert "Task: Minimal task" in result
        assert "Progress: Just started" in result
        assert "Next step: Continue work" in result
        assert "=== END COMPACTED ===" in result
        assert "resuming from a compacted context" in result
        assert "Notes:" not in result
        assert "Accept criteria:" not in result

    def test_to_prompt_with_notes_and_accept(self) -> None:
        """Test to_prompt includes notes and accept criteria."""
        ctx = CompactedContext(
            task_name="Task with notes",
            task_notes="Read the docs carefully",
            task_accept="All tests pass",
            progress_summary="In progress",
            uncommitted_changes="",
            key_files=[],
            blockers=[],
            next_step="Run tests",
            key_decisions=[],
        )
        result = ctx.to_prompt()
        assert "Notes: Read the docs carefully" in result
        assert "Accept criteria: All tests pass" in result

    def test_to_prompt_with_key_files(self) -> None:
        """Test to_prompt includes key files."""
        ctx = CompactedContext(
            task_name="Task",
            task_notes=None,
            task_accept=None,
            progress_summary="Progress",
            uncommitted_changes="",
            key_files=["src/a.py", "src/b.py"],
            blockers=[],
            next_step="Next",
            key_decisions=[],
        )
        result = ctx.to_prompt()
        assert "Key files: src/a.py, src/b.py" in result

    def test_to_prompt_with_uncommitted_changes(self) -> None:
        """Test to_prompt includes uncommitted changes."""
        ctx = CompactedContext(
            task_name="Task",
            task_notes=None,
            task_accept=None,
            progress_summary="Progress",
            uncommitted_changes="+ added line\n- removed line",
            key_files=[],
            blockers=[],
            next_step="Next",
            key_decisions=[],
        )
        result = ctx.to_prompt()
        assert "Uncommitted changes:" in result
        assert "+ added line" in result
        assert "- removed line" in result

    def test_to_prompt_truncates_long_diff(self) -> None:
        """Test to_prompt truncates very long diffs."""
        long_diff = "x" * 3000  # Longer than 2000 char limit
        ctx = CompactedContext(
            task_name="Task",
            task_notes=None,
            task_accept=None,
            progress_summary="Progress",
            uncommitted_changes=long_diff,
            key_files=[],
            blockers=[],
            next_step="Next",
            key_decisions=[],
        )
        result = ctx.to_prompt()
        assert "Uncommitted changes:" in result
        assert "(truncated)" in result
        # Should only have first 2000 chars
        assert "x" * 2000 in result
        assert "x" * 2001 not in result

    def test_to_prompt_with_blockers(self) -> None:
        """Test to_prompt includes blockers."""
        ctx = CompactedContext(
            task_name="Task",
            task_notes=None,
            task_accept=None,
            progress_summary="Progress",
            uncommitted_changes="",
            key_files=[],
            blockers=["Issue A", "Issue B"],
            next_step="Next",
            key_decisions=[],
        )
        result = ctx.to_prompt()
        assert "Blockers: Issue A; Issue B" in result

    def test_to_prompt_with_key_decisions(self) -> None:
        """Test to_prompt includes key decisions."""
        ctx = CompactedContext(
            task_name="Task",
            task_notes=None,
            task_accept=None,
            progress_summary="Progress",
            uncommitted_changes="",
            key_files=[],
            blockers=[],
            next_step="Next",
            key_decisions=["Decision 1", "Decision 2"],
        )
        result = ctx.to_prompt()
        assert "Key decisions made:" in result
        assert "- Decision 1" in result
        assert "- Decision 2" in result

    def test_to_prompt_with_tool_summaries(self) -> None:
        """Test to_prompt includes tool summaries."""
        summaries = ToolSummaries(
            files_read={"src/a.py": "File A desc"},
            files_edited=["src/a.py", "src/b.py"],
            searches_performed=["search 1", "search 2"],
            tests_run=["pytest test_a.py"],
            subagents_spawned=["Subagent task 1"],
        )
        ctx = CompactedContext(
            task_name="Task",
            task_notes=None,
            task_accept=None,
            progress_summary="Progress",
            uncommitted_changes="",
            key_files=[],
            blockers=[],
            next_step="Next",
            key_decisions=[],
            tool_summaries=summaries,
        )
        result = ctx.to_prompt()
        assert "Exploration performed:" in result
        assert "- search 1" in result
        assert "Files read:" in result
        assert "- src/a.py: File A desc" in result
        assert "Files edited: src/a.py, src/b.py" in result
        assert "Tests run:" in result
        assert "- pytest test_a.py" in result
        assert "Subagent tasks:" in result
        assert "- Subagent task 1" in result

    def test_to_prompt_tool_summaries_empty_collections(self) -> None:
        """Test to_prompt handles empty tool summaries collections."""
        summaries = ToolSummaries(
            files_read={},
            files_edited=[],
            searches_performed=[],
            tests_run=[],
            subagents_spawned=[],
        )
        ctx = CompactedContext(
            task_name="Task",
            task_notes=None,
            task_accept=None,
            progress_summary="Progress",
            uncommitted_changes="",
            key_files=[],
            blockers=[],
            next_step="Next",
            key_decisions=[],
            tool_summaries=summaries,
        )
        result = ctx.to_prompt()
        # Empty sections should not appear
        assert "Exploration performed:" not in result
        assert "Files read:" not in result
        assert "Files edited:" not in result
        assert "Tests run:" not in result
        assert "Subagent tasks:" not in result

    def test_to_prompt_contains_resumption_guidance(self) -> None:
        """Test to_prompt includes guidance for resumption."""
        ctx = CompactedContext(
            task_name="Task",
            task_notes=None,
            task_accept=None,
            progress_summary="Progress",
            uncommitted_changes="",
            key_files=[],
            blockers=[],
            next_step="Next",
            key_decisions=[],
        )
        result = ctx.to_prompt()
        assert "You are resuming from a compacted context" in result
        assert "stopped due to context pressure" in result
        assert "Do NOT re-explore the codebase" in result
        assert "use subagents (Task tool)" in result
