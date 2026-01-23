"""Unit tests for ralph.prompts module."""

import pytest
from pathlib import Path

from ralph.prompts import (
    load_prompt,
    build_prompt_with_rules,
    merge_prompts,
    find_project_rules,
)


class TestLoadPrompt:
    """Tests for load_prompt function."""

    def test_load_prompt_success(self, tmp_path):
        """Test loading a prompt file successfully."""
        ralph_dir = tmp_path / "ralph"
        ralph_dir.mkdir()
        prompt_file = ralph_dir / "PROMPT_build.md"
        prompt_content = "# BUILD Stage\n\nThis is the build prompt."
        prompt_file.write_text(prompt_content)

        result = load_prompt("build", ralph_dir=ralph_dir)

        assert result == prompt_content

    def test_load_prompt_different_stages(self, tmp_path):
        """Test loading prompts for different stages."""
        ralph_dir = tmp_path / "ralph"
        ralph_dir.mkdir()

        stages = ["plan", "build", "verify", "investigate", "decompose"]
        for stage in stages:
            prompt_file = ralph_dir / f"PROMPT_{stage}.md"
            prompt_file.write_text(f"Content for {stage}")

        for stage in stages:
            result = load_prompt(stage, ralph_dir=ralph_dir)
            assert result == f"Content for {stage}"

    def test_load_prompt_file_not_found(self, tmp_path):
        """Test FileNotFoundError when prompt file doesn't exist."""
        ralph_dir = tmp_path / "ralph"
        ralph_dir.mkdir()

        with pytest.raises(FileNotFoundError) as exc_info:
            load_prompt("nonexistent", ralph_dir=ralph_dir)

        assert "PROMPT_nonexistent.md" in str(exc_info.value)

    def test_load_prompt_empty_file(self, tmp_path):
        """Test loading an empty prompt file."""
        ralph_dir = tmp_path / "ralph"
        ralph_dir.mkdir()
        prompt_file = ralph_dir / "PROMPT_test.md"
        prompt_file.write_text("")

        result = load_prompt("test", ralph_dir=ralph_dir)

        assert result == ""

    def test_load_prompt_with_unicode(self, tmp_path):
        """Test loading prompt with unicode characters."""
        ralph_dir = tmp_path / "ralph"
        ralph_dir.mkdir()
        prompt_file = ralph_dir / "PROMPT_unicode.md"
        unicode_content = (
            "# Prompt with Unicode\n\nSymbols: \u2713 \u2717 \u2022\nEmoji: \U0001f680"
        )
        prompt_file.write_text(unicode_content)

        result = load_prompt("unicode", ralph_dir=ralph_dir)

        assert result == unicode_content


class TestBuildPromptWithRules:
    """Tests for build_prompt_with_rules function."""

    def test_build_prompt_with_rules_success(self, tmp_path):
        """Test combining prompt with rules file."""
        rules_file = tmp_path / "AGENTS.md"
        rules_content = "# Project Rules\n\n- Rule 1\n- Rule 2"
        rules_file.write_text(rules_content)

        prompt = "# Task\n\nDo something important."

        result = build_prompt_with_rules(prompt, rules_file)

        assert "Project Rules (from AGENTS.md)" in result
        assert "MANDATORY" in result
        assert rules_content in result
        assert "# Ralph Task" in result
        assert prompt in result

    def test_build_prompt_with_rules_no_rules_file(self, tmp_path):
        """Test returns original prompt when rules file doesn't exist."""
        rules_file = tmp_path / "nonexistent.md"
        prompt = "# Task\n\nDo something."

        result = build_prompt_with_rules(prompt, rules_file)

        assert result == prompt

    def test_build_prompt_with_rules_empty_rules(self, tmp_path):
        """Test returns original prompt when rules file is empty."""
        rules_file = tmp_path / "AGENTS.md"
        rules_file.write_text("")
        prompt = "# Task\n\nDo something."

        result = build_prompt_with_rules(prompt, rules_file)

        assert result == prompt

    def test_build_prompt_with_rules_whitespace_only(self, tmp_path):
        """Test returns original prompt when rules file is whitespace only."""
        rules_file = tmp_path / "AGENTS.md"
        rules_file.write_text("   \n\n   \t  ")
        prompt = "# Task\n\nDo something."

        result = build_prompt_with_rules(prompt, rules_file)

        assert result == prompt

    def test_build_prompt_with_rules_structure(self, tmp_path):
        """Test the structure of the combined prompt."""
        rules_file = tmp_path / "RULES.md"
        rules_file.write_text("Follow these rules.")
        prompt = "Execute this task."

        result = build_prompt_with_rules(prompt, rules_file)

        lines = result.split("\n")
        header_found = any("Project Rules" in line for line in lines)
        task_header_found = any("Ralph Task" in line for line in lines)

        assert header_found
        assert task_header_found
        assert result.index("Project Rules") < result.index("Ralph Task")


