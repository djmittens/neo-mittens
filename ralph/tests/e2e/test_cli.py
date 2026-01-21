"""End-to-end tests for Ralph CLI.

Tests command parsing, help output, version display, and error handling.
Verifies all commands are accessible and basic argument parsing works.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def temp_git_repo() -> Generator[Path, None, None]:
    """Create a temporary git repository for testing CLI commands."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        subprocess.run(
            ["git", "init"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            capture_output=True,
            check=True,
        )
        yield repo_path


REPO_ROOT = Path(__file__).parent.parent.parent.parent


def run_ralph(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run ralph CLI command and return result.

    Sets PYTHONPATH to include the repo root so ralph package is importable.
    """
    cmd = [sys.executable, "-m", "ralph"] + list(args)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


class TestCLIHelp:
    """Tests for ralph help output."""

    def test_help_flag(self) -> None:
        """Test that --help shows help and exits with 0."""
        result = run_ralph("--help")
        assert result.returncode == 0
        assert "Ralph Wiggum" in result.stdout
        assert "Autonomous AI Development Loop" in result.stdout

    def test_help_command(self) -> None:
        """Test that 'help' command shows help."""
        result = run_ralph("help")
        assert result.returncode == 0
        assert "Ralph Wiggum" in result.stdout

    def test_help_shows_commands(self) -> None:
        """Test that help output lists available commands."""
        result = run_ralph("--help")
        assert result.returncode == 0
        assert "init" in result.stdout
        assert "plan" in result.stdout
        assert "construct" in result.stdout
        assert "config" in result.stdout
        assert "query" in result.stdout
        assert "task" in result.stdout
        assert "issue" in result.stdout
        assert "set-spec" in result.stdout
        assert "status" in result.stdout
        assert "watch" in result.stdout
        assert "stream" in result.stdout

    def test_help_shows_examples(self) -> None:
        """Test that help output shows usage examples."""
        result = run_ralph("--help")
        assert result.returncode == 0
        assert "Examples:" in result.stdout
        assert "ralph init" in result.stdout
        assert "ralph plan" in result.stdout


class TestCLIVersion:
    """Tests for ralph version display."""

    def test_version_flag(self) -> None:
        """Test that --version shows version and exits with 0."""
        result = run_ralph("--version")
        assert result.returncode == 0
        assert "ralph" in result.stdout
        assert "0.1.0" in result.stdout or result.stdout.strip().startswith("ralph ")


class TestCLIConfig:
    """Tests for ralph config command."""

    def test_config_shows_settings(self, temp_git_repo: Path) -> None:
        """Test that 'config' shows current configuration."""
        result = run_ralph("config", cwd=temp_git_repo)
        assert result.returncode == 0
        assert "Global Configuration" in result.stdout
        assert "Model:" in result.stdout
        assert "Context window:" in result.stdout
        assert "Stage timeout:" in result.stdout
        assert "Max failures:" in result.stdout


class TestCLIStatus:
    """Tests for ralph status command."""

    def test_status_without_init(self, temp_git_repo: Path) -> None:
        """Test status before ralph is initialized shows warning message."""
        result = run_ralph("status", cwd=temp_git_repo)
        assert (
            "not initialized" in result.stdout.lower()
            or "not initialized" in result.stderr.lower()
        )

    def test_status_after_init(self, temp_git_repo: Path) -> None:
        """Test status after ralph is initialized."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("status", cwd=temp_git_repo)
        assert result.returncode == 0
        assert "Spec:" in result.stdout
        assert "Stage:" in result.stdout
        assert "Tasks:" in result.stdout
        assert "Issues:" in result.stdout


class TestCLIInit:
    """Tests for ralph init command."""

    def test_init_creates_directory(self, temp_git_repo: Path) -> None:
        """Test that init creates ralph directory."""
        result = run_ralph("init", cwd=temp_git_repo)
        assert result.returncode == 0
        ralph_dir = temp_git_repo / "ralph"
        assert ralph_dir.exists()
        assert ralph_dir.is_dir()

    def test_init_creates_specs_directory(self, temp_git_repo: Path) -> None:
        """Test that init creates specs subdirectory."""
        run_ralph("init", cwd=temp_git_repo)
        specs_dir = temp_git_repo / "ralph" / "specs"
        assert specs_dir.exists()
        assert specs_dir.is_dir()

    def test_init_creates_plan_file(self, temp_git_repo: Path) -> None:
        """Test that init creates plan.jsonl file."""
        run_ralph("init", cwd=temp_git_repo)
        plan_file = temp_git_repo / "ralph" / "plan.jsonl"
        assert plan_file.exists()


class TestCLIQuery:
    """Tests for ralph query command."""

    def test_query_outputs_json(self, temp_git_repo: Path) -> None:
        """Test that query outputs valid JSON."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("query", cwd=temp_git_repo)
        assert result.returncode == 0
        import json

        data = json.loads(result.stdout)
        assert "tasks" in data
        assert "pending" in data["tasks"]
        assert "done" in data["tasks"]

    def test_query_stage(self, temp_git_repo: Path) -> None:
        """Test query stage subcommand."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("query", "stage", cwd=temp_git_repo)
        assert result.returncode == 0
        assert result.stdout.strip() in [
            "INVESTIGATE",
            "BUILD",
            "VERIFY",
            "DECOMPOSE",
            "COMPLETE",
            "PLAN",
        ]

    def test_query_tasks(self, temp_git_repo: Path) -> None:
        """Test query tasks subcommand."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("query", "tasks", cwd=temp_git_repo)
        assert result.returncode == 0
        import json

        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_query_issues(self, temp_git_repo: Path) -> None:
        """Test query issues subcommand."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("query", "issues", cwd=temp_git_repo)
        assert result.returncode == 0
        import json

        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_query_iteration(self, temp_git_repo: Path) -> None:
        """Test query iteration subcommand."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("query", "iteration", cwd=temp_git_repo)
        assert result.returncode == 0
        assert result.stdout.strip().isdigit()


class TestCLITask:
    """Tests for ralph task subcommands."""

    def test_task_no_subcommand_shows_usage(self, temp_git_repo: Path) -> None:
        """Test that 'task' without subcommand shows usage."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("task", cwd=temp_git_repo)
        assert "Usage:" in result.stdout or "done" in result.stdout

    def test_task_add(self, temp_git_repo: Path) -> None:
        """Test adding a task."""
        run_ralph("init", cwd=temp_git_repo)
        run_ralph("set-spec", "test.md", cwd=temp_git_repo)
        (temp_git_repo / "ralph" / "specs" / "test.md").write_text("# Test")
        result = run_ralph("task", "add", "Test task description", cwd=temp_git_repo)
        assert result.returncode == 0
        assert "Task added" in result.stdout

    def test_task_done_no_tasks(self, temp_git_repo: Path) -> None:
        """Test 'task done' when no tasks exist shows message."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("task", "done", cwd=temp_git_repo)
        assert "No pending tasks" in result.stdout


class TestCLIIssue:
    """Tests for ralph issue subcommands."""

    def test_issue_no_subcommand_shows_usage(self, temp_git_repo: Path) -> None:
        """Test that 'issue' without subcommand shows usage."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("issue", cwd=temp_git_repo)
        assert "Usage:" in result.stdout or "done" in result.stdout

    def test_issue_add_requires_spec(self, temp_git_repo: Path) -> None:
        """Test that adding an issue requires a spec to be set."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("issue", "add", "Test issue", cwd=temp_git_repo)
        assert "spec" in result.stdout.lower() or "No spec" in result.stdout

    def test_issue_add_with_spec(self, temp_git_repo: Path) -> None:
        """Test adding an issue when spec is set."""
        run_ralph("init", cwd=temp_git_repo)
        (temp_git_repo / "ralph" / "specs" / "test.md").write_text("# Test")
        run_ralph("set-spec", "test.md", cwd=temp_git_repo)
        result = run_ralph("issue", "add", "Test issue description", cwd=temp_git_repo)
        assert result.returncode == 0
        assert "Issue added" in result.stdout

    def test_issue_done_no_issues(self, temp_git_repo: Path) -> None:
        """Test 'issue done' when no issues exist shows message."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("issue", "done", cwd=temp_git_repo)
        assert "No issues" in result.stdout


class TestCLISetSpec:
    """Tests for ralph set-spec command."""

    def test_set_spec_missing_arg(self, temp_git_repo: Path) -> None:
        """Test set-spec without argument shows usage."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("set-spec", cwd=temp_git_repo)
        assert "Usage:" in result.stdout

    def test_set_spec_file_not_found(self, temp_git_repo: Path) -> None:
        """Test set-spec with non-existent file shows error."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("set-spec", "nonexistent.md", cwd=temp_git_repo)
        assert "not found" in result.stdout.lower()

    def test_set_spec_success(self, temp_git_repo: Path) -> None:
        """Test set-spec with valid spec file."""
        run_ralph("init", cwd=temp_git_repo)
        spec_file = temp_git_repo / "ralph" / "specs" / "myspec.md"
        spec_file.write_text("# My Spec\n\nContent here.")
        result = run_ralph("set-spec", "myspec.md", cwd=temp_git_repo)
        assert result.returncode == 0
        assert "Spec set" in result.stdout


class TestCLIErrorHandling:
    """Tests for CLI error handling."""

    def test_unknown_command(self, temp_git_repo: Path) -> None:
        """Test that unknown command shows error message."""
        result = run_ralph("unknowncommand", cwd=temp_git_repo)
        assert "Unknown command" in result.stdout or "unknowncommand" in result.stdout

    def test_not_in_git_repo(self) -> None:
        """Test error message when not in a git repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_ralph("status", cwd=Path(tmpdir))
            assert (
                "git repository" in result.stdout.lower()
                or "git repository" in result.stderr.lower()
            )


class TestCLIArgumentParsing:
    """Tests for CLI argument parsing."""

    def test_max_cost_argument(self) -> None:
        """Test --max-cost argument is accepted."""
        result = run_ralph("--help")
        assert "--max-cost" in result.stdout

    def test_max_failures_argument(self) -> None:
        """Test --max-failures argument is accepted."""
        result = run_ralph("--help")
        assert "--max-failures" in result.stdout

    def test_timeout_argument(self) -> None:
        """Test --timeout argument is accepted."""
        result = run_ralph("--help")
        assert "--timeout" in result.stdout

    def test_context_limit_argument(self) -> None:
        """Test --context-limit argument is accepted."""
        result = run_ralph("--help")
        assert "--context-limit" in result.stdout

    def test_no_ui_argument(self) -> None:
        """Test --no-ui argument is accepted."""
        result = run_ralph("--help")
        assert "--no-ui" in result.stdout

    def test_profile_argument(self) -> None:
        """Test --profile argument is accepted."""
        result = run_ralph("--help")
        assert "--profile" in result.stdout

    def test_numeric_arg_becomes_construct_iterations(
        self, temp_git_repo: Path
    ) -> None:
        """Test that numeric first argument invokes construct with iterations."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("10", cwd=temp_git_repo)
        assert result.returncode == 0
        assert (
            "Iterations:" in result.stdout
            or "Construct" in result.stdout
            or "not yet implemented" in result.stdout.lower()
        )
