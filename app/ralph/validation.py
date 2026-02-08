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

    Also catches untargeted commands that run the entire test suite
    or build without specifying what to check — these are meaningless
    for verifying a single task completed correctly.
    """
    text_lower = text.lower().strip()

    # Prose vagueness: no command at all
    prose_patterns = [
        r"^works?\s+(correctly|properly|as expected)",
        r"^is\s+(implemented|complete|done)",
        r"^should\s+work",
        r"^functions?\s+(correctly|properly)",
        r"^tests?\s+pass$",  # Just "tests pass" without specifying which
        r"^all\s+tests?\s+pass",
        r"^builds?\s+(successfully|correctly|without errors?)",
        r"^compiles?\s+(successfully|correctly|without errors?)",
        r"^no\s+(errors?|warnings?|failures?)",
        r"^everything\s+(works|passes|compiles|builds)",
        r"^feature\s+(is|works|functions)",
        r"^code\s+(is|works|compiles)",
        r"^implementation\s+(is|works)",
    ]
    for pattern in prose_patterns:
        if re.match(pattern, text_lower):
            return True

    return False


def _is_untargeted_command(text: str) -> bool:
    """Check if acceptance criteria is a command that lacks a specific target.

    Catches commands like:
    - "make test" / "make" / "make all"
    - "pytest" (no path)
    - "npm test" / "npm run test" (no specific script target)
    - "cargo test" (no specific test)
    - "go test ./..." (runs everything)

    These are bad because:
    1. They run the entire suite, not the task's specific change
    2. Pre-existing failures mask whether THIS task's work is correct
    3. They're slow and waste context on irrelevant output
    4. A failure gives no signal about what the task actually broke

    Good alternatives:
    - "pytest tests/unit/test_config.py -v"
    - "python3 -c 'from ralph.config import GlobalConfig'"
    - "test -f app/ralph/foo.py && grep -c 'class Foo' app/ralph/foo.py"
    - "make test-unit TEST=test_config"
    """
    text_lower = text.lower().strip()
    first_line = text_lower.split("\n")[0].strip()

    # Bare make / make with generic targets
    untargeted_make = [
        r"^make\s*$",
        r"^make\s+(test|tests|check|all|build|clean|lint|format)\s*$",
        r"^make\s+-j\s*\d*\s*$",
    ]
    for pattern in untargeted_make:
        if re.match(pattern, first_line):
            return True

    # Bare pytest / pytest with only flags (no path)
    # "pytest" / "pytest -v" / "pytest --verbose" but NOT "pytest tests/foo.py"
    if re.match(r"^pytest(\s+-[a-zA-Z-]+)*\s*$", first_line):
        return True

    # Bare npm/yarn test
    if re.match(r"^(npm|yarn)\s+(test|run\s+test)\s*$", first_line):
        return True

    # Bare cargo test (no specific test name/path)
    if re.match(r"^cargo\s+test\s*$", first_line):
        return True

    # go test ./... (runs everything)
    if re.match(r"^go\s+test\s+\./\.\.\.\s*$", first_line):
        return True

    return False


def _has_measurable_command(text: str) -> bool:
    """Check if acceptance criteria contains a specific, targeted command.

    Good criteria include commands with SPECIFIC targets:
    - pytest tests/unit/test_config.py  (specific test file)
    - python -c "from foo import bar"   (specific import check)
    - grep -c 'pattern' file.py         (specific file + pattern)
    - test -f path/to/file              (specific file existence)

    Bare commands without targets (pytest, make test) do NOT qualify.
    """
    # Commands that need a path/target argument to be meaningful
    targeted_patterns = [
        r"pytest\s+\S*[/.]",              # pytest with a path (has / or .)
        r"python3?\s+-c\s+['\"]",         # python -c "..." (inline code)
        r"python3?\s+-m\s+\S+",           # python -m module
        r"grep\s+-\S*\s+['\"]?\S+['\"]?\s+\S+",  # grep with pattern AND file
        r"test\s+-[fde]\s+\S+",           # test -f path
        r"\./\S+",                         # ./script (specific script)
        r"bash\s+\S+",                     # bash script.sh
        r"sh\s+\S+",                       # sh script.sh
    ]
    for pattern in targeted_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    # Shell pipelines and compound commands with specific content
    # e.g., "test -f foo.py && python -c 'import foo'"
    if "&&" in text or "|" in text:
        # At least one side must have a file reference
        if _has_file_reference(text):
            return True

    # "exits 0" or "returns N" combined with a file reference
    if re.search(r"(exits?\s+0|returns?\s+\d+)", text, re.IGNORECASE):
        if _has_file_reference(text):
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
    2. Accept criteria must not be vague prose
    3. Accept criteria must not be an untargeted command (make test, pytest, etc.)
    4. Accept criteria must include a specific, targeted measurable command

    The goal is to ensure every task has acceptance criteria that can be
    auto-executed by the pre-check harness, avoiding expensive VERIFY calls.

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

    if _is_untargeted_command(accept):
        errors.append(ValidationError(
            field="accept",
            code="ACCEPT_UNTARGETED",
            message="Acceptance criteria must target specific files or tests, not the entire suite. "
                    "Bad: 'make test', 'pytest', 'npm test'. "
                    "Good: 'pytest tests/unit/test_foo.py', 'test -f src/foo.py && python -c \"from foo import Bar\"'"
        ))

    if not _has_measurable_command(accept):
        errors.append(ValidationError(
            field="accept",
            code="ACCEPT_NOT_MEASURABLE",
            message="Acceptance criteria must be a specific shell command with a target. "
                    "Include file paths: 'pytest tests/unit/test_config.py passes', "
                    "'grep -c \"class Foo\" src/foo.py returns 1', "
                    "'test -f src/foo.py && python3 -c \"from foo import Foo\" exits 0'"
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
