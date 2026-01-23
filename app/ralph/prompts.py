"""Prompt loading and management utilities for Ralph."""

from pathlib import Path
from typing import Optional


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


def build_prompt_with_rules(prompt: str, rules_path: Path) -> str:
    """Combine prompt content with project rules from AGENTS.md.

    Args:
        prompt: The base prompt content.
        rules_path: Path to the AGENTS.md or similar rules file.

    Returns:
        Combined prompt with rules prepended.
    """
    if not rules_path.exists():
        return prompt

    try:
        project_rules = rules_path.read_text()
    except (OSError, IOError):
        return prompt

    if not project_rules.strip():
        return prompt

    return f"""# Project Rules (from {rules_path.name})

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
