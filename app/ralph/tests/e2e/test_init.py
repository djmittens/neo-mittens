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

    plan_file = ralph_dir / "plan.jsonl"
    assert plan_file.exists(), "ralph/plan.jsonl not created"
    assert plan_file.is_file(), "plan.jsonl should be a file"

    example_spec = specs_dir / "example.md"
    assert example_spec.exists(), "ralph/specs/example.md not created"
    assert example_spec.is_file(), "example.md should be a file"

    content = example_spec.read_text()
    assert "Example Specification" in content
    assert "Acceptance Criteria" in content


def test_init_creates_prompts(tmp_path: Path):
    """Test that ralph init creates all prompt template files."""
    result = run_ralph("init", cwd=tmp_path)

    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ralph_dir = tmp_path / "ralph"

    expected_prompts = [
        "PROMPT_plan.md",
        "PROMPT_build.md",
        "PROMPT_verify.md",
        "PROMPT_investigate.md",
        "PROMPT_decompose.md",
    ]

    for prompt_file in expected_prompts:
        prompt_path = ralph_dir / prompt_file
        assert prompt_path.exists(), f"{prompt_file} not created"
        assert prompt_path.is_file(), f"{prompt_file} should be a file"

        content = prompt_path.read_text()
        assert len(content) > 100, f"{prompt_file} appears to be too short"

    plan_prompt = ralph_dir / "PROMPT_plan.md"
    content = plan_prompt.read_text()
    assert "PLAN Stage" in content or "ralph task add" in content

    build_prompt = ralph_dir / "PROMPT_build.md"
    content = build_prompt.read_text()
    assert "BUILD Stage" in content or "ralph query" in content

    verify_prompt = ralph_dir / "PROMPT_verify.md"
    content = verify_prompt.read_text()
    assert "VERIFY Stage" in content or "acceptance criteria" in content.lower()

    investigate_prompt = ralph_dir / "PROMPT_investigate.md"
    content = investigate_prompt.read_text()
    assert "INVESTIGATE Stage" in content or "issues" in content.lower()

    decompose_prompt = ralph_dir / "PROMPT_decompose.md"
    content = decompose_prompt.read_text()
    assert "DECOMPOSE Stage" in content or "subtask" in content.lower()


def test_init_idempotent(tmp_path: Path):
    """Test that running ralph init twice is idempotent and preserves files."""
    result1 = run_ralph("init", cwd=tmp_path)
    assert result1.returncode == 0, f"First init failed: {result1.stderr}"

    ralph_dir = tmp_path / "ralph"
    plan_file = ralph_dir / "plan.jsonl"
    original_plan_content = plan_file.read_text()

    custom_spec = ralph_dir / "specs" / "custom.md"
    custom_spec.write_text("# Custom Spec\n\nMy custom specification.\n")

    result2 = run_ralph("init", cwd=tmp_path)
    assert result2.returncode == 0, f"Second init failed: {result2.stderr}"

    assert plan_file.exists(), "plan.jsonl should still exist"
    new_plan_content = plan_file.read_text()
    assert new_plan_content == original_plan_content, "plan.jsonl should be preserved"

    assert custom_spec.exists(), "Custom spec should be preserved"
    assert "Custom Spec" in custom_spec.read_text()

    expected_prompts = [
        "PROMPT_plan.md",
        "PROMPT_build.md",
        "PROMPT_verify.md",
        "PROMPT_investigate.md",
        "PROMPT_decompose.md",
    ]
    for prompt_file in expected_prompts:
        assert (ralph_dir / prompt_file).exists(), f"{prompt_file} should still exist"

    example_spec = ralph_dir / "specs" / "example.md"
    assert example_spec.exists(), "example.md should still exist"

    assert "Updating Ralph" in result2.stdout or "updated" in result2.stdout.lower()