class TestMergePrompts:
    """Tests for merge_prompts function."""

    def test_merge_prompts_keep_strategy(self):
        """Test merge with 'keep' strategy returns old content."""
        old = "Old prompt content"
        new = "New prompt content"

        result = merge_prompts(old, new, "keep")

        assert result == old

    def test_merge_prompts_override_strategy(self):
        """Test merge with 'override' strategy returns new content."""
        old = "Old prompt content"
        new = "New prompt content"

        result = merge_prompts(old, new, "override")

        assert result == new

    def test_merge_prompts_merge_strategy_different_content(self):
        """Test merge strategy with different content creates merged document."""
        old = "Customized prompt with special rules"
        new = "Default template prompt"

        result = merge_prompts(old, new, "merge")

        assert "MERGED PROMPT" in result
        assert "EXISTING CONTENT" in result
        assert "NEW TEMPLATE" in result
        assert old in result
        assert new in result

    def test_merge_prompts_merge_strategy_identical_content(self):
        """Test merge strategy with identical content returns new content."""
        content = "Identical prompt content"

        result = merge_prompts(content, content, "merge")

        assert result == content
        assert "MERGED PROMPT" not in result

    def test_merge_prompts_merge_strategy_whitespace_diff(self):
        """Test merge strategy ignores leading/trailing whitespace."""
        old = "  Same content  "
        new = "Same content"

        result = merge_prompts(old, new, "merge")

        assert result == new
        assert "MERGED PROMPT" not in result

    def test_merge_prompts_invalid_strategy(self):
        """Test invalid strategy raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            merge_prompts("old", "new", "invalid_strategy")

        assert "Unknown merge strategy" in str(exc_info.value)
        assert "invalid_strategy" in str(exc_info.value)

    def test_merge_prompts_empty_strings(self):
        """Test merge with empty strings."""
        assert merge_prompts("", "new", "keep") == ""
        assert merge_prompts("old", "", "override") == ""
        assert merge_prompts("", "", "merge") == ""

    def test_merge_prompts_multiline_content(self):
        """Test merge with multiline content."""
        old = "Line 1\nLine 2\nLine 3"
        new = "New Line 1\nNew Line 2"

        result = merge_prompts(old, new, "merge")

        assert "Line 1" in result
        assert "Line 2" in result
        assert "New Line 1" in result


class TestFindProjectRules:
    """Tests for find_project_rules function."""

    def test_find_project_rules_agents_md(self, tmp_path):
        """Test finding AGENTS.md in repo root."""
        agents_content = "# Agent Rules\n\nFollow these."
        (tmp_path / "AGENTS.md").write_text(agents_content)

        result = find_project_rules(tmp_path)

        assert result == agents_content

    def test_find_project_rules_claude_md(self, tmp_path):
        """Test finding CLAUDE.md when AGENTS.md doesn't exist."""
        claude_content = "# Claude Instructions\n\nDo this."
        (tmp_path / "CLAUDE.md").write_text(claude_content)

        result = find_project_rules(tmp_path)

        assert result == claude_content

    def test_find_project_rules_agents_priority(self, tmp_path):
        """Test AGENTS.md takes priority over CLAUDE.md."""
        agents_content = "AGENTS content"
        claude_content = "CLAUDE content"
        (tmp_path / "AGENTS.md").write_text(agents_content)
        (tmp_path / "CLAUDE.md").write_text(claude_content)

        result = find_project_rules(tmp_path)

        assert result == agents_content

    def test_find_project_rules_none_found(self, tmp_path):
        """Test returns None when no rules file found."""
        result = find_project_rules(tmp_path)

        assert result is None

    def test_find_project_rules_empty_file(self, tmp_path):
        """Test returns empty string for empty rules file."""
        (tmp_path / "AGENTS.md").write_text("")

        result = find_project_rules(tmp_path)

        assert result == ""
