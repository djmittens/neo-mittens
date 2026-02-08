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
    _is_vague_acceptance,
    _is_untargeted_command,
    _has_measurable_command,
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


class TestIsVagueAcceptance:
    """Tests for _is_vague_acceptance function."""

    def test_works_correctly(self):
        assert _is_vague_acceptance("works correctly") is True

    def test_is_implemented(self):
        assert _is_vague_acceptance("is implemented") is True

    def test_should_work(self):
        assert _is_vague_acceptance("should work") is True

    def test_functions_properly(self):
        assert _is_vague_acceptance("functions properly") is True

    def test_tests_pass_bare(self):
        assert _is_vague_acceptance("tests pass") is True

    def test_all_tests_pass(self):
        assert _is_vague_acceptance("all tests pass") is True

    def test_builds_successfully(self):
        assert _is_vague_acceptance("builds successfully") is True

    def test_compiles_without_errors(self):
        assert _is_vague_acceptance("compiles without errors") is True

    def test_no_errors(self):
        assert _is_vague_acceptance("no errors") is True

    def test_everything_works(self):
        assert _is_vague_acceptance("everything works") is True

    def test_specific_command_not_vague(self):
        assert _is_vague_acceptance("pytest tests/unit/test_foo.py passes") is False

    def test_grep_command_not_vague(self):
        assert _is_vague_acceptance("grep -c 'class Foo' src/foo.py returns 1") is False


class TestIsUntargetedCommand:
    """Tests for _is_untargeted_command function."""

    # These should all be rejected as untargeted
    def test_bare_make(self):
        assert _is_untargeted_command("make") is True

    def test_make_test(self):
        assert _is_untargeted_command("make test") is True

    def test_make_all(self):
        assert _is_untargeted_command("make all") is True

    def test_make_check(self):
        assert _is_untargeted_command("make check") is True

    def test_make_build(self):
        assert _is_untargeted_command("make build") is True

    def test_make_lint(self):
        assert _is_untargeted_command("make lint") is True

    def test_bare_pytest(self):
        assert _is_untargeted_command("pytest") is True

    def test_pytest_with_only_flags(self):
        assert _is_untargeted_command("pytest -v") is True

    def test_pytest_verbose_flag(self):
        assert _is_untargeted_command("pytest --verbose") is True

    def test_bare_npm_test(self):
        assert _is_untargeted_command("npm test") is True

    def test_bare_yarn_test(self):
        assert _is_untargeted_command("yarn test") is True

    def test_npm_run_test(self):
        assert _is_untargeted_command("npm run test") is True

    def test_bare_cargo_test(self):
        assert _is_untargeted_command("cargo test") is True

    def test_go_test_all(self):
        assert _is_untargeted_command("go test ./...") is True

    # These should be accepted as targeted
    def test_pytest_with_path(self):
        assert _is_untargeted_command("pytest tests/unit/test_foo.py") is False

    def test_pytest_with_path_and_flags(self):
        assert _is_untargeted_command("pytest tests/unit/test_foo.py -v") is False

    def test_make_with_specific_target(self):
        assert _is_untargeted_command("make test-unit TEST=test_config") is False

    def test_npm_run_specific_script(self):
        assert _is_untargeted_command("npm run test:unit -- --path foo") is False

    def test_cargo_test_specific(self):
        assert _is_untargeted_command("cargo test test_config") is False


