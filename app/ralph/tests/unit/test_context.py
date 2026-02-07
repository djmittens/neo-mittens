"""Unit tests for ralph.context module."""

import pytest
from ralph.context import (
    Metrics,
    LoopDetector,
    IterationKillInfo,
    ToolSummaries,
    CompactedContext,
    WARNING_PCT,
    COMPACT_PCT,
    KILL_PCT,
    context_pressure,
)


class TestThresholdConstants:
    """Tests for context pressure threshold constants."""

    def test_warning_pct_value(self):
        """Verify WARNING_PCT is 70."""
        assert WARNING_PCT == 70

    def test_compact_pct_value(self):
        """Verify COMPACT_PCT is 85."""
        assert COMPACT_PCT == 85

    def test_kill_pct_value(self):
        """Verify KILL_PCT is 95."""
        assert KILL_PCT == 95

    def test_thresholds_are_ordered(self):
        """Verify thresholds are in ascending order."""
        assert WARNING_PCT < COMPACT_PCT < KILL_PCT


class TestMetricsCreation:
    """Tests for Metrics dataclass."""

    def test_metrics_default_creation(self):
        """Test creating Metrics with default values."""
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

    def test_metrics_custom_values(self):
        """Test creating Metrics with custom values."""
        metrics = Metrics(
            total_cost=1.23,
            total_iterations=5,
            total_tokens_in=1000,
            total_tokens_out=500,
            failures=2,
            successes=3,
            kills_timeout=1,
            kills_context=0,
            started_at="2026-01-21T10:00:00",
            last_kill_reason="timeout",
            last_kill_activity="running tests",
        )
        assert metrics.total_cost == 1.23
        assert metrics.total_iterations == 5
        assert metrics.total_tokens_in == 1000
        assert metrics.total_tokens_out == 500
        assert metrics.failures == 2
        assert metrics.successes == 3
        assert metrics.kills_timeout == 1
        assert metrics.kills_context == 0
        assert metrics.started_at == "2026-01-21T10:00:00"
        assert metrics.last_kill_reason == "timeout"
        assert metrics.last_kill_activity == "running tests"

    def test_metrics_tokens_used_property(self):
        """Test tokens_used computed property."""
        metrics = Metrics(total_tokens_in=1000, total_tokens_out=500)
        assert metrics.tokens_used == 1500

    def test_metrics_tokens_used_zero(self):
        """Test tokens_used with zero values."""
        metrics = Metrics()
        assert metrics.tokens_used == 0

    def test_metrics_cost_alias(self):
        """Test cost property is alias for total_cost."""
        metrics = Metrics(total_cost=5.67)
        assert metrics.cost == 5.67
        assert metrics.cost == metrics.total_cost

    def test_metrics_iterations_alias(self):
        """Test iterations property is alias for total_iterations."""
        metrics = Metrics(total_iterations=10)
        assert metrics.iterations == 10
        assert metrics.iterations == metrics.total_iterations


