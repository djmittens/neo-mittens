"""Ralph set-spec command.

Sets the current spec for the project.
"""

from pathlib import Path

from ralph.state import load_state, save_state
from ralph.utils import Colors

__all__ = ["cmd_set_spec"]


def cmd_set_spec(config: dict, spec_file: str) -> int:
    """Set the current spec.

    Args:
        config: Ralph configuration dict with repo_root.
        spec_file: Path to the spec file to set.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    repo_root = config.get("repo_root", Path.cwd())
    ralph_dir = config.get("ralph_dir", repo_root / "ralph")

    if not ralph_dir.exists():
        print(
            f"{Colors.YELLOW}Ralph not initialized. Run 'ralph init' first.{Colors.NC}"
        )
        return 1

    # Validate spec file exists
    spec_path = Path(spec_file)
    if not spec_path.exists():
        # Try relative to ralph/specs/
        spec_path = ralph_dir / "specs" / spec_file
        if not spec_path.exists():
            print(f"{Colors.RED}Spec file not found: {spec_file}{Colors.NC}")
            return 1

    # Load state and update spec
    state = load_state(repo_root)
    old_spec = state.spec

    # Set new spec (just the filename, not full path)
    new_spec = spec_path.name
    state.spec = new_spec

    # Save state
    save_state(state, repo_root)

    if old_spec:
        print(f"{Colors.GREEN}Spec changed:{Colors.NC} {old_spec} -> {new_spec}")
    else:
        print(f"{Colors.GREEN}Spec set:{Colors.NC} {new_spec}")

    return 0
