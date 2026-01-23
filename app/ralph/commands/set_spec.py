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
        config: Ralph configuration dict with plan_file.
        spec_file: Path to the spec file to set.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    plan_file = config.get("plan_file")
    if not plan_file or not plan_file.exists():
        print(
            f"{Colors.YELLOW}Ralph not initialized. Run 'ralph init' first.{Colors.NC}"
        )
        return 1

    # Validate spec file exists
    spec_path = Path(spec_file)
    if not spec_path.exists():
        # Try relative to ralph/specs/
        ralph_dir = config.get("ralph_dir", Path.cwd() / "ralph")
        spec_path = ralph_dir / "specs" / spec_file
        if not spec_path.exists():
            print(f"{Colors.RED}Spec file not found: {spec_file}{Colors.NC}")
            return 1

    # Load state and update spec
    state = load_state(plan_file)
    old_spec = state.spec

    # Set new spec (just the filename, not full path)
    new_spec = spec_path.name
    state.spec = new_spec

    # Save state
    save_state(state, plan_file)

    if old_spec:
        print(f"{Colors.GREEN}Spec changed:{Colors.NC} {old_spec} -> {new_spec}")
    else:
        print(f"{Colors.GREEN}Spec set:{Colors.NC} {new_spec}")

    return 0