class TestContextPressureCalculation:
    """Tests for context_pressure function."""

    def test_context_pressure_zero_tokens(self):
        """Test context pressure with zero tokens used."""
        metrics = Metrics()

        class MockConfig:
            context_window = 200_000

        pressure = context_pressure(metrics, MockConfig())
        assert pressure == 0.0

    def test_context_pressure_50_percent(self):
        """Test context pressure at 50%."""
        metrics = Metrics(total_tokens_in=50_000, total_tokens_out=50_000)

        class MockConfig:
            context_window = 200_000

        pressure = context_pressure(metrics, MockConfig())
        assert pressure == 50.0

    def test_context_pressure_at_warning(self):
        """Test context pressure at WARNING_PCT threshold."""

        class MockConfig:
            context_window = 100_000

        metrics = Metrics(total_tokens_in=70_000)
        pressure = context_pressure(metrics, MockConfig())
        assert pressure == WARNING_PCT

    def test_context_pressure_at_compact(self):
        """Test context pressure at COMPACT_PCT threshold."""

        class MockConfig:
            context_window = 100_000

        metrics = Metrics(total_tokens_in=85_000)
        pressure = context_pressure(metrics, MockConfig())
        assert pressure == COMPACT_PCT

    def test_context_pressure_at_kill(self):
        """Test context pressure at KILL_PCT threshold."""

        class MockConfig:
            context_window = 100_000

        metrics = Metrics(total_tokens_in=95_000)
        pressure = context_pressure(metrics, MockConfig())
        assert pressure == KILL_PCT

    def test_context_pressure_over_100(self):
        """Test context pressure can exceed 100%."""
        metrics = Metrics(total_tokens_in=300_000)

        class MockConfig:
            context_window = 200_000

        pressure = context_pressure(metrics, MockConfig())
        assert pressure == 150.0

    def test_context_pressure_zero_limit(self):
        """Test context pressure with zero context limit returns 0."""
        metrics = Metrics(total_tokens_in=1000)

        class MockConfig:
            context_window = 0

        pressure = context_pressure(metrics, MockConfig())
        assert pressure == 0.0

    def test_context_pressure_default_limit(self):
        """Test context pressure uses default limit if not specified."""
        metrics = Metrics(total_tokens_in=100_000, total_tokens_out=100_000)

        class MockConfig:
            pass  # No context_window attribute

        pressure = context_pressure(metrics, MockConfig())
        assert pressure == 100.0  # 200k / 200k default

    def test_context_pressure_negative_limit(self):
        """Test context pressure with negative context limit returns 0."""
        metrics = Metrics(total_tokens_in=1000)

        class MockConfig:
            context_window = -100

        pressure = context_pressure(metrics, MockConfig())
        assert pressure == 0.0


class TestIterationKillInfo:
    """Tests for IterationKillInfo dataclass."""

    def test_kill_info_creation(self):
        """Test creating IterationKillInfo."""
        info = IterationKillInfo(
            reason="timeout",
            task_name="test task",
            tokens_used=50_000,
            context_limit=100_000,
            timeout_seconds=300,
            elapsed_seconds=350,
            last_activity="running tests",
        )
        assert info.reason == "timeout"
        assert info.task_name == "test task"
        assert info.tokens_used == 50_000
        assert info.context_limit == 100_000
        assert info.timeout_seconds == 300
        assert info.elapsed_seconds == 350
        assert info.last_activity == "running tests"

    def test_kill_info_to_prompt_none(self):
        """Test to_prompt_injection with reason 'none'."""
        info = IterationKillInfo(reason="none")
        assert info.to_prompt_injection() == ""

    def test_kill_info_to_prompt_timeout(self):
        """Test to_prompt_injection with timeout reason."""
        info = IterationKillInfo(
            reason="timeout",
            task_name="build feature",
            elapsed_seconds=350,
            timeout_seconds=300,
            last_activity="compiling",
        )
        prompt = info.to_prompt_injection()
        assert "timed out" in prompt.lower()
        assert "350" in prompt
        assert "300" in prompt
        assert "build feature" in prompt
        assert "compiling" in prompt

    def test_kill_info_to_prompt_context_limit(self):
        """Test to_prompt_injection with context_limit reason."""
        info = IterationKillInfo(
            reason="context_limit",
            tokens_used=95_000,
            context_limit=100_000,
        )
        prompt = info.to_prompt_injection()
        assert "context limit" in prompt.lower()
        assert "95" in prompt  # 95%


class TestToolSummaries:
    """Tests for ToolSummaries dataclass."""

    def test_tool_summaries_defaults(self):
        """Test ToolSummaries default values."""
        ts = ToolSummaries()
        assert ts.files_read == {}
        assert ts.files_edited == []
        assert ts.searches_performed == []
        assert ts.tests_run == []
        assert ts.subagents_spawned == []

    def test_tool_summaries_custom_values(self):
        """Test ToolSummaries with custom values."""
        ts = ToolSummaries(
            files_read={"file1.py": 100},
            files_edited=["file2.py"],
            searches_performed=["test query"],
            tests_run=["test_example"],
            subagents_spawned=["explore agent"],
        )
        assert ts.files_read == {"file1.py": 100}
        assert ts.files_edited == ["file2.py"]
        assert ts.searches_performed == ["test query"]
        assert ts.tests_run == ["test_example"]
        assert ts.subagents_spawned == ["explore agent"]


