"""Prompt loading and management utilities for Ralph.

This module provides:
1. Template loading from package-embedded defaults
2. Context injection to replace template variables with actual data
3. Structured context builders for each stage
"""

import json
from pathlib import Path
from typing import Any, Optional


def load_prompt(stage: str) -> str:
    """Load the prompt template for the given stage.

    Prompts are loaded from package-embedded defaults in init_prompts.py.
    No files are read from the target repository.

    Args:
        stage: The stage name (plan, build, verify, investigate, decompose)

    Returns:
        The prompt content as a string.

    Raises:
        KeyError: If the stage name is not recognized.
    """
    from ralph.commands.init_prompts import PROMPTS

    if stage not in PROMPTS:
        raise KeyError(
            f"Unknown stage: {stage!r}. "
            f"Valid stages: {', '.join(sorted(PROMPTS))}"
        )

    return PROMPTS[stage]


def inject_context(template: str, context: dict[str, Any]) -> str:
    """Inject context variables into a prompt template.

    Replaces {{VARIABLE}} placeholders with values from context dict.
    Handles nested paths like {{task.name}} by flattening to {{TASK_NAME}}.

    Args:
        template: Prompt template with {{VAR}} placeholders
        context: Dict of variable names to values

    Returns:
        Prompt with all placeholders replaced
    """
    result = template

    for key, value in context.items():
        placeholder = "{{" + key.upper() + "}}"
        if isinstance(value, (dict, list)):
            replacement = json.dumps(value, indent=2)
        elif value is None:
            replacement = ""
        else:
            replacement = str(value)
        result = result.replace(placeholder, replacement)

    return result


def build_plan_context(
    spec_name: str,
    spec_content: str,
    tix_history: Optional[str] = None,
    pending_tasks: Optional[str] = None,
) -> dict[str, Any]:
    """Build context dict for PLAN stage prompt.

    Args:
        spec_name: Name of the spec file
        spec_content: Full content of the spec file
        tix_history: Optional formatted tix history (accepted/rejected tasks)
        pending_tasks: Optional formatted pending tasks for incremental planning

    Returns:
        Context dict with SPEC_*, TIX_*, and PENDING_* variables
    """
    return {
        "spec_file": spec_name,
        "spec_content": spec_content,
        "tix_history": tix_history or "",
        "pending_tasks": pending_tasks or "",
    }


# =========================================================================
# Stage context builders (work with raw dicts from tix JSON output)
# =========================================================================


def build_build_context(
    task: dict, spec_name: str = "", spec_content: str = ""
) -> dict[str, Any]:
    """Build context dict for BUILD stage prompt.

    Args:
        task: Task dict from tix query output.
        spec_name: Spec file name.
        spec_content: Content of the spec file.

    Returns:
        Context dict for prompt injection.
    """
    return {
        "task_json": json.dumps(task, indent=2),
        "task_name": task.get("name", ""),
        "task_notes": task.get("notes", ""),
        "task_accept": task.get("accept", ""),
        "task_reject": task.get("reject", ""),
        "task_id": task.get("id", ""),
        "spec_file": spec_name or task.get("spec", ""),
        "spec_content": spec_content,
        "is_retry": "true" if task.get("reject") else "false",
    }


def build_verify_context(
    done_tasks: list[dict],
    spec_name: str,
    spec_content: str = "",
    build_diff: str = "",
) -> dict[str, Any]:
    """Build context dict for VERIFY stage prompt.

    Args:
        done_tasks: List of done task dicts from tix query.
        spec_name: Spec file name.
        spec_content: Content of the spec file.
        build_diff: Unified diff of uncommitted changes from BUILD.

    Returns:
        Context dict for prompt injection.
    """
    return {
        "done_tasks_json": json.dumps(done_tasks, indent=2),
        "done_count": len(done_tasks),
        "spec_file": spec_name,
        "spec_content": spec_content,
        "build_diff": build_diff or "(no diff available)",
    }


