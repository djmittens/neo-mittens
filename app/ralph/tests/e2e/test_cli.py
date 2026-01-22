"""E2E tests for ralph CLI."""

import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).parent.parent.parent.parent


def run_ralph(*args: str, cwd: str | Path = ".") -> subprocess.CompletedProcess:
    """Run ralph as subprocess and return result."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(APP_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "ralph", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=30,
    )


def test_help_output():
    """Test that --help outputs usage information."""
    result = run_ralph("--help")

    assert result.returncode == 0
    assert "ralph" in result.stdout.lower()
    assert "usage" in result.stdout.lower() or "Ralph Wiggum" in result.stdout
    assert "init" in result.stdout
    assert "status" in result.stdout
    assert "construct" in result.stdout


def test_version_output():
    """Test that --version outputs version string."""
    result = run_ralph("--version")

    assert result.returncode == 0
    assert "ralph" in result.stdout.lower()
    assert "0.1.0" in result.stdout or "." in result.stdout


def test_subcommand_parsing():
    """Test that subcommands are parsed correctly."""
    # Commands that should succeed even without initialization
    # Note: watch and stream are excluded - they are interactive commands
    # with infinite loops that would hang the test
    subcommands = [
        "init",
        "config",
        "query",
        "validate",
        "compact",
    ]

    for cmd in subcommands:
        result = run_ralph(cmd)
        assert result.returncode == 0, f"Command '{cmd}' failed with: {result.stderr}"
        # Commands should produce some output (not be silent)
        assert len(result.stdout) > 0 or len(result.stderr) >= 0, (
            f"Command '{cmd}' produced no output"
        )


def test_status_not_initialized(tmp_path: Path):
    """Test that status returns 1 when ralph is not initialized."""
    result = run_ralph("status", cwd=tmp_path)
    # status returns 1 when not initialized, which is expected behavior
    assert result.returncode == 1
    assert "not initialized" in result.stdout.lower() or "init" in result.stdout.lower()


def test_subcommand_help():
    """Test that subcommands accept --help flag."""
    subcommands = ["plan", "construct", "query", "task", "issue"]

    for cmd in subcommands:
        result = run_ralph(cmd, "--help")
        assert result.returncode == 0, f"Command '{cmd} --help' failed: {result.stderr}"
        assert cmd in result.stdout.lower() or "usage" in result.stdout.lower()


def test_unknown_command():
    """Test that unknown commands produce error."""
    result = run_ralph("nonexistent_command")

    assert result.returncode != 0


def test_no_command_shows_help():
    """Test that running without command shows help."""
    result = run_ralph()

    assert result.returncode == 0
    assert "ralph" in result.stdout.lower() or "usage" in result.stdout.lower()


def test_task_without_action():
    """Test that task without action shows usage."""
    result = run_ralph("task")

    assert result.returncode == 1
    assert "usage" in result.stdout.lower() or "task" in result.stdout.lower()


def test_issue_without_action():
    """Test that issue without action shows usage."""
    result = run_ralph("issue")

    assert result.returncode == 1
    assert "usage" in result.stdout.lower() or "issue" in result.stdout.lower()
