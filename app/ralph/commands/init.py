"""Ralph init command.

Creates ralph directory structure, prompt templates, and initial plan.jsonl.
Supports both fresh initialization and updating existing installations.
"""

from pathlib import Path
from typing import Optional

from ralph.config import get_global_config
from ralph.state import RalphState, save_state
from ralph.utils import Colors

from ralph.commands.init_helpers import handle_prompt_file
from ralph.commands.init_prompts import EXAMPLE_SPEC, PROMPT_TEMPLATES


def cmd_init(repo_root: Optional[Path] = None) -> int:
    """Initialize or update Ralph in a repository.

    Creates the ralph directory structure, prompt templates, and initial
    plan.jsonl file. If ralph is already initialized, offers to update
    prompt templates with merge options.

    Args:
        repo_root: Repository root directory. If None, uses current directory.

    Returns:
        Exit code (0 for success).
    """
    if repo_root is None:
        repo_root = Path.cwd()

    config = get_global_config()
    ralph_dir = repo_root / config.ralph_dir
    specs_dir = ralph_dir / "specs"
    log_dir = repo_root / config.log_dir
    plan_file = ralph_dir / "plan.jsonl"

    is_update = ralph_dir.exists()

    if is_update:
        print(f"Updating Ralph in {repo_root}")
    else:
        print(f"Initializing Ralph in {repo_root}")

    ralph_dir.mkdir(parents=True, exist_ok=True)
    specs_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in PROMPT_TEMPLATES.items():
        prompt_path = ralph_dir / filename
        handle_prompt_file(prompt_path, content, repo_root)

    if not is_update:
        example_spec = specs_dir / "example.md"
        if not example_spec.exists():
            example_spec.write_text(EXAMPLE_SPEC)

        if not plan_file.exists():
            save_state(RalphState(), plan_file)

    if is_update:
        print(f"\n{Colors.GREEN}Ralph updated!{Colors.NC}")
        print(f"""
Updated files:
  ralph/
  ├── PROMPT_plan.md        (planning mode)
  ├── PROMPT_build.md       (build stage)
  ├── PROMPT_verify.md      (verify stage)
  ├── PROMPT_investigate.md (investigate stage)
  └── PROMPT_decompose.md   (decompose stage)

Preserved:
  ├── plan.jsonl
  └── specs/*
""")
    else:
        print(f"\n{Colors.GREEN}Ralph initialized!{Colors.NC}")
        print("""
Next steps:
  1. Write specs in ralph/specs/
  2. Run 'ralph plan <spec.md>' to generate tasks
  3. Run 'ralph' to start building

Files created:
  ralph/
  ├── PROMPT_plan.md        (planning mode)
  ├── PROMPT_build.md       (build stage)
  ├── PROMPT_verify.md      (verify stage)
  ├── PROMPT_investigate.md (investigate stage)
  ├── PROMPT_decompose.md   (decompose stage)
  ├── plan.jsonl            (task/issue state)
  └── specs/
      └── example.md        (delete and add your own)
""")

    return 0
