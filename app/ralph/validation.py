"""Task and issue validation for Ralph.

Centralizes all validation rules that were previously scattered in prompts.
Validation is enforced programmatically rather than relying on LLM compliance.
"""

import re
from dataclasses import dataclass
from typing import Optional

# Validation thresholds
MIN_NOTES_LENGTH = 50
MIN_ACCEPT_LENGTH = 10


@dataclass
class ValidationError:
    """A single validation error."""

    field: str
    code: str
    message: str


@dataclass
class ValidationResult:
    """Result of validating a task or issue."""

    valid: bool
    errors: list[ValidationError]

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "valid": self.valid,
            "errors": [
                {"field": e.field, "code": e.code, "message": e.message}
                for e in self.errors
            ],
        }


def _has_file_reference(text: str) -> bool:
    """Check if text contains a file path reference.

    Matches patterns like:
    - src/foo.py
    - ralph/stages/build.py
    - file.ts:123
    - lines 100-150
    """
    patterns = [
        r"[a-zA-Z_][a-zA-Z0-9_/.-]+\.(py|ts|tsx|js|jsx|go|rs|c|cpp|h|hpp|md|json|yaml|yml)",
        r"lines?\s+\d+",
        r":\d+",  # file:line reference
    ]
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _has_line_numbers(text: str) -> bool:
    """Check if text contains line number references.

    Matches patterns like:
    - lines 100-150
    - line 42
    - :123
    - L100
    """
    patterns = [
        r"lines?\s+\d+(-\d+)?",
        r":\d+",
        r"L\d+",
    ]
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _is_vague_acceptance(text: str) -> bool:
    """Check if acceptance criteria is too vague.

    Returns True if the criteria uses weak/vague language without
    specific commands or measurable conditions.
    """
    vague_patterns = [
        r"^works?\s+(correctly|properly|as expected)",
        r"^is\s+(implemented|complete|done)",
        r"^should\s+work",
        r"^functions?\s+(correctly|properly)",
        r"^tests?\s+pass$",  # Just "tests pass" without specifying which
    ]
    text_lower = text.lower().strip()
    for pattern in vague_patterns:
        if re.match(pattern, text_lower):
            return True
    return False


def _has_measurable_command(text: str) -> bool:
    """Check if acceptance criteria contains a measurable command.

    Good criteria include specific commands like:
    - pytest path/to/test.py
    - python -c "from foo import bar"
    - grep -c 'pattern' file
    - test -f path/to/file
    """
    command_patterns = [
        r"pytest\s+",
        r"python3?\s+-[cm]",
        r"npm\s+(test|run)",
        r"grep\s+-",
        r"test\s+-[fde]",
        r"exits?\s+0",
        r"returns?\s+\d+",
        r"outputs?\s+",
        r"contains?\s+",
    ]
    for pattern in command_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def validate_task_notes(notes: Optional[str], is_modification: bool = True) -> list[ValidationError]:
    """Validate task notes field.

    Rules:
    1. Notes must be at least MIN_NOTES_LENGTH characters
    2. Notes must contain file path references
    3. For modification tasks, notes should include line numbers

    Args:
        notes: The notes field content
        is_modification: Whether this is a modification task (vs new file creation)

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    if not notes:
        errors.append(ValidationError(
            field="notes",
            code="NOTES_REQUIRED",
            message="Task notes are required. Include: source file paths, what to do, how to do it."
        ))
        return errors

    if len(notes) < MIN_NOTES_LENGTH:
        errors.append(ValidationError(
            field="notes",
            code="NOTES_TOO_SHORT",
            message=f"Task notes must be at least {MIN_NOTES_LENGTH} characters. "
                    f"Current: {len(notes)}. Include file paths and implementation details."
        ))

    if not _has_file_reference(notes):
        errors.append(ValidationError(
            field="notes",
            code="NOTES_NO_FILE_REF",
            message="Task notes must include file path references (e.g., 'src/foo.py')."
        ))

    if is_modification and not _has_line_numbers(notes):
        errors.append(ValidationError(
            field="notes",
            code="NOTES_NO_LINE_NUMBERS",
            message="Modification tasks should include line number references "
                    "(e.g., 'lines 100-150' or 'file.py:42')."
        ))

    return errors


def validate_acceptance_criteria(accept: Optional[str]) -> list[ValidationError]:
    """Validate task acceptance criteria.

    Rules:
    1. Accept criteria must be provided
    2. Accept criteria must not be vague
    3. Accept criteria should include measurable commands

    Args:
        accept: The acceptance criteria content

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    if not accept:
        errors.append(ValidationError(
            field="accept",
            code="ACCEPT_REQUIRED",
            message="Acceptance criteria required. Use specific commands: "
                    "'pytest path/test.py passes' or 'python -c \"from x import y\" exits 0'"
        ))
        return errors

    if len(accept) < MIN_ACCEPT_LENGTH:
        errors.append(ValidationError(
            field="accept",
            code="ACCEPT_TOO_SHORT",
            message=f"Acceptance criteria must be at least {MIN_ACCEPT_LENGTH} characters."
        ))

    if _is_vague_acceptance(accept):
        errors.append(ValidationError(
            field="accept",
            code="ACCEPT_VAGUE",
            message="Acceptance criteria is too vague. Avoid 'works correctly', 'is implemented'. "
                    "Use specific commands with expected outputs."
        ))

    if not _has_measurable_command(accept):
        errors.append(ValidationError(
            field="accept",
            code="ACCEPT_NOT_MEASURABLE",
            message="Acceptance criteria should include a measurable command "
                    "(e.g., 'pytest X passes', 'grep -c pattern file returns 1')."
        ))

    return errors


