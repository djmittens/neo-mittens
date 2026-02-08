"""Ralph init command.

Creates ralph directory structure and initializes tix. Prompt templates
are embedded in the package and loaded at runtime — no prompt files are
written to the target repository.
"""

from pathlib import Path
from typing import Optional

from ralph.config import get_global_config
from ralph.tix import Tix
from ralph.utils import Colors

from ralph.commands.init_prompts import EXAMPLE_SPEC


def cmd_init(repo_root: Optional[Path] = None) -> int:
    """Initialize Ralph in a repository.

    Creates the ralph directory structure and initializes tix for ticket
    management. Prompt templates are embedded in the package and do not
    need to be written to disk.

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

    is_update = ralph_dir.exists()

    if is_update:
        print(f"Ralph already initialized in {repo_root}")
        return 0

    print(f"Initializing Ralph in {repo_root}")

    ralph_dir.mkdir(parents=True, exist_ok=True)
    specs_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    example_spec = specs_dir / "example.md"
    if not example_spec.exists():
        example_spec.write_text(EXAMPLE_SPEC)

    # Initialize tix (creates .tix/ directory and plan.jsonl)
    tix = Tix(repo_root)
    try:
        tix.init()
    except Exception:
        # tix init may fail if already initialized — that's fine
        pass

    print(f"\n{Colors.GREEN}Ralph initialized!{Colors.NC}")
    print("""
Next steps:
  1. Write specs in ralph/specs/
  2. Run 'ralph plan <spec.md>' to generate tasks
  3. Run 'ralph' to start building

Files created:
  ralph/
  └── specs/
      └── example.md        (delete and add your own)
  .tix/
  └── plan.jsonl            (ticket data via tix)
""")

    return 0
