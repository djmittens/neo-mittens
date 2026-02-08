"""Unit tests for ralph.prompts module."""

import pytest
import json
from pathlib import Path

from ralph.prompts import (
    load_prompt,
    build_prompt_with_rules,
    find_project_rules,
    inject_context,
    build_plan_context,
    build_build_context,
    build_verify_context,
    build_investigate_context,
    build_decompose_context,
    load_and_inject,
)


class TestLoadPrompt:
    """Tests for load_prompt function."""

    def test_load_prompt_returns_string(self):
        """Test loading a prompt returns a string."""
        result = load_prompt("build")
        assert isinstance(result, str)

    def test_load_prompt_all_stages(self):
        """Test loading prompts for all valid stages."""
        stages = ["plan", "build", "verify", "investigate", "decompose"]
        for stage in stages:
            result = load_prompt(stage)
            assert isinstance(result, str)
            assert len(result) > 100, f"{stage} prompt appears too short"

    def test_load_prompt_unknown_stage(self):
        """Test KeyError for unknown stage name."""
        with pytest.raises(KeyError) as exc_info:
            load_prompt("nonexistent")
        assert "nonexistent" in str(exc_info.value)

    def test_load_prompt_contains_ralph_output(self):
        """Test all prompts contain the RALPH_OUTPUT marker."""
        stages = ["plan", "build", "verify", "investigate", "decompose"]
        for stage in stages:
            result = load_prompt(stage)
            assert "RALPH_OUTPUT" in result, f"{stage} prompt missing RALPH_OUTPUT"

    def test_load_prompt_build_has_spec_content(self):
        """Test build prompt includes spec content placeholder."""
        result = load_prompt("build")
        assert "{{SPEC_CONTENT}}" in result

    def test_load_prompt_verify_has_issues_field(self):
        """Test verify prompt documents the issues output field."""
        result = load_prompt("verify")
        assert "issues" in result.lower()
        assert "Rejection Quality" in result

    def test_load_prompt_decompose_has_depth(self):
        """Test decompose prompt includes depth tracking."""
        result = load_prompt("decompose")
        assert "{{DECOMPOSE_DEPTH}}" in result
        assert "{{MAX_DEPTH}}" in result


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


class TestInjectContext:
    """Tests for inject_context function."""

    def test_replaces_simple_placeholders(self):
        template = "Hello {{NAME}}, your task is {{TASK}}."
        context = {"name": "Alice", "task": "build"}
        
        result = inject_context(template, context)
        
        assert result == "Hello Alice, your task is build."

    def test_handles_dict_values(self):
        template = "Task: {{TASK_JSON}}"
        context = {"task_json": {"name": "Fix bug", "id": "t-123"}}
        
        result = inject_context(template, context)
        
        assert '"name": "Fix bug"' in result
        assert '"id": "t-123"' in result

    def test_handles_list_values(self):
        template = "Items: {{ITEMS}}"
        context = {"items": ["a", "b", "c"]}
        
        result = inject_context(template, context)
        
        # json.dumps with indent=2 produces formatted output
        assert '"a"' in result
        assert '"b"' in result
        assert '"c"' in result

    def test_handles_none_values(self):
        template = "Value: {{VALUE}}"
        context = {"value": None}
        
        result = inject_context(template, context)
        
        assert result == "Value: "

    def test_preserves_unmatched_placeholders(self):
        template = "Hello {{NAME}}, {{UNKNOWN}} is not replaced."
        context = {"name": "Alice"}
        
        result = inject_context(template, context)
        
        assert "Alice" in result
        assert "{{UNKNOWN}}" in result


