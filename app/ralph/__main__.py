#!/usr/bin/env python3
import sys


def main() -> int:
    """Entry point for ralph CLI."""
    args = sys.argv[1:]

    if "--help" in args or "-h" in args or not args:
        print("usage: ralph [-h] [--version] <command> [<args>]")
        print()
        print("Ralph - Autonomous Development Agent")
        print()
        print("commands:")
        print("  init       Initialize ralph in current directory")
        print("  status     Show ralph status")
        print("  config     Configure ralph settings")
        print("  watch      Watch for changes")
        print("  stream     Stream opencode output")
        print("  plan       Create plan from spec")
        print("  construct  Run autonomous construction")
        print("  query      Query current state")
        print("  task       Manage tasks")
        print("  issue      Manage issues")
        print("  validate   Validate plan")
        print("  compact    Compact plan file")
        print()
        print("options:")
        print("  -h, --help     show this help message and exit")
        print("  --version      show program's version number and exit")
        return 0

    if "--version" in args:
        from ralph import __version__

        print(f"ralph {__version__}")
        return 0

    print(f"ralph: unknown command '{args[0]}'", file=sys.stderr)
    print("Try 'ralph --help' for more information.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
