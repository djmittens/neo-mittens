# PLAN Stage: Gap Analysis

Generate implementation tasks for the spec.

## Spec File

`ralph/specs/{{SPEC_FILE}}`

## Spec Content

<spec>
{{SPEC_CONTENT}}
</spec>

## Instructions

### 1. Research with Subagents

Your context is LIMITED. Launch parallel subagents:

```
Task: "Research [requirement] for spec {{SPEC_FILE}}

Return JSON:
{
  \"requirement\": \"spec requirement\",
  \"current_state\": \"implemented|partial|missing\",
  \"files_to_modify\": [{\"path\": \"...\", \"lines\": \"100-150\", \"what\": \"...\", \"how\": \"...\"}],
  \"files_to_create\": [{\"path\": \"...\", \"template\": \"similar file\", \"purpose\": \"...\"}],
  \"imports_needed\": [\"from X import Y\"],
  \"patterns_to_follow\": \"reference to similar code\",
  \"verification\": \"command + expected output\"
}"
```

### 2. Create Tasks

For each gap, create a task preserving research:

```
ralph2 task add '{"name": "...", "notes": "Source: file lines N-M. Action. Pattern: similar code. Imports: list.", "accept": "pytest X passes", "deps": ["t-xxx"]}'
```

### Task Requirements

**`notes`** MUST include:
- Source locations (file paths + line numbers)
- What to do (specific action)
- How to do it (pattern/approach)
- Imports/dependencies needed

**`accept`** MUST be:
- Specific (name exact files, commands)
- Measurable (concrete pass/fail)
- Executable (can run and check)

**Good**: `pytest ralph/tests/unit/test_foo.py passes`
**Bad**: `works correctly` (vague, will be rejected)

### 3. Report

```
[RALPH] PLAN_COMPLETE: Added N tasks for {{SPEC_FILE}}
```

## Validation

Tasks are validated programmatically. REJECTED if:
- Notes < 50 chars or missing file paths
- Modification tasks without line numbers
- Acceptance criteria is vague
