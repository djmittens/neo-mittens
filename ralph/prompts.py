"""Prompt building and loading for Ralph stages.

This module handles loading PROMPT_*.md files, combining prompts with project
rules, and merging customized prompts with updated templates.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional


def get_ralph_dir() -> Path:
    """Get the ralph directory path.

    Returns the directory containing PROMPT_*.md files.
    """
    return Path(__file__).parent


def load_prompt(stage: str) -> str:
    """Load a prompt file for the given stage.

    Args:
        stage: Stage name (plan, build, verify, investigate, decompose)
               Case-insensitive.

    Returns:
        The prompt content as a string.

    Raises:
        FileNotFoundError: If the prompt file doesn't exist.
    """
    ralph_dir = get_ralph_dir()
    stage_lower = stage.lower()
    prompt_path = ralph_dir / f"PROMPT_{stage_lower}.md"

    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    return prompt_path.read_text()


def find_project_rules(repo_root: Path) -> Optional[str]:
    """Find and load project rules from AGENTS.md or CLAUDE.md.

    Searches for rules files in order of precedence (first found wins):
    1. AGENTS.md in repo root
    2. CLAUDE.md in repo root

    Args:
        repo_root: The repository root directory.

    Returns:
        The content of the rules file, or None if no rules file found.
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


def build_prompt_with_rules(prompt_content: str, project_rules: Optional[str]) -> str:
    """Combine project rules with a Ralph prompt.

    If project rules exist, prepend them to the prompt with clear separation.
    This ensures the AI follows repo-specific conventions while executing
    Ralph tasks.

    Args:
        prompt_content: The prompt content to wrap.
        project_rules: Optional project rules content (from AGENTS.md/CLAUDE.md).

    Returns:
        The combined prompt with rules prepended, or the original prompt
        if no rules provided.
    """
    if not project_rules:
        return prompt_content

    return f"""# Project Rules (from AGENTS.md)

The following rules are MANDATORY for this repository. Follow them strictly.

{project_rules}

---

# Ralph Task

{prompt_content}
"""


def get_prompt_for_stage(stage: str, mode: str = "construct") -> Path:
    """Get the appropriate prompt file path based on mode and stage.

    Args:
        stage: Stage name (BUILD, VERIFY, INVESTIGATE, DECOMPOSE, PLAN, COMPLETE)
               or Stage enum (will be converted via .name).
        mode: 'plan' or 'construct'.

    Returns:
        Path to the appropriate prompt file.
    """
    ralph_dir = get_ralph_dir()

    if mode == "plan":
        return ralph_dir / "PROMPT_plan.md"

    stage_str = stage.name if hasattr(stage, "name") else str(stage)
    stage_upper = stage_str.upper()

    if stage_upper == "VERIFY":
        return ralph_dir / "PROMPT_verify.md"
    elif stage_upper == "INVESTIGATE":
        return ralph_dir / "PROMPT_investigate.md"
    elif stage_upper == "DECOMPOSE":
        return ralph_dir / "PROMPT_decompose.md"
    else:
        return ralph_dir / "PROMPT_build.md"


def merge_prompts(
    existing_content: str,
    new_template: str,
    filename: str,
    repo_root: Path,
    timeout: int = 120,
) -> Optional[str]:
    """Use opencode to intelligently merge existing prompt customizations with new template.

    This function invokes an LLM to identify user customizations in the existing
    prompt and merge them with the new template while preserving both the
    customizations and new features.

    Args:
        existing_content: The user's current (possibly customized) prompt content.
        new_template: The new default template content.
        filename: The filename being merged (for context in the LLM prompt).
        repo_root: The repository root directory.
        timeout: Timeout in seconds for the LLM call.

    Returns:
        The merged content, or None if merge failed.
    """
    merge_prompt = f"""You are merging two versions of a Ralph prompt file: {filename}

EXISTING (user's customized version):
```
{existing_content}
```

NEW TEMPLATE (latest default):
```
{new_template}
```

Your task:
1. Identify any customizations the user made to the existing version
2. Preserve those customizations while incorporating any new features/improvements from the template
3. If the existing version has the same content as the template, just return the template
4. Output ONLY the merged content, no explanations or markdown code blocks

Merged content:"""

    try:
        opencode_env = os.environ.copy()
        opencode_env["XDG_STATE_HOME"] = "/tmp/ralph-opencode-state"
        opencode_env["OPENCODE_PERMISSION"] = json.dumps(
            {"external_directory": "deny", "doom_loop": "deny"}
        )

        result = subprocess.run(
            ["opencode", "run", "--print", merge_prompt],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=timeout,
            env=opencode_env,
        )

        if result.returncode == 0 and result.stdout.strip():
            merged = result.stdout.strip()
            if merged.startswith("```") and merged.endswith("```"):
                lines = merged.split("\n")
                merged = "\n".join(lines[1:-1])
            return merged
        else:
            return None
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        return None
    except Exception:
        return None


def substitute_spec_file(prompt_content: str, spec_file: str) -> str:
    """Substitute {{SPEC_FILE}} placeholder in prompt content.

    Args:
        prompt_content: The prompt content with placeholders.
        spec_file: The spec filename to substitute.

    Returns:
        The prompt content with placeholders replaced.
    """
    return prompt_content.replace("{{SPEC_FILE}}", spec_file)