class TestHasMeasurableCommand:
    """Tests for _has_measurable_command function."""

    # These should pass - specific and targeted
    def test_pytest_with_path(self):
        assert _has_measurable_command("pytest tests/unit/test_foo.py passes") is True

    def test_python_c_import(self):
        assert _has_measurable_command("python -c 'from foo import bar' exits 0") is True

    def test_python3_c_import(self):
        assert _has_measurable_command('python3 -c "from ralph.config import GlobalConfig"') is True

    def test_python_m_module(self):
        assert _has_measurable_command("python -m pytest tests/test_foo.py") is True

    def test_grep_with_file(self):
        assert _has_measurable_command("grep -c 'pattern' file.py returns 1") is True

    def test_test_f_file(self):
        assert _has_measurable_command("test -f app/ralph/foo.py") is True

    def test_test_d_dir(self):
        assert _has_measurable_command("test -d app/ralph/stages") is True

    def test_compound_with_file_ref(self):
        assert _has_measurable_command(
            "test -f app/ralph/foo.py && python3 -c 'from ralph.foo import Bar'"
        ) is True

    def test_script_execution(self):
        assert _has_measurable_command("./run_test.sh") is True

    def test_bash_script(self):
        assert _has_measurable_command("bash scripts/verify.sh") is True

    def test_pipe_with_file_ref(self):
        assert _has_measurable_command("cat src/foo.py | grep -c 'class Foo'") is True

    def test_exits_0_with_file_ref(self):
        assert _has_measurable_command(
            "python3 -c 'import ralph.config' exits 0"
        ) is True

    # These should fail - not specific enough
    def test_bare_pytest_not_measurable(self):
        assert _has_measurable_command("pytest") is False

    def test_bare_make_not_measurable(self):
        assert _has_measurable_command("make test") is False

    def test_prose_not_measurable(self):
        assert _has_measurable_command("the function works correctly") is False

    def test_vague_tests_pass_not_measurable(self):
        assert _has_measurable_command("all tests pass") is False

    def test_npm_test_not_measurable(self):
        assert _has_measurable_command("npm test") is False


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

    def test_untargeted_pytest_returns_error(self):
        errors = validate_acceptance_criteria("pytest -v")
        assert any(e.code == "ACCEPT_UNTARGETED" for e in errors)

    def test_untargeted_make_test_returns_error(self):
        errors = validate_acceptance_criteria("make test")
        assert any(e.code == "ACCEPT_UNTARGETED" for e in errors)

    def test_untargeted_npm_test_returns_error(self):
        errors = validate_acceptance_criteria("npm test")
        assert any(e.code == "ACCEPT_UNTARGETED" for e in errors)

    def test_accept_without_command_returns_error(self):
        errors = validate_acceptance_criteria("the feature should work as expected by users")
        assert any(e.code == "ACCEPT_NOT_MEASURABLE" for e in errors)

    def test_accept_with_targeted_pytest_passes(self):
        errors = validate_acceptance_criteria("pytest tests/unit/test_foo.py passes")
        assert len(errors) == 0

    def test_accept_with_python_c_passes(self):
        errors = validate_acceptance_criteria("python -c 'from foo import bar' exits 0")
        assert len(errors) == 0

    def test_accept_with_grep_passes(self):
        errors = validate_acceptance_criteria("grep -c 'pattern' file.py returns 1")
        assert len(errors) == 0

    def test_accept_with_test_f_passes(self):
        errors = validate_acceptance_criteria("test -f app/ralph/config.py")
        assert len(errors) == 0

    def test_accept_with_compound_command_passes(self):
        errors = validate_acceptance_criteria(
            "test -f app/ralph/foo.py && python3 -c 'from ralph.foo import Bar' exits 0"
        )
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
            accept="pytest tests/unit/test_foo.py passes",
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

    def test_strict_rejects_untargeted_pytest(self):
        """Bare 'pytest' should fail strict validation."""
        result = validate_task(
            name="Add validation module",
            notes="Source: src/validation.py lines 1-50. Create validation functions.",
            accept="pytest",
            strict=True,
        )
        assert not result.valid
        assert any(e.code == "ACCEPT_UNTARGETED" for e in result.errors)

    def test_strict_rejects_make_test(self):
        """'make test' should fail strict validation."""
        result = validate_task(
            name="Add config module",
            notes="Source: src/config.py lines 1-50. Create config loading functions.",
            accept="make test",
            strict=True,
        )
        assert not result.valid
        assert any(e.code == "ACCEPT_UNTARGETED" for e in result.errors)


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