def validate_task(
    name: str,
    notes: Optional[str],
    accept: Optional[str],
    is_modification: bool = True,
    strict: bool = True,
) -> ValidationResult:
    """Validate a complete task.

    Args:
        name: Task name
        notes: Task notes
        accept: Acceptance criteria
        is_modification: Whether this modifies existing code
        strict: If True, all rules enforced. If False, only critical rules.

    Returns:
        ValidationResult with valid flag and any errors
    """
    errors = []

    if not name or len(name.strip()) < 5:
        errors.append(ValidationError(
            field="name",
            code="NAME_TOO_SHORT",
            message="Task name must be at least 5 characters."
        ))

    if strict:
        errors.extend(validate_task_notes(notes, is_modification))
        errors.extend(validate_acceptance_criteria(accept))
    else:
        # Non-strict: only require notes and accept to exist
        if not notes:
            errors.append(ValidationError(
                field="notes",
                code="NOTES_REQUIRED",
                message="Task notes are required."
            ))
        if not accept:
            errors.append(ValidationError(
                field="accept",
                code="ACCEPT_REQUIRED",
                message="Acceptance criteria required."
            ))

    return ValidationResult(valid=len(errors) == 0, errors=errors)


def validate_issue(desc: str) -> ValidationResult:
    """Validate an issue description.

    Args:
        desc: Issue description

    Returns:
        ValidationResult with valid flag and any errors
    """
    errors = []

    if not desc or len(desc.strip()) < 10:
        errors.append(ValidationError(
            field="desc",
            code="DESC_TOO_SHORT",
            message="Issue description must be at least 10 characters."
        ))

    return ValidationResult(valid=len(errors) == 0, errors=errors)


def validate_subtask_for_decompose(
    name: str,
    notes: Optional[str],
    accept: Optional[str] = None,
    parent_depth: int = 0,
    max_depth: int = 3,
) -> ValidationResult:
    """Validate a subtask created during DECOMPOSE stage.

    Additional rules for decomposed tasks:
    1. Must not exceed max decomposition depth
    2. Notes must include risk mitigation
    3. Notes must include context from parent

    Args:
        name: Subtask name
        notes: Subtask notes
        accept: Optional acceptance criteria
        parent_depth: Decomposition depth of the parent task
        max_depth: Maximum allowed decomposition depth

    Returns:
        ValidationResult with valid flag and any errors
    """
    errors = []

    if parent_depth >= max_depth:
        errors.append(ValidationError(
            field="decompose_depth",
            code="MAX_DEPTH_EXCEEDED",
            message=f"Maximum decomposition depth ({max_depth}) exceeded. "
                    "Task cannot be further decomposed."
        ))

    # Base task validation (non-strict for decompose)
    base_result = validate_task(name, notes, accept, is_modification=True, strict=False)
    errors.extend(base_result.errors)

    # Additional decompose-specific checks
    if notes:
        notes_lower = notes.lower()
        if "risk" not in notes_lower and "mitigation" not in notes_lower:
            errors.append(ValidationError(
                field="notes",
                code="NOTES_NO_RISK_MITIGATION",
                message="Subtask notes should include risk mitigation "
                        "(how to avoid re-killing due to context/timeout)."
            ))

    return ValidationResult(valid=len(errors) == 0, errors=errors)