class TestCompactedContext:
    """Tests for CompactedContext dataclass."""

    def test_compacted_context_creation(self):
        """Test creating CompactedContext."""
        ctx = CompactedContext(
            task_name="implement feature",
            task_notes="some notes",
            task_accept="tests pass",
            progress_summary="50% done",
            next_step="add tests",
        )
        assert ctx.task_name == "implement feature"
        assert ctx.task_notes == "some notes"
        assert ctx.task_accept == "tests pass"
        assert ctx.progress_summary == "50% done"
        assert ctx.next_step == "add tests"

    def test_compacted_context_defaults(self):
        """Test CompactedContext default values."""
        ctx = CompactedContext(task_name="test")
        assert ctx.task_notes is None
        assert ctx.task_accept is None
        assert ctx.progress_summary == ""
        assert ctx.uncommitted_changes == ""
        assert ctx.key_files == []
        assert ctx.blockers == []
        assert ctx.next_step == ""
        assert ctx.key_decisions == []
        assert ctx.tool_summaries is None

    def test_compacted_context_to_prompt(self):
        """Test to_prompt generates valid markdown."""
        ctx = CompactedContext(
            task_name="implement feature",
            task_notes="implementation details",
            task_accept="all tests pass",
            progress_summary="halfway done",
            key_files=["file1.py", "file2.py"],
            next_step="add validation",
        )
        prompt = ctx.to_prompt()
        assert "## Compacted Context" in prompt
        assert "implement feature" in prompt
        assert "implementation details" in prompt
        assert "all tests pass" in prompt
        assert "halfway done" in prompt
        assert "file1.py" in prompt
        assert "file2.py" in prompt
        assert "add validation" in prompt


class TestLoopDetector:
    """Tests for LoopDetector class."""

    def test_no_loop_on_first_output(self):
        """First output should never trigger loop detection."""
        ld = LoopDetector(threshold=3)
        assert ld.check_output("BUILD|p=['t1']|d=[]|i=[]|s=BUILD") is False

    def test_no_loop_on_different_outputs(self):
        """Different outputs should not trigger loop detection."""
        ld = LoopDetector(threshold=3)
        assert ld.check_output("BUILD|p=['t1']|d=[]|i=[]|s=VERIFY") is False
        assert ld.check_output("BUILD|p=[]|d=['t1']|i=[]|s=VERIFY") is False
        assert ld.check_output("VERIFY|p=[]|d=['t1']|i=[]|s=BUILD") is False

    def test_loop_detected_on_threshold(self):
        """Identical outputs at threshold count should trigger loop."""
        ld = LoopDetector(threshold=3)
        output = "BUILD|p=['t1']|d=[]|i=[]|s=BUILD"
        assert ld.check_output(output) is False  # 1st
        assert ld.check_output(output) is False  # 2nd
        assert ld.check_output(output) is True   # 3rd = threshold

    def test_loop_resets_on_different_output(self):
        """A different output resets the consecutive counter."""
        ld = LoopDetector(threshold=3)
        output_a = "BUILD|p=['t1']|d=[]|i=[]|s=BUILD"
        output_b = "BUILD|p=[]|d=['t1']|i=[]|s=VERIFY"
        assert ld.check_output(output_a) is False  # 1st
        assert ld.check_output(output_a) is False  # 2nd
        assert ld.check_output(output_b) is False  # different -> reset
        assert ld.check_output(output_a) is False  # 1st again
        assert ld.check_output(output_a) is False  # 2nd again
        assert ld.check_output(output_a) is True   # 3rd -> triggered

    def test_reset_clears_state(self):
        """reset() should clear all tracking state."""
        ld = LoopDetector(threshold=3)
        output = "BUILD|p=['t1']|d=[]|i=[]|s=BUILD"
        ld.check_output(output)
        ld.check_output(output)
        ld.reset()
        assert ld.consecutive_identical == 0
        assert ld.last_hash == ""
        assert ld.output_hashes == []

    def test_threshold_of_one(self):
        """Threshold of 1 should trigger on first output."""
        ld = LoopDetector(threshold=1)
        assert ld.check_output("anything") is True
