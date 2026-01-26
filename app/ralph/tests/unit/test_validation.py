"""Tests for ralph.validation module."""

import pytest

from ralph.validation import (
    validate_task,
    validate_task_notes,
    validate_acceptance_criteria,
    validate_issue,
    validate_subtask_for_decompose,
    ValidationResult,
    ValidationError,
    MIN_NOTES_LENGTH,
    MIN_ACCEPT_LENGTH,
)


class TestValidateTaskNotes:
    """Tests for validate_task_notes function."""

    def test_empty_notes_returns_error(self):
        errors = validate_task_notes(None)
        assert len(errors) == 1
        assert errors[0].code == "NOTES_REQUIRED"

    def test_short_notes_returns_error(self):
        errors = validate_task_notes("short")
        assert any(e.code == "NOTES_TOO_SHORT" for e in errors)

    def test_notes_without_file_ref_returns_error(self):
        notes = "This is a long enough description but has no file references in it at all"
        errors = validate_task_notes(notes)
        assert any(e.code == "NOTES_NO_FILE_REF" for e in errors)

    def test_notes_with_file_ref_passes(self):
        notes = "Source: src/foo.py lines 100-150. Extract the function and move it."
        errors = validate_task_notes(notes, is_modification=False)
        assert len(errors) == 0

    def test_modification_without_line_numbers_returns_error(self):
        notes = "Source: src/foo.py - Extract the function and move it to new module."
        errors = validate_task_notes(notes, is_modification=True)
        assert any(e.code == "NOTES_NO_LINE_NUMBERS" for e in errors)

    def test_modification_with_line_numbers_passes(self):
        notes = "Source: src/foo.py lines 100-150. Extract the function and move it."
        errors = validate_task_notes(notes, is_modification=True)
        assert len(errors) == 0


class TestValidateAcceptanceCriteria:
    """Tests for validate_acceptance_criteria function."""

    def test_empty_accept_returns_error(self):
        errors = validate_acceptance_criteria(None)
        assert len(errors) == 1
        assert errors[0].code == "ACCEPT_REQUIRED"

    def test_short_accept_returns_error(self):
        errors = validate_acceptance_criteria("pass")
        assert any(e.code == "ACCEPT_TOO_SHORT" for e in errors)

    def test_vague_accept_returns_error(self):
        errors = validate_acceptance_criteria("works correctly")
        assert any(e.code == "ACCEPT_VAGUE" for e in errors)

    def test_vague_accept_is_implemented_returns_error(self):
        errors = validate_acceptance_criteria("is implemented")
        assert any(e.code == "ACCEPT_VAGUE" for e in errors)

    def test_accept_without_command_returns_error(self):
        errors = validate_acceptance_criteria("the feature should work as expected by users")
        assert any(e.code == "ACCEPT_NOT_MEASURABLE" for e in errors)

    def test_accept_with_pytest_passes(self):
        errors = validate_acceptance_criteria("pytest tests/unit/test_foo.py passes")
        assert len(errors) == 0

    def test_accept_with_python_c_passes(self):
        errors = validate_acceptance_criteria("python -c 'from foo import bar' exits 0")
        assert len(errors) == 0

    def test_accept_with_grep_passes(self):
        errors = validate_acceptance_criteria("grep -c 'pattern' file.py returns 1")
        assert len(errors) == 0


class TestValidateTask:
    """Tests for validate_task function."""

    def test_valid_task_passes(self):
        result = validate_task(
            name="Add validation module",
            notes="Source: src/validation.py lines 1-50. Create validation functions.",
            accept="pytest tests/unit/test_validation.py passes",
            is_modification=True,
            strict=True,
        )
        assert result.valid
        assert len(result.errors) == 0

    def test_short_name_fails(self):
        result = validate_task(
            name="Fix",
            notes="Source: src/foo.py lines 100-150. Fix the bug.",
            accept="pytest passes",
            strict=True,
        )
        assert not result.valid
        assert any(e.code == "NAME_TOO_SHORT" for e in result.errors)

    def test_non_strict_only_requires_existence(self):
        result = validate_task(
            name="Add validation module",
            notes="short",  # Would fail strict validation
            accept="test",  # Would fail strict validation
            strict=False,
        )
        # Non-strict only checks existence, not content quality
        assert result.valid

    def test_strict_enforces_all_rules(self):
        result = validate_task(
            name="Add validation module",
            notes="short",
            accept="works",
            strict=True,
        )
        assert not result.valid
        # Should have multiple errors
        assert len(result.errors) > 1


class TestValidateIssue:
    """Tests for validate_issue function."""

    def test_valid_issue_passes(self):
        result = validate_issue("Test failure in test_foo.py: assertion error on line 42")
        assert result.valid

    def test_short_issue_fails(self):
        result = validate_issue("bug")
        assert not result.valid
        assert result.errors[0].code == "DESC_TOO_SHORT"


class TestValidateSubtaskForDecompose:
    """Tests for validate_subtask_for_decompose function."""

    def test_max_depth_exceeded_fails(self):
        result = validate_subtask_for_decompose(
            name="Subtask",
            notes="Source: file.py lines 1-10. Do something. Risk mitigation: keep it small.",
            accept="pytest tests/test.py passes",
            parent_depth=3,
            max_depth=3,
        )
        assert not result.valid
        assert any(e.code == "MAX_DEPTH_EXCEEDED" for e in result.errors)

    def test_missing_risk_mitigation_fails(self):
        result = validate_subtask_for_decompose(
            name="Subtask name here",
            notes="Source: file.py lines 1-10. Do something without any safety measures.",
            accept="pytest tests/test_file.py passes",
            parent_depth=1,
            max_depth=3,
        )
        assert not result.valid
        assert any(e.code == "NOTES_NO_RISK_MITIGATION" for e in result.errors)

    def test_valid_subtask_passes(self):
        result = validate_subtask_for_decompose(
            name="Extract dataclass to new file",
            notes="Source: file.py lines 1-10. Extract class. Risk mitigation: keep it small.",
            accept="pytest tests/test_extract.py passes",
            parent_depth=1,
            max_depth=3,
        )
        # Should pass - has risk mitigation and valid notes with accept criteria
        assert result.valid


class TestValidationResult:
    """Tests for ValidationResult class."""

    def test_to_dict_with_errors(self):
        result = ValidationResult(
            valid=False,
            errors=[
                ValidationError(field="notes", code="NOTES_REQUIRED", message="Notes required"),
                ValidationError(field="accept", code="ACCEPT_REQUIRED", message="Accept required"),
            ],
        )
        d = result.to_dict()
        assert d["valid"] is False
        assert len(d["errors"]) == 2
        assert d["errors"][0]["field"] == "notes"
        assert d["errors"][0]["code"] == "NOTES_REQUIRED"

    def test_to_dict_when_valid(self):
        result = ValidationResult(valid=True, errors=[])
        d = result.to_dict()
        assert d["valid"] is True
        assert len(d["errors"]) == 0
