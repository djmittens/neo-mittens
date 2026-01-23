"""Helper functions for Ralph init command.

Handles prompt file merging and user interaction during initialization.
"""

from pathlib import Path

from ralph.prompts import merge_prompts
from ralph.utils import Colors


def prompt_merge_choice(filename: str) -> str:
    """Prompt user for merge choice when updating prompt files.

    Args:
        filename: The prompt file name.

    Returns:
        One of 'keep', 'override', or 'merge'.
    """
    print(f"\n{Colors.YELLOW}{filename} has been customized.{Colors.NC}")
    print("  [k] Keep existing (skip update)")
    print("  [o] Override with new default template")
    print("  [m] Merge customizations with new template (uses LLM)")

    while True:
        try:
            choice = input("Choice [k/o/m]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "keep"

        if choice in ("k", "keep"):
            return "keep"
        elif choice in ("o", "override"):
            return "override"
        elif choice in ("m", "merge"):
            return "merge"
        else:
            print("Please enter k, o, or m")


def handle_prompt_file(prompt_path: Path, new_content: str, repo_root: Path) -> None:
    """Handle creating or updating a prompt file with merge options.

    Args:
        prompt_path: Path to the prompt file.
        new_content: The new default template content.
        repo_root: The repository root directory.
    """
    if not prompt_path.exists():
        prompt_path.write_text(new_content)
        return

    existing_content = prompt_path.read_text()

    if existing_content.strip() == new_content.strip():
        print(f"  {Colors.DIM}{prompt_path.name} - unchanged{Colors.NC}")
        return

    choice = prompt_merge_choice(prompt_path.name)

    if choice == "keep":
        print(f"  {Colors.YELLOW}Keeping existing {prompt_path.name}{Colors.NC}")
    elif choice == "override":
        prompt_path.write_text(new_content)
        print(
            f"  {Colors.GREEN}Replaced {prompt_path.name} with default template{Colors.NC}"
        )
    elif choice == "merge":
        print(f"  {Colors.CYAN}Merging {prompt_path.name} with LLM...{Colors.NC}")
        merged = merge_prompts(existing_content, new_content, "merge")
        if merged:
            prompt_path.write_text(merged)
            print(f"  {Colors.GREEN}Merged {prompt_path.name} successfully{Colors.NC}")
        else:
            print(
                f"  {Colors.YELLOW}Merge failed, keeping existing {prompt_path.name}{Colors.NC}"
            )
