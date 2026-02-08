"""Unit tests for ralph.commands.compare module."""

import json
import pytest
from pathlib import Path

from ralph.commands.compare import (
    _format_duration,
    _format_tokens,
    cmd_compare,
)
from ralph.config import GlobalConfig
from ralph.ledger import RunRecord, TokenBreakdown, write_run


class TestFormatDuration:
    """Tests for _format_duration helper."""

    def test_seconds_only(self):
        """Test formatting under 60 seconds."""
        assert _format_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        """Test formatting minutes and seconds."""
        assert _format_duration(125) == "2m05s"

    def test_hours_and_minutes(self):
        """Test formatting hours and minutes."""
        assert _format_duration(3900) == "1h05m"

    def test_zero(self):
        """Test formatting zero seconds."""
        assert _format_duration(0) == "0s"


class TestFormatTokens:
    """Tests for _format_tokens helper."""

    def test_small_count(self):
        """Test formatting under 1000."""
        assert _format_tokens(500) == "500"

    def test_thousands(self):
        """Test formatting thousands."""
        assert _format_tokens(150_000) == "150K"

    def test_millions(self):
        """Test formatting millions."""
        assert _format_tokens(1_200_000) == "1.2M"


class TestCmdCompare:
    """Tests for cmd_compare function."""

    def _make_config(self, tmp_path: Path) -> GlobalConfig:
        """Create a config pointing to tmp_path for log_dir."""
        return GlobalConfig(log_dir=str(tmp_path))

    def _make_args(self, **kwargs):
        """Create a mock args namespace."""
        import argparse
        args = argparse.Namespace()
        args.spec = kwargs.get("spec", None)
        args.profile_filter = kwargs.get("profile_filter", None)
        args.json = kwargs.get("json", False)
        return args

    def test_empty_ledger(self, tmp_path: Path, capsys):
        """Test compare with no runs."""
        cfg = self._make_config(tmp_path)
        result = cmd_compare(cfg, self._make_args())
        assert result == 0
        out = capsys.readouterr().out
        assert "No runs found" in out

    def test_single_run(self, tmp_path: Path, capsys):
        """Test compare with one run."""
        rr = RunRecord(
            run_id="run_001", spec="gc.md", profile="opus",
            branch="main", exit_reason="complete",
            iterations=5, cost=1.0, duration_s=300,
            tokens=TokenBreakdown(input=50000, cached=10000, output=20000),
        )
        write_run(tmp_path, rr)
        cfg = self._make_config(tmp_path)
        result = cmd_compare(cfg, self._make_args())
        assert result == 0
        out = capsys.readouterr().out
        assert "gc.md" in out
        assert "opus" in out

    def test_spec_filter(self, tmp_path: Path, capsys):
        """Test filtering by spec."""
        write_run(tmp_path, RunRecord(run_id="r1", spec="gc.md"))
        write_run(tmp_path, RunRecord(run_id="r2", spec="other.md"))
        cfg = self._make_config(tmp_path)
        result = cmd_compare(cfg, self._make_args(spec="gc.md"))
        assert result == 0
        out = capsys.readouterr().out
        assert "gc.md" in out
        assert "other.md" not in out

    def test_json_output(self, tmp_path: Path, capsys):
        """Test JSON output mode."""
        write_run(tmp_path, RunRecord(run_id="r1", spec="gc.md", cost=1.5))
        cfg = self._make_config(tmp_path)
        result = cmd_compare(cfg, self._make_args(json=True))
        assert result == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data) == 1
        assert data[0]["run_id"] == "r1"

    def test_profile_filter(self, tmp_path: Path, capsys):
        """Test filtering by profile."""
        write_run(tmp_path, RunRecord(run_id="r1", spec="gc.md", profile="opus"))
        write_run(tmp_path, RunRecord(run_id="r2", spec="gc.md", profile="sonnet"))
        cfg = self._make_config(tmp_path)
        result = cmd_compare(cfg, self._make_args(profile_filter="opus"))
        assert result == 0
        out = capsys.readouterr().out
        assert "opus" in out

    def test_multiple_specs_grouped(self, tmp_path: Path, capsys):
        """Test runs grouped by spec."""
        write_run(tmp_path, RunRecord(run_id="r1", spec="gc.md", profile="opus"))
        write_run(tmp_path, RunRecord(run_id="r2", spec="refactor.md", profile="sonnet"))
        cfg = self._make_config(tmp_path)
        result = cmd_compare(cfg, self._make_args())
        assert result == 0
        out = capsys.readouterr().out
        assert "gc.md" in out
        assert "refactor.md" in out
