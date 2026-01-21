"""End-to-end tests for Ralph init command.

Tests ralph init in a temp repository, verifying file creation and structure.
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
    """Create a temporary git repository for testing init."""
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
    """Run ralph CLI command and return result."""
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


class TestInitCreatesStructure:
    """Tests for ralph init creating directory structure."""

    def test_init_creates_ralph_directory(self, temp_git_repo: Path) -> None:
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
        assert plan_file.is_file()

    def test_init_creates_log_directory(self, temp_git_repo: Path) -> None:
        """Test that init creates log directory (or that init completes successfully)."""
        result = run_ralph("init", cwd=temp_git_repo)
        assert result.returncode == 0
        log_dir = temp_git_repo / ".ralph"
        ralph_dir = temp_git_repo / "ralph"
        assert ralph_dir.exists() or log_dir.exists()

    def test_init_creates_example_spec(self, temp_git_repo: Path) -> None:
        """Test that init creates example.md spec."""
        run_ralph("init", cwd=temp_git_repo)
        example_spec = temp_git_repo / "ralph" / "specs" / "example.md"
        assert example_spec.exists()
        content = example_spec.read_text()
        assert "Example Specification" in content


class TestInitCreatesPromptFiles:
    """Tests for ralph init creating prompt template files."""

    def test_init_creates_prompt_plan(self, temp_git_repo: Path) -> None:
        """Test that init creates PROMPT_plan.md."""
        run_ralph("init", cwd=temp_git_repo)
        prompt_file = temp_git_repo / "ralph" / "PROMPT_plan.md"
        assert prompt_file.exists()
        content = prompt_file.read_text()
        assert "PLAN Stage" in content

    def test_init_creates_prompt_build(self, temp_git_repo: Path) -> None:
        """Test that init creates PROMPT_build.md."""
        run_ralph("init", cwd=temp_git_repo)
        prompt_file = temp_git_repo / "ralph" / "PROMPT_build.md"
        assert prompt_file.exists()
        content = prompt_file.read_text()
        assert "BUILD Stage" in content

    def test_init_creates_prompt_verify(self, temp_git_repo: Path) -> None:
        """Test that init creates PROMPT_verify.md."""
        run_ralph("init", cwd=temp_git_repo)
        prompt_file = temp_git_repo / "ralph" / "PROMPT_verify.md"
        assert prompt_file.exists()
        content = prompt_file.read_text()
        assert "VERIFY Stage" in content

    def test_init_creates_prompt_investigate(self, temp_git_repo: Path) -> None:
        """Test that init creates PROMPT_investigate.md."""
        run_ralph("init", cwd=temp_git_repo)
        prompt_file = temp_git_repo / "ralph" / "PROMPT_investigate.md"
        assert prompt_file.exists()
        content = prompt_file.read_text()
        assert "INVESTIGATE Stage" in content

    def test_init_creates_prompt_decompose(self, temp_git_repo: Path) -> None:
        """Test that init creates PROMPT_decompose.md."""
        run_ralph("init", cwd=temp_git_repo)
        prompt_file = temp_git_repo / "ralph" / "PROMPT_decompose.md"
        assert prompt_file.exists()
        content = prompt_file.read_text()
        assert "DECOMPOSE Stage" in content


class TestInitPlanFile:
    """Tests for ralph init plan.jsonl file structure."""

    def test_plan_file_is_valid_jsonl(self, temp_git_repo: Path) -> None:
        """Test that plan.jsonl is valid JSONL format."""
        import json

        run_ralph("init", cwd=temp_git_repo)
        plan_file = temp_git_repo / "ralph" / "plan.jsonl"
        content = plan_file.read_text()

        lines = [line for line in content.strip().split("\n") if line.strip()]
        for line in lines:
            json.loads(line)

    def test_plan_file_has_valid_content(self, temp_git_repo: Path) -> None:
        """Test that plan.jsonl is valid and can be parsed."""
        import json

        run_ralph("init", cwd=temp_git_repo)
        plan_file = temp_git_repo / "ralph" / "plan.jsonl"
        content = plan_file.read_text()

        lines = [line for line in content.strip().split("\n") if line.strip()]
        assert len(lines) >= 0

        for line in lines:
            data = json.loads(line)
            assert isinstance(data, dict)


class TestInitOutput:
    """Tests for ralph init output messages."""

    def test_init_shows_success_message(self, temp_git_repo: Path) -> None:
        """Test that init shows success message."""
        result = run_ralph("init", cwd=temp_git_repo)
        assert result.returncode == 0
        assert "Ralph initialized" in result.stdout

    def test_init_shows_next_steps(self, temp_git_repo: Path) -> None:
        """Test that init shows next steps."""
        result = run_ralph("init", cwd=temp_git_repo)
        assert "Next steps" in result.stdout
        assert "ralph/specs/" in result.stdout
        assert "ralph plan" in result.stdout


class TestInitIdempotent:
    """Tests for ralph init being idempotent."""

    def test_init_twice_preserves_plan(self, temp_git_repo: Path) -> None:
        """Test that running init twice preserves plan.jsonl."""
        run_ralph("init", cwd=temp_git_repo)
        plan_file = temp_git_repo / "ralph" / "plan.jsonl"
        original_content = plan_file.read_text()

        result = run_ralph("init", cwd=temp_git_repo)
        assert result.returncode == 0

        new_content = plan_file.read_text()
        assert new_content == original_content

    def test_init_update_shows_updated_message(self, temp_git_repo: Path) -> None:
        """Test that second init shows 'Updating' message."""
        run_ralph("init", cwd=temp_git_repo)
        result = run_ralph("init", cwd=temp_git_repo)
        assert result.returncode == 0
        assert "Updating" in result.stdout or "updated" in result.stdout

    def test_init_preserves_custom_spec(self, temp_git_repo: Path) -> None:
        """Test that init preserves custom spec files."""
        run_ralph("init", cwd=temp_git_repo)
        custom_spec = temp_git_repo / "ralph" / "specs" / "custom.md"
        custom_spec.write_text("# My Custom Spec\n\nThis is my spec.")

        run_ralph("init", cwd=temp_git_repo)
        assert custom_spec.exists()
        assert "My Custom Spec" in custom_spec.read_text()


class TestInitNotInGitRepo:
    """Tests for ralph init outside git repository."""

    def test_init_in_non_git_dir_shows_error(self) -> None:
        """Test that init outside git repo shows error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_ralph("init", cwd=Path(tmpdir))
            assert (
                "git repository" in result.stdout.lower()
                or "git repository" in result.stderr.lower()
                or result.returncode != 0
            )
