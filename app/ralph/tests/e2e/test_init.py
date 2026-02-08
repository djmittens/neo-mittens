"""E2E tests for ralph init command."""

import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).parent.parent.parent.parent


def run_ralph(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Run ralph as subprocess in specified directory."""
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


def test_init_creates_structure(tmp_path: Path):
    """Test that ralph init creates the expected directory structure."""
    result = run_ralph("init", cwd=tmp_path)

    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ralph_dir = tmp_path / "ralph"
    assert ralph_dir.exists(), "ralph/ directory not created"
    assert ralph_dir.is_dir(), "ralph should be a directory"

    specs_dir = ralph_dir / "specs"
    assert specs_dir.exists(), "ralph/specs/ directory not created"
    assert specs_dir.is_dir(), "specs should be a directory"

    # Note: .tix/plan.jsonl is created by tix binary (not available in tests)
    # so we only verify the ralph/ directory structure here.

    example_spec = specs_dir / "example.md"
    assert example_spec.exists(), "ralph/specs/example.md not created"
    assert example_spec.is_file(), "example.md should be a file"

    content = example_spec.read_text()
    assert "Example Specification" in content
    assert "Acceptance Criteria" in content


def test_init_does_not_create_prompt_files(tmp_path: Path):
    """Test that ralph init does NOT create prompt files (they're package-embedded)."""
    result = run_ralph("init", cwd=tmp_path)

    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ralph_dir = tmp_path / "ralph"

    prompt_files = [
        "PROMPT_plan.md",
        "PROMPT_build.md",
        "PROMPT_verify.md",
        "PROMPT_investigate.md",
        "PROMPT_decompose.md",
    ]

    for prompt_file in prompt_files:
        prompt_path = ralph_dir / prompt_file
        assert not prompt_path.exists(), f"{prompt_file} should NOT be created"


def test_init_idempotent(tmp_path: Path):
    """Test that running ralph init twice is safe and preserves specs."""
    result1 = run_ralph("init", cwd=tmp_path)
    assert result1.returncode == 0, f"First init failed: {result1.stderr}"

    ralph_dir = tmp_path / "ralph"

    custom_spec = ralph_dir / "specs" / "custom.md"
    custom_spec.write_text("# Custom Spec\n\nMy custom specification.\n")

    result2 = run_ralph("init", cwd=tmp_path)
    assert result2.returncode == 0, f"Second init failed: {result2.stderr}"

    assert custom_spec.exists(), "Custom spec should be preserved"
    assert "Custom Spec" in custom_spec.read_text()

    example_spec = ralph_dir / "specs" / "example.md"
    assert example_spec.exists(), "example.md should still exist"

    assert "already initialized" in result2.stdout.lower()
