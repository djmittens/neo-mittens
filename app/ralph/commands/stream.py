"""Ralph stream command.

Pipe opencode JSON output for pretty display.
"""

import json
import select
import sys

from ralph.utils import Colors

__all__ = ["cmd_stream"]


def cmd_stream() -> int:
    """Stream command - pipe opencode JSON for pretty output.

    Reads from stdin and pretty-prints JSON stream.

    Returns:
        Exit code (0 for success).
    """
    print(f"{Colors.CYAN}Waiting for JSON stream on stdin...{Colors.NC}")
    print(f"{Colors.DIM}(Pipe opencode output here){Colors.NC}")

    try:
        while True:
            if select.select([sys.stdin], [], [], 0.1)[0]:
                line = sys.stdin.readline()
                if not line:
                    break
                try:
                    data = json.loads(line)
                    if "type" in data:
                        msg_type = data.get("type", "")
                        if msg_type == "assistant":
                            content = data.get("content", "")
                            print(content, end="", flush=True)
                        elif msg_type == "tool_use":
                            tool = data.get("name", "unknown")
                            print(
                                f"\n{Colors.DIM}[Tool: {tool}]{Colors.NC}", flush=True
                            )
                except json.JSONDecodeError:
                    print(line, end="", flush=True)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Stream ended.{Colors.NC}")

    return 0