class TestBuildBuildContext:
    """Tests for build_build_context (tix dict-based)."""

    def test_creates_context_from_task_dict(self):
        task = {
            "id": "t-123",
            "name": "Fix bug",
            "spec": "feature.md",
            "notes": "Fix the bug in module X",
            "accept": "pytest passes",
            "reject": "",
        }
        context = build_build_context(task, "feature.md")

        assert context["task_id"] == "t-123"
        assert context["task_name"] == "Fix bug"
        assert context["is_retry"] == "false"

    def test_marks_retry_when_rejected(self):
        task = {
            "id": "t-123",
            "name": "Fix bug",
            "reject": "Did not fix the root cause",
        }
        context = build_build_context(task)

        assert context["is_retry"] == "true"
        assert context["task_reject"] == "Did not fix the root cause"

    def test_includes_spec_content(self):
        task = {"id": "t-1", "name": "Task"}
        context = build_build_context(task, "s.md", "# My Spec\nDo things.")

        assert context["spec_content"] == "# My Spec\nDo things."

    def test_spec_content_defaults_empty(self):
        task = {"id": "t-1", "name": "Task"}
        context = build_build_context(task)

        assert context["spec_content"] == ""


class TestBuildVerifyContext:
    """Tests for build_verify_context (tix dict-based)."""

    def test_creates_context_from_done_tasks(self):
        tasks = [
            {"id": "t-1", "name": "Task 1"},
            {"id": "t-2", "name": "Task 2"},
        ]
        context = build_verify_context(tasks, "spec.md")

        assert context["done_count"] == 2
        assert context["spec_file"] == "spec.md"
        assert '"t-1"' in context["done_tasks_json"]

    def test_includes_spec_content(self):
        context = build_verify_context([], "s.md", "spec text")

        assert context["spec_content"] == "spec text"


class TestBuildInvestigateContext:
    """Tests for build_investigate_context (tix dict-based)."""

    def test_creates_context_from_issues(self):
        issues = [
            {"id": "i-1", "desc": "Test failure"},
            {"id": "i-2", "desc": "Warning in build"},
        ]
        context = build_investigate_context(issues, "spec.md")

        assert context["issue_count"] == 2
        assert '"i-1"' in context["issues_json"]

    def test_includes_spec_content(self):
        context = build_investigate_context([], "s.md", "spec text")

        assert context["spec_content"] == "spec text"


class TestBuildDecomposeContext:
    """Tests for build_decompose_context (tix dict-based)."""

    def test_creates_context_from_killed_task(self):
        task = {
            "id": "t-123",
            "name": "Large refactor",
            "kill_reason": "context_limit",
            "kill_log": "/tmp/logs/t-123.log",
        }
        context = build_decompose_context(task)

        assert context["task_id"] == "t-123"
        assert context["kill_reason"] == "context_limit"
        assert context["kill_log_path"] == "/tmp/logs/t-123.log"

    def test_includes_spec_content(self):
        task = {"id": "t-1", "name": "Task", "kill_reason": "timeout"}
        context = build_decompose_context(task, "s.md", "spec text")

        assert context["spec_content"] == "spec text"

    def test_includes_depth_and_max_depth(self):
        task = {"id": "t-1", "name": "Task", "decompose_depth": 2}
        context = build_decompose_context(task, max_depth=5)

        assert context["decompose_depth"] == 2
        assert context["max_depth"] == 5

    def test_depth_defaults_to_zero(self):
        task = {"id": "t-1", "name": "Task"}
        context = build_decompose_context(task)

        assert context["decompose_depth"] == 0
        assert context["max_depth"] == 3  # default


class TestBuildPlanContext:
    """Tests for build_plan_context function."""

    def test_creates_context_from_spec(self):
        context = build_plan_context("feature.md", "# Feature Spec\n\nDo things.")
        
        assert context["spec_file"] == "feature.md"
        assert "Feature Spec" in context["spec_content"]


class TestLoadAndInject:
    """Tests for load_and_inject function."""

    def test_loads_and_injects_build_context(self):
        """Test load_and_inject with build stage and real context."""
        context = {
            "task_json": '{"id": "t-1"}',
            "task_name": "Build feature",
            "task_notes": "Fix the thing",
            "task_accept": "tests pass",
            "task_reject": "",
            "spec_content": "# My Spec",
        }
        result = load_and_inject("build", context)

        assert "Build feature" in result
        assert "# My Spec" in result
        assert "RALPH_OUTPUT" in result
