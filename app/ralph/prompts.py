"""Prompt loading and management utilities for Ralph.

This module provides:
1. Template loading from PROMPT_*.md files
2. Context injection to replace template variables with actual data
3. Structured context builders for each stage
"""

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ralph.state import RalphState
    from ralph.models import Task, Issue


def load_prompt(stage: str, ralph_dir: Optional[Path] = None) -> str:
    """Load a prompt file for the given stage.

    Args:
        stage: The stage name (plan, build, verify, investigate, decompose)
        ralph_dir: Path to ralph directory. Defaults to cwd/ralph.

    Returns:
        The prompt content as a string.

    Raises:
        FileNotFoundError: If the prompt file doesn't exist.
    """
    if ralph_dir is None:
        ralph_dir = Path.cwd() / "ralph"

    prompt_file = ralph_dir / f"PROMPT_{stage}.md"

    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

    return prompt_file.read_text()


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


def _task_to_context(task: "Task") -> dict[str, Any]:
    """Convert a Task to a context dict for template injection."""
    return {
        "id": task.id,
        "name": task.name,
        "spec": task.spec,
        "notes": task.notes or "",
        "accept": task.accept or "",
        "deps": task.deps or [],
        "status": task.status,
        "priority": task.priority or "medium",
        "reject": task.reject_reason or "",
        "kill_reason": task.kill_reason or "",
        "kill_log": task.kill_log or "",
        "parent": task.parent or "",
        "decompose_depth": task.decompose_depth,
    }


def _issue_to_context(issue: "Issue") -> dict[str, Any]:
    """Convert an Issue to a context dict for template injection."""
    return {
        "id": issue.id,
        "desc": issue.desc,
        "spec": issue.spec,
        "priority": issue.priority or "medium",
    }


def build_build_context(task: "Task", spec_content: str = "") -> dict[str, Any]:
    """Build context dict for BUILD stage prompt.

    Args:
        task: The task to build
        spec_content: Optional spec file content

    Returns:
        Context dict with TASK_* and SPEC_CONTENT variables
    """
    task_ctx = _task_to_context(task)
    return {
        "task": task_ctx,
        "task_json": json.dumps(task_ctx, indent=2),
        "task_name": task.name,
        "task_notes": task.notes or "",
        "task_accept": task.accept or "",
        "task_reject": task.reject_reason or "",
        "task_id": task.id,
        "spec_file": task.spec,
        "spec_content": spec_content,
        "is_retry": "true" if task.reject_reason else "false",
    }


def build_verify_context(
    done_tasks: list["Task"], spec_name: str, spec_content: str = ""
) -> dict[str, Any]:
    """Build context dict for VERIFY stage prompt.

    Args:
        done_tasks: List of tasks with status 'd' (done)
        spec_name: Name of the current spec
        spec_content: Content of the spec file

    Returns:
        Context dict with DONE_TASKS and SPEC_* variables
    """
    tasks_data = [_task_to_context(t) for t in done_tasks]
    return {
        "done_tasks": tasks_data,
        "done_tasks_json": json.dumps(tasks_data, indent=2),
        "done_count": len(done_tasks),
        "spec_file": spec_name,
        "spec_content": spec_content,
    }


def build_investigate_context(
    issues: list["Issue"], spec_name: str, spec_content: str = ""
) -> dict[str, Any]:
    """Build context dict for INVESTIGATE stage prompt.

    Args:
        issues: List of issues to investigate
        spec_name: Name of the current spec
        spec_content: Content of the spec file

    Returns:
        Context dict with ISSUES and SPEC_* variables
    """
    issues_data = [_issue_to_context(i) for i in issues]
    return {
        "issues": issues_data,
        "issues_json": json.dumps(issues_data, indent=2),
        "issue_count": len(issues),
        "spec_file": spec_name,
        "spec_content": spec_content,
    }


def build_decompose_context(
    task: "Task", kill_log_preview: str = "", spec_content: str = ""
) -> dict[str, Any]:
    """Build context dict for DECOMPOSE stage prompt.

    Args:
        task: The killed task that needs decomposition
        kill_log_preview: First/last N lines of the kill log
        spec_content: Content of the spec file

    Returns:
        Context dict with KILLED_TASK_* and log preview variables
    """
    task_ctx = _task_to_context(task)
    return {
        "task": task_ctx,
        "task_json": json.dumps(task_ctx, indent=2),
        "task_name": task.name,
        "task_notes": task.notes or "",
        "task_id": task.id,
        "kill_reason": task.kill_reason or "unknown",
        "kill_log_path": task.kill_log or "",
        "kill_log_preview": kill_log_preview,
        "spec_file": task.spec,
        "spec_content": spec_content,
        "decompose_depth": task.decompose_depth,
        "max_depth": 3,
    }


def build_plan_context(spec_name: str, spec_content: str) -> dict[str, Any]:
    """Build context dict for PLAN stage prompt.

    Args:
        spec_name: Name of the spec file
        spec_content: Full content of the spec file

    Returns:
        Context dict with SPEC_* variables
    """
    return {
        "spec_file": spec_name,
        "spec_content": spec_content,
    }


def load_and_inject(
    stage: str, context: dict[str, Any], ralph_dir: Optional[Path] = None
) -> str:
    """Load a prompt template and inject context in one step.

    Args:
        stage: Stage name (build, verify, investigate, decompose, plan)
        context: Context dict from build_*_context functions
        ralph_dir: Optional path to ralph directory

    Returns:
        Fully rendered prompt with all placeholders replaced
    """
    template = load_prompt(stage, ralph_dir)
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


def merge_prompts(old: str, new: str, strategy: str) -> str:
    """Merge old and new prompt content based on strategy.

    Args:
        old: Existing prompt content.
        new: New prompt template content.
        strategy: One of 'keep', 'override', or 'merge'.

    Returns:
        The merged prompt content.
    """
    if strategy == "keep":
        return old
    elif strategy == "override":
        return new
    elif strategy == "merge":
        if old.strip() == new.strip():
            return new
        return f"""# MERGED PROMPT - Review and consolidate manually

## === EXISTING CONTENT (preserved customizations) ===

{old}

## === NEW TEMPLATE ===

{new}
"""
    else:
        raise ValueError(f"Unknown merge strategy: {strategy}")
