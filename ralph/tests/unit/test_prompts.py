"""Unit tests for ralph.prompts module - prompt building and merging."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ralph.prompts import (
    build_prompt_with_rules,
    find_project_rules,
    get_prompt_for_stage,
    get_ralph_dir,
    load_prompt,
    merge_prompts,
    substitute_spec_file,
)


class TestGetRalphDir:
    """Tests for get_ralph_dir function."""

    def test_returns_path(self) -> None:
        """Test that get_ralph_dir returns a Path object."""
        result = get_ralph_dir()
        assert isinstance(result, Path)

    def test_points_to_ralph_module(self) -> None:
        """Test that get_ralph_dir points to the ralph module directory."""
        result = get_ralph_dir()
        assert result.name == "ralph" or "ralph" in str(result)


class TestLoadPrompt:
    """Tests for load_prompt function."""

    def test_load_build_prompt(self) -> None:
        """Test loading the build stage prompt."""
        content = load_prompt("build")
        assert isinstance(content, str)
        assert len(content) > 0

    def test_load_verify_prompt(self) -> None:
        """Test loading the verify stage prompt."""
        content = load_prompt("verify")
        assert isinstance(content, str)
        assert len(content) > 0

    def test_load_plan_prompt(self) -> None:
        """Test loading the plan stage prompt."""
        content = load_prompt("plan")
        assert isinstance(content, str)
        assert len(content) > 0

    def test_case_insensitive(self) -> None:
        """Test that stage names are case-insensitive."""
        lower = load_prompt("build")
        upper = load_prompt("BUILD")
        mixed = load_prompt("Build")
        assert lower == upper == mixed

    def test_nonexistent_prompt_raises(self) -> None:
        """Test that loading non-existent prompt raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_prompt("nonexistent_stage_xyz")


class TestFindProjectRules:
    """Tests for find_project_rules function."""

    def test_finds_agents_md(self) -> None:
        """Test finding AGENTS.md in repo root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            agents_file = repo_root / "AGENTS.md"
            agents_file.write_text("# Project Rules\nFollow these rules.")

            result = find_project_rules(repo_root)
            assert result == "# Project Rules\nFollow these rules."

    def test_finds_claude_md(self) -> None:
        """Test finding CLAUDE.md in repo root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            claude_file = repo_root / "CLAUDE.md"
            claude_file.write_text("# Claude Instructions")

            result = find_project_rules(repo_root)
            assert result == "# Claude Instructions"

    def test_prefers_agents_over_claude(self) -> None:
        """Test that AGENTS.md takes precedence over CLAUDE.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            (repo_root / "AGENTS.md").write_text("AGENTS content")
            (repo_root / "CLAUDE.md").write_text("CLAUDE content")

            result = find_project_rules(repo_root)
            assert result == "AGENTS content"

    def test_returns_none_when_no_rules(self) -> None:
        """Test returns None when no rules files exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            result = find_project_rules(repo_root)
            assert result is None


class TestBuildPromptWithRules:
    """Tests for build_prompt_with_rules function."""

    def test_no_rules_returns_original(self) -> None:
        """Test that no rules returns original prompt."""
        prompt = "Do the task."
        result = build_prompt_with_rules(prompt, None)
        assert result == "Do the task."

    def test_empty_rules_returns_original(self) -> None:
        """Test that empty rules returns original prompt."""
        prompt = "Do the task."
        result = build_prompt_with_rules(prompt, "")
        assert result == "Do the task."

    def test_prepends_rules(self) -> None:
        """Test that rules are prepended to prompt."""
        prompt = "Do the task."
        rules = "Follow coding standards."
        result = build_prompt_with_rules(prompt, rules)
        assert "Follow coding standards." in result
        assert "Do the task." in result
        assert result.index("Follow coding standards.") < result.index("Do the task.")

    def test_includes_header(self) -> None:
        """Test that combined prompt includes proper headers."""
        prompt = "Task content"
        rules = "Rule content"
        result = build_prompt_with_rules(prompt, rules)
        assert "Project Rules" in result
        assert "Ralph Task" in result

    def test_includes_separator(self) -> None:
        """Test that combined prompt includes separator."""
        prompt = "Task content"
        rules = "Rule content"
        result = build_prompt_with_rules(prompt, rules)
        assert "---" in result

    def test_mandatory_notice(self) -> None:
        """Test that combined prompt includes MANDATORY notice."""
        prompt = "Task content"
        rules = "Rule content"
        result = build_prompt_with_rules(prompt, rules)
        assert "MANDATORY" in result