def build_investigate_context(
    issues: list[dict],
    spec_name: str,
    spec_content: str = "",
    pending_tasks: list[dict] | None = None,
) -> dict[str, Any]:
    """Build context dict for INVESTIGATE stage prompt.

    Args:
        issues: List of issue dicts from tix query.
        spec_name: Spec file name.
        spec_content: Content of the spec file.
        pending_tasks: Pending task list so INVESTIGATE avoids duplicates.

    Returns:
        Context dict for prompt injection.
    """
    # Compact task summary: just id + name to keep token count low.
    if pending_tasks:
        compact = [
            {"id": t.get("id", ""), "name": t.get("name", "")}
            for t in pending_tasks
        ]
        pending_json = json.dumps(compact, indent=2)
        pending_count = len(compact)
    else:
        pending_json = "[]"
        pending_count = 0

    return {
        "issues_json": json.dumps(issues, indent=2),
        "issue_count": len(issues),
        "spec_file": spec_name,
        "spec_content": spec_content,
        "pending_tasks_json": pending_json,
        "pending_task_count": pending_count,
    }


def build_decompose_context(
    task: dict,
    spec_name: str = "",
    spec_content: str = "",
    max_depth: int = 3,
) -> dict[str, Any]:
    """Build context dict for DECOMPOSE stage prompt.

    Intentionally omits spec_content to save tokens — DECOMPOSE only
    needs the task JSON and kill info. The spec filename is included
    for reference only.

    Args:
        task: The killed task dict from tix query.
        spec_name: Spec file name.
        spec_content: Unused (kept for API compat). Not injected.
        max_depth: Maximum decomposition depth from config.

    Returns:
        Context dict for prompt injection.
    """
    return {
        "task_json": json.dumps(task, indent=2),
        "task_name": task.get("name", ""),
        "task_id": task.get("id", ""),
        "kill_reason": task.get("kill_reason", "unknown"),
        "kill_log_path": task.get("kill_log", ""),
        "spec_file": spec_name or task.get("spec", ""),
        "decompose_depth": task.get("decompose_depth", 0),
        "max_depth": max_depth,
    }


def load_and_inject(stage: str, context: dict[str, Any]) -> str:
    """Load a prompt template and inject context in one step.

    Args:
        stage: Stage name (build, verify, investigate, decompose, plan)
        context: Context dict from build_*_context functions

    Returns:
        Fully rendered prompt with all placeholders replaced
    """
    template = load_prompt(stage)
    return inject_context(template, context)


def build_prompt_with_rules(prompt: str, rules: Any) -> str:
    """Combine prompt content with project rules.

    Args:
        prompt: The base prompt content.
        rules: Either a Path to rules file, or the rules content as a string.

    Returns:
        Combined prompt with rules prepended.
    """
    # Handle both Path and string content
    if rules is None:
        return prompt
    
    if isinstance(rules, Path):
        if not rules.exists():
            return prompt
        try:
            project_rules = rules.read_text()
            rules_name = rules.name
        except (OSError, IOError):
            return prompt
    elif isinstance(rules, str):
        project_rules = rules
        rules_name = "AGENTS.md"
    else:
        return prompt

    if not project_rules.strip():
        return prompt

    return f"""# Project Rules (from {rules_name})

The following rules are MANDATORY for this repository. Follow them strictly.

{project_rules}

---

# Ralph Task

{prompt}
"""


def find_project_rules(repo_root: Path) -> Optional[str]:
    """Find and load project rules from AGENTS.md or CLAUDE.md.

    Args:
        repo_root: Root of the repository.

    Returns:
        The rules content, or None if no rules file found.
    """
    candidates = [
        repo_root / "AGENTS.md",
        repo_root / "CLAUDE.md",
    ]

    for path in candidates:
        if path.exists():
            try:
                return path.read_text()
            except (OSError, IOError):
                pass

    return None



