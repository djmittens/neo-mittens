"""Tests for ralph.subagent module."""

import pytest
import json

from ralph.subagent import (
    build_investigate_prompt,
    build_verify_task_prompt,
    build_verify_criterion_prompt,
    build_research_prompt,
    build_decompose_prompt,
    get_schema,
    validate_response,
    INVESTIGATE_SCHEMA,
    VERIFY_TASK_SCHEMA,
    DECOMPOSE_SCHEMA,
)


class TestBuildInvestigatePrompt:
    """Tests for build_investigate_prompt function."""

    def test_creates_prompt_with_context(self):
        prompt = build_investigate_prompt(
            issue_id="i-123",
            issue_desc="Test failure in module X",
            priority="high",
        )
        assert prompt.task_type == "investigate"
        assert "i-123" in prompt.context["issue_id"]
        assert "Test failure" in prompt.context["issue_desc"]

    def test_renders_complete_prompt(self):
        prompt = build_investigate_prompt(
            issue_id="i-123",
            issue_desc="Test failure",
            priority="high",
        )
        rendered = prompt.render()
        assert "Subagent Task: investigate" in rendered
        assert "i-123" in rendered
        assert "Return ONLY the JSON object" in rendered


class TestBuildVerifyTaskPrompt:
    """Tests for build_verify_task_prompt function."""

    def test_creates_prompt_with_context(self):
        prompt = build_verify_task_prompt(
            task_id="t-456",
            task_name="Add validation",
            accept_criteria="pytest passes",
        )
        assert prompt.task_type == "verify_task"
        assert prompt.context["task_id"] == "t-456"
        assert prompt.context["task_name"] == "Add validation"

    def test_renders_with_schema(self):
        prompt = build_verify_task_prompt(
            task_id="t-456",
            task_name="Add validation",
            accept_criteria="pytest passes",
        )
        rendered = prompt.render()
        assert "passed" in rendered
        assert "evidence" in rendered


class TestBuildDecomposePrompt:
    """Tests for build_decompose_prompt function."""

    def test_creates_prompt_with_context(self):
        prompt = build_decompose_prompt(
            task_name="Large refactor",
            task_notes="Move all functions",
            kill_reason="context_limit",
        )
        assert prompt.task_type == "decompose"
        assert prompt.context["kill_reason"] == "context_limit"

    def test_renders_with_schema(self):
        prompt = build_decompose_prompt(
            task_name="Large refactor",
            task_notes="Move all functions",
            kill_reason="timeout",
        )
        rendered = prompt.render()
        assert "remaining_work" in rendered
        assert "context_risks" in rendered


class TestGetSchema:
    """Tests for get_schema function."""

    def test_returns_investigate_schema(self):
        schema = get_schema("investigate")
        assert schema is not None
        assert "issue_id" in schema["properties"]

    def test_returns_verify_task_schema(self):
        schema = get_schema("verify_task")
        assert schema is not None
        assert "task_id" in schema["properties"]

    def test_returns_none_for_unknown(self):
        schema = get_schema("unknown_type")
        assert schema is None


class TestValidateResponse:
    """Tests for validate_response function."""

    def test_valid_investigate_response(self):
        response = {
            "issue_id": "i-123",
            "root_cause": "src/foo.py:42",
            "resolution": "task",
            "task": {
                "name": "Fix the bug",
                "notes": "Root cause found",
                "accept": "pytest passes",
            },
        }
        is_valid, errors = validate_response("investigate", response)
        assert is_valid
        assert len(errors) == 0

    def test_missing_required_field(self):
        response = {
            "issue_id": "i-123",
            # missing root_cause and resolution
        }
        is_valid, errors = validate_response("investigate", response)
        assert not is_valid
        assert "root_cause" in str(errors) or "resolution" in str(errors)

    def test_invalid_enum_value(self):
        response = {
            "issue_id": "i-123",
            "root_cause": "src/foo.py:42",
            "resolution": "invalid_value",  # Not in enum
        }
        is_valid, errors = validate_response("investigate", response)
        assert not is_valid
        assert any("resolution" in e for e in errors)

    def test_wrong_type(self):
        response = {
            "issue_id": 123,  # Should be string
            "root_cause": "src/foo.py:42",
            "resolution": "task",
        }
        is_valid, errors = validate_response("investigate", response)
        assert not is_valid
        assert any("issue_id" in e for e in errors)

    def test_unknown_type_returns_error(self):
        is_valid, errors = validate_response("unknown", {})
        assert not is_valid
        assert "Unknown task type" in errors[0]


class TestSchemaStructure:
    """Tests for schema structure integrity."""

    def test_investigate_schema_has_required_fields(self):
        assert "required" in INVESTIGATE_SCHEMA
        assert "issue_id" in INVESTIGATE_SCHEMA["required"]
        assert "root_cause" in INVESTIGATE_SCHEMA["required"]
        assert "resolution" in INVESTIGATE_SCHEMA["required"]

    def test_verify_task_schema_has_required_fields(self):
        assert "required" in VERIFY_TASK_SCHEMA
        assert "task_id" in VERIFY_TASK_SCHEMA["required"]
        assert "passed" in VERIFY_TASK_SCHEMA["required"]

    def test_decompose_schema_has_required_fields(self):
        assert "required" in DECOMPOSE_SCHEMA
        assert "remaining_work" in DECOMPOSE_SCHEMA["required"]