class TestGetPromptForStage:
    """Tests for get_prompt_for_stage function."""

    def test_plan_mode_returns_plan_prompt(self) -> None:
        """Test that plan mode returns plan prompt path."""
        result = get_prompt_for_stage("BUILD", mode="plan")
        assert result.name == "PROMPT_plan.md"

    def test_verify_stage(self) -> None:
        """Test VERIFY stage returns verify prompt path."""
        result = get_prompt_for_stage("VERIFY", mode="construct")
        assert result.name == "PROMPT_verify.md"

    def test_investigate_stage(self) -> None:
        """Test INVESTIGATE stage returns investigate prompt path."""
        result = get_prompt_for_stage("INVESTIGATE", mode="construct")
        assert result.name == "PROMPT_investigate.md"

    def test_decompose_stage(self) -> None:
        """Test DECOMPOSE stage returns decompose prompt path."""
        result = get_prompt_for_stage("DECOMPOSE", mode="construct")
        assert result.name == "PROMPT_decompose.md"

    def test_build_stage_default(self) -> None:
        """Test BUILD stage returns build prompt path."""
        result = get_prompt_for_stage("BUILD", mode="construct")
        assert result.name == "PROMPT_build.md"

    def test_unknown_stage_returns_build(self) -> None:
        """Test unknown stage defaults to build prompt path."""
        result = get_prompt_for_stage("UNKNOWN", mode="construct")
        assert result.name == "PROMPT_build.md"

    def test_case_insensitive_stage(self) -> None:
        """Test stage matching is case-insensitive."""
        upper = get_prompt_for_stage("VERIFY", mode="construct")
        lower = get_prompt_for_stage("verify", mode="construct")
        mixed = get_prompt_for_stage("Verify", mode="construct")
        assert upper == lower == mixed

    def test_stage_enum_support(self) -> None:
        """Test that Stage enum-like objects work."""

        class MockStage:
            name = "VERIFY"

        result = get_prompt_for_stage(MockStage(), mode="construct")
        assert result.name == "PROMPT_verify.md"


class TestMergePrompts:
    """Tests for merge_prompts function."""

    @patch("ralph.prompts.subprocess.run")
    def test_successful_merge(self, mock_run: MagicMock) -> None:
        """Test successful merge returns merged content."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Merged content here",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = merge_prompts(
                "existing content",
                "new template",
                "PROMPT_build.md",
                Path(tmpdir),
            )
            assert result == "Merged content here"

    @patch("ralph.prompts.subprocess.run")
    def test_failed_merge_returns_none(self, mock_run: MagicMock) -> None:
        """Test failed merge returns None."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = merge_prompts(
                "existing content",
                "new template",
                "PROMPT_build.md",
                Path(tmpdir),
            )
            assert result is None

    @patch("ralph.prompts.subprocess.run")
    def test_empty_output_returns_none(self, mock_run: MagicMock) -> None:
        """Test empty output returns None."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = merge_prompts(
                "existing content",
                "new template",
                "PROMPT_build.md",
                Path(tmpdir),
            )
            assert result is None

    @patch("ralph.prompts.subprocess.run")
    def test_strips_markdown_code_blocks(self, mock_run: MagicMock) -> None:
        """Test that markdown code blocks are stripped from output."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="```\nMerged content\n```",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = merge_prompts(
                "existing content",
                "new template",
                "PROMPT_build.md",
                Path(tmpdir),
            )
            assert result == "Merged content"

    @patch("ralph.prompts.subprocess.run")
    def test_timeout_returns_none(self, mock_run: MagicMock) -> None:
        """Test timeout returns None."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 120)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = merge_prompts(
                "existing content",
                "new template",
                "PROMPT_build.md",
                Path(tmpdir),
            )
            assert result is None

    @patch("ralph.prompts.subprocess.run")
    def test_opencode_not_found_returns_none(self, mock_run: MagicMock) -> None:
        """Test opencode not found returns None."""
        mock_run.side_effect = FileNotFoundError("opencode not found")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = merge_prompts(
                "existing content",
                "new template",
                "PROMPT_build.md",
                Path(tmpdir),
            )
            assert result is None

    @patch("ralph.prompts.subprocess.run")
    def test_uses_correct_environment(self, mock_run: MagicMock) -> None:
        """Test that merge_prompts sets correct environment variables."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Merged",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            merge_prompts(
                "existing",
                "new",
                "file.md",
                Path(tmpdir),
            )
            call_kwargs = mock_run.call_args.kwargs
            env = call_kwargs.get("env", {})
            assert "XDG_STATE_HOME" in env
            assert "OPENCODE_PERMISSION" in env


class TestSubstituteSpecFile:
    """Tests for substitute_spec_file function."""

    def test_substitutes_placeholder(self) -> None:
        """Test that {{SPEC_FILE}} is replaced."""
        content = "Read the spec at ralph/specs/{{SPEC_FILE}}"
        result = substitute_spec_file(content, "my-feature.md")
        assert result == "Read the spec at ralph/specs/my-feature.md"

    def test_multiple_placeholders(self) -> None:
        """Test that multiple placeholders are replaced."""
        content = "Spec: {{SPEC_FILE}}, also {{SPEC_FILE}}"
        result = substitute_spec_file(content, "test.md")
        assert result == "Spec: test.md, also test.md"

    def test_no_placeholder_unchanged(self) -> None:
        """Test that content without placeholder is unchanged."""
        content = "No placeholder here"
        result = substitute_spec_file(content, "spec.md")
        assert result == "No placeholder here"

    def test_empty_spec_file(self) -> None:
        """Test with empty spec file name."""
        content = "Spec: {{SPEC_FILE}}"
        result = substitute_spec_file(content, "")
        assert result == "Spec: "

    def test_spec_file_with_path(self) -> None:
        """Test with spec file containing path."""
        content = "Use {{SPEC_FILE}}"
        result = substitute_spec_file(content, "feature/my-spec.md")
        assert result == "Use feature/my-spec.md"
