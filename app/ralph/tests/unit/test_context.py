"""Unit tests for ralph.context module."""

import pytest
from ralph.context import (
    Metrics,
    LoopDetector,
    IterationKillInfo,
    ToolSummaries,
    CompactedContext,
    SessionSummary,
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


class TestMetricsNewFields:
    """Tests for new Metrics fields added for measurement system."""

    def test_cached_tokens_default(self):
        """Test total_tokens_cached defaults to 0."""
        m = Metrics()
        assert m.total_tokens_cached == 0

    def test_api_calls_default(self):
        """Test API call counters default to 0."""
        m = Metrics()
        assert m.api_calls_remote == 0
        assert m.api_calls_local == 0

    def test_validation_retries_default(self):
        """Test validation_retries defaults to 0."""
        m = Metrics()
        assert m.validation_retries == 0

    def test_tokens_used_includes_cached(self):
        """Test tokens_used property includes cached tokens."""
        m = Metrics(total_tokens_in=1000, total_tokens_cached=200, total_tokens_out=500)
        assert m.tokens_used == 1700

    def test_record_progress_sets_timestamp(self):
        """Test record_progress sets last_progress_time."""
        m = Metrics()
        assert m.last_progress_time == 0.0
        m.record_progress()
        assert m.last_progress_time > 0

    def test_seconds_since_progress_zero_when_never_recorded(self):
        """Test seconds_since_progress returns 0 when never recorded."""
        m = Metrics()
        assert m.seconds_since_progress() == 0.0

    def test_seconds_since_progress_after_record(self):
        """Test seconds_since_progress returns positive after recording."""
        import time
        m = Metrics()
        m.record_progress()
        time.sleep(0.01)
        assert m.seconds_since_progress() > 0


class TestSessionSummaryNewFields:
    """Tests for new SessionSummary fields."""

    def test_to_dict_includes_cached_tokens(self):
        """Test to_dict includes cached token count."""
        s = SessionSummary(
            started_at="2026-01-01T00:00:00",
            ended_at="2026-01-01T01:00:00",
            duration_seconds=3600,
            total_iterations=10,
            tasks_completed=5,
            commits_made=3,
            total_tokens_in=50000,
            total_tokens_cached=10000,
            total_tokens_out=20000,
            total_cost=1.0,
            failures=1,
            successes=9,
            kills_timeout=0,
            kills_context=0,
            kills_loop=0,
            api_calls_remote=10,
            api_calls_local=0,
            exit_reason="complete",
            spec="test.md",
            profile="opus",
        )
        d = s.to_dict()
        assert d["tokens"]["cached"] == 10000
        assert d["tokens"]["total"] == 80000  # 50k + 10k + 20k
        assert d["api_calls"]["remote"] == 10
        assert d["api_calls"]["local"] == 0

    def test_from_metrics_maps_new_fields(self):
        """Test from_metrics maps all new Metrics fields."""
        m = Metrics(
            total_tokens_in=5000,
            total_tokens_cached=1000,
            total_tokens_out=2000,
            api_calls_remote=8,
            api_calls_local=3,
            started_at="2026-01-01T00:00:00",
        )
        s = SessionSummary.from_metrics(
            metrics=m,
            exit_reason="complete",
            spec="test.md",
            profile="opus",
            ended_at="2026-01-01T00:10:00",
        )
        assert s.total_tokens_cached == 1000
        assert s.api_calls_remote == 8
        assert s.api_calls_local == 3


class TestMetricsModelTracking:
    """Tests for model and finish_reason tracking."""

    def test_last_model_default(self):
        """Test last_model defaults to empty string."""
        m = Metrics()
        assert m.last_model == ""

    def test_last_finish_reason_default(self):
        """Test last_finish_reason defaults to empty string."""
        m = Metrics()
        assert m.last_finish_reason == ""

    def test_last_kill_activity_removed(self):
        """Verify last_kill_activity field no longer exists."""
        m = Metrics()
        assert not hasattr(m, "last_kill_activity")


class TestProcessEvent:
    """Tests for _process_event capturing model/finish_reason from step_finish."""

    def test_step_finish_captures_model(self):
        """_process_event sets last_model from step_finish part."""
        from ralph.opencode import _process_event

        m = Metrics()
        event = {
            "type": "step_finish",
            "part": {
                "cost": 0.01,
                "tokens": {"input": 100, "output": 50, "cache": {}},
                "model": "claude-opus-4-20260801",
                "finish_reason": "stop",
            },
        }
        _process_event(event, m)
        assert m.last_model == "claude-opus-4-20260801"
        assert m.last_finish_reason == "stop"

    def test_step_finish_captures_finish_reason_tool_use(self):
        """_process_event captures tool_use finish_reason."""
        from ralph.opencode import _process_event

        m = Metrics()
        event = {
            "type": "step_finish",
            "part": {
                "cost": 0.02,
                "tokens": {"input": 200, "output": 100, "cache": {}},
                "model": "claude-sonnet-4-20260514",
                "finish_reason": "tool_use",
            },
        }
        _process_event(event, m)
        assert m.last_finish_reason == "tool_use"

    def test_step_finish_without_model_preserves_previous(self):
        """_process_event does not overwrite model if absent in event."""
        from ralph.opencode import _process_event

        m = Metrics()
        m.last_model = "previous-model"
        event = {
            "type": "step_finish",
            "part": {
                "cost": 0.01,
                "tokens": {"input": 100, "output": 50, "cache": {}},
            },
        }
        _process_event(event, m)
        assert m.last_model == "previous-model"

    def test_step_finish_without_finish_reason_preserves_previous(self):
        """_process_event does not overwrite finish_reason if absent."""
        from ralph.opencode import _process_event

        m = Metrics()
        m.last_finish_reason = "stop"
        event = {
            "type": "step_finish",
            "part": {
                "cost": 0.01,
                "tokens": {"input": 100, "output": 50, "cache": {}},
                "model": "opus",
            },
        }
        _process_event(event, m)
        assert m.last_finish_reason == "stop"

    def test_step_finish_accumulates_cached_tokens(self):
        """_process_event adds cache read tokens to total_tokens_cached."""
        from ralph.opencode import _process_event

        m = Metrics()
        event = {
            "type": "step_finish",
            "part": {
                "cost": 0.01,
                "tokens": {"input": 100, "output": 50, "cache": {"read": 500}},
            },
        }
        _process_event(event, m)
        assert m.total_tokens_cached == 500
        assert m.total_tokens_in == 100
        assert m.total_tokens_out == 50

    def test_step_finish_empty_model_string_not_set(self):
        """_process_event ignores empty string model."""
        from ralph.opencode import _process_event

        m = Metrics()
        m.last_model = "previous"
        event = {
            "type": "step_finish",
            "part": {
                "cost": 0.01,
                "tokens": {"input": 100, "output": 50, "cache": {}},
                "model": "",
                "finish_reason": "",
            },
        }
        _process_event(event, m)
        assert m.last_model == "previous"

    def test_non_step_finish_event_ignored(self):
        """_process_event does not modify metrics for text events."""
        from ralph.opencode import _process_event

        m = Metrics()
        event = {"type": "text", "part": {"text": "hello"}}
        _process_event(event, m)
        assert m.last_model == ""
        assert m.total_cost == 0.0
