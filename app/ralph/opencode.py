"""OpenCode process spawning and output parsing for Ralph."""

import json
import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional, Tuple

from ralph.context import Metrics

logger = logging.getLogger(__name__)


class Colors:
    """ANSI color codes for terminal output."""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'


def _opencode_env() -> dict:
    """Build environment for opencode subprocesses."""
    env = os.environ.copy()
    env["XDG_STATE_HOME"] = "/tmp/ralph-opencode-state"
    env["OPENCODE_PERMISSION"] = json.dumps(
        {"external_directory": "deny", "doom_loop": "deny"}
    )
    return env


def spawn_opencode(
    prompt: str,
    cwd: Path,
    timeout: int,
    model: Optional[str] = None,
    agent: Optional[str] = None,
) -> subprocess.Popen:
    """Spawn an opencode process with the given prompt.

    Args:
        prompt: The prompt content to send to opencode
        cwd: Working directory for the process
        timeout: Timeout in milliseconds (used by caller, not subprocess)
        model: Optional model override (uses opencode default if not specified)
        agent: Optional agent profile name (e.g. "ralph-build"). Controls
            which tools are available to the LLM via opencode's agent
            sandboxing.

    Returns:
        subprocess.Popen instance with stdout=PIPE for reading output
    """
    cmd = ["opencode", "run", "--format", "json"]
    if model:
        cmd.extend(["--model", model])
    if agent:
        cmd.extend(["--agent", agent])
    cmd.append(prompt)

    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        env=_opencode_env(),
    )


def spawn_opencode_continue(
    session_id: str,
    message: str,
    cwd: Path,
    model: Optional[str] = None,
    agent: Optional[str] = None,
) -> subprocess.Popen:
    """Continue an existing opencode session with a follow-up message.

    Reuses the session's cached context (system prompt, tool definitions,
    previous conversation) so follow-up messages only pay for new tokens.

    Args:
        session_id: Session ID from a previous opencode run.
        message: Follow-up message to send.
        cwd: Working directory for the process.
        model: Optional model override.
        agent: Optional agent profile name for tool sandboxing.

    Returns:
        subprocess.Popen instance with stdout=PIPE for reading output.
    """
    cmd = ["opencode", "run", "--format", "json", "-s", session_id]
    if model:
        cmd.extend(["--model", model])
    if agent:
        cmd.extend(["--agent", agent])
    cmd.append(message)

    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        env=_opencode_env(),
    )


def parse_json_stream(output: str) -> Iterator[dict]:
    """Parse newline-delimited JSON output from opencode.

    Args:
        output: Raw output string containing newline-delimited JSON

    Yields:
        Parsed JSON objects (dicts) for each valid JSON line
    """
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _format_tool_output(tool: str, args: dict, title: str, output: str) -> None:
    """Format and print tool use output with colors and icons."""
    C = Colors
    
    if tool == "bash":
        cmd = args.get("command", "")
        desc = args.get("description", "") or title
        print(f"\n{C.BRIGHT_YELLOW}Bash:{C.RESET} {C.DIM}{cmd[:80]}{C.RESET}")
        if desc:
            print(f"  {C.YELLOW}{desc}{C.RESET}")
    elif tool == "read":
        path = args.get("filePath", "")
        print(f"\n{C.BRIGHT_CYAN}Read:{C.RESET} {C.CYAN}{path}{C.RESET}")
    elif tool == "edit":
        path = args.get("filePath", "")
        print(f"\n{C.BRIGHT_GREEN}Edit:{C.RESET} {C.GREEN}{path}{C.RESET}")
    elif tool == "write":
        path = args.get("filePath", "")
        print(f"\n{C.BRIGHT_GREEN}Write:{C.RESET} {C.GREEN}{path}{C.RESET}")
    elif tool == "grep":
        pattern = args.get("pattern", "")
        print(f"\n{C.BRIGHT_MAGENTA}Grep:{C.RESET} {C.MAGENTA}{pattern}{C.RESET}")
    elif tool == "glob":
        pattern = args.get("pattern", "")
        print(f"\n{C.BRIGHT_MAGENTA}Glob:{C.RESET} {C.MAGENTA}{pattern}{C.RESET}")
    elif tool == "task":
        desc = args.get("description", "") or title
        print(f"\n{C.BRIGHT_BLUE}Task:{C.RESET} {C.BLUE}{desc}{C.RESET}")
    elif tool == "todowrite":
        todos = args.get("todos", [])
        print(f"\n{C.WHITE}TodoWrite:{C.RESET} {C.DIM}{len(todos)} todos{C.RESET}")
    elif tool == "ddg-search" or tool == "webfetch":
        query = args.get("query", "") or args.get("url", "") or title
        print(f"\n{C.BRIGHT_CYAN}Web:{C.RESET} {C.CYAN}{query}{C.RESET}")
    elif tool.startswith("ralph") or tool.startswith("mcp_ralph"):
        desc = args.get("description", "") or title or tool
        print(f"\n{C.BRIGHT_YELLOW}Ralph:{C.RESET} {C.YELLOW}{desc}{C.RESET}")
    else:
        label = f"{tool}: {title}" if title else tool
        print(f"\n{C.WHITE}{label}{C.RESET}")
    
    if output:
        lines = str(output).strip().split('\n')
        if len(lines) <= 3:
            for line in lines:
                print(f"  {C.DIM}{line[:100]}{C.RESET}")
        else:
            print(f"  {C.DIM}({len(lines)} lines){C.RESET}")
    sys.stdout.flush()


def _process_event(event: dict, metrics: Metrics) -> None:
    """Process a single JSON event from opencode output stream."""
    C = Colors
    event_type = event.get("type", "")
    part = event.get("part", {})
    
    if event_type == "text":
        text = part.get("text", "")
        if text:
            print(f"\n{C.WHITE}{text}{C.RESET}")
            sys.stdout.flush()
    
    elif event_type == "tool_use":
        tool = part.get("tool", "?")
        state = part.get("state", {})
        args = state.get("input", {})
        title = state.get("title", "")
        output = state.get("output", "")
        _format_tool_output(tool, args, title, output)
    
    elif event_type == "step_finish":
        cost = part.get("cost", 0)
        tokens = part.get("tokens", {})
        input_tokens = tokens.get("input", 0)
        output_tokens = tokens.get("output", 0)
        cache = tokens.get("cache", {})
        cache_read = cache.get("read", 0)
        context_size = input_tokens + cache_read
        
        if isinstance(cost, (int, float)):
            metrics.total_cost += cost
        if isinstance(input_tokens, int):
            metrics.total_tokens_in += input_tokens
        if isinstance(cache_read, int) and cache_read > 0:
            metrics.total_tokens_cached += cache_read
        if isinstance(output_tokens, int):
            metrics.total_tokens_out += output_tokens
        metrics.total_iterations += 1
        # Track actual window occupancy for context pressure detection
        metrics.last_context_size = context_size

        # Capture model and finish reason for telemetry
        model = part.get("model", "")
        if isinstance(model, str) and model:
            metrics.last_model = model
        finish_reason = part.get("finish_reason", "")
        if isinstance(finish_reason, str) and finish_reason:
            metrics.last_finish_reason = finish_reason
        
        cache_str = f" ({cache_read} cached)" if cache_read > 0 else ""
        print(f"\n{C.BRIGHT_BLACK}---{C.RESET}")
        print(f"Cost: ${cost:.4f} | Tokens: {context_size}in{cache_str}/{output_tokens}out")
        sys.stdout.flush()


@dataclass
class SessionResult:
    """Result from an opencode session run."""

    return_code: int
    raw_output: str
    timed_out: bool
    metrics: Metrics
    session_id: Optional[str] = None
    output_truncated: bool = False


def stream_and_collect(
    proc: subprocess.Popen,
    timeout_seconds: int,
    print_output: bool = True,
) -> SessionResult:
    """Stream output from opencode process while collecting metrics.

    Reads stdout line-by-line, parses JSON events, prints human-readable
    progress in real-time, and accumulates metrics.

    Args:
        proc: The opencode subprocess with stdout=PIPE
        timeout_seconds: Maximum time to wait for process completion
        print_output: Whether to print human-readable output (default True)

    Returns:
        SessionResult with return code, output, metrics, and session ID.
    """
    metrics = Metrics()
    output_lines: list[str] = []
    timed_out = False
    output_truncated = False
    session_id: Optional[str] = None

    def read_output():
        nonlocal timed_out, session_id, output_truncated
        if proc.stdout is None:
            return
        try:
            for line_bytes in proc.stdout:
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                output_lines.append(line)

                if not line:
                    continue

                try:
                    event = json.loads(line)

                    # Capture session ID from first event
                    if session_id is None:
                        sid = event.get("sessionID", "")
                        if sid:
                            session_id = sid

                    if print_output:
                        _process_event(event, metrics)
                    else:
                        event_type = event.get("type", "")
                        if event_type == "step_finish":
                            part = event.get("part", {})
                            cost = part.get("cost", 0)
                            tokens = part.get("tokens", {})
                            input_tokens = tokens.get("input", 0)
                            output_tokens = tokens.get("output", 0)
                            cache = tokens.get("cache", {})
                            cache_read = cache.get("read", 0)

                            if isinstance(cost, (int, float)):
                                metrics.total_cost += cost
                            if isinstance(input_tokens, int):
                                metrics.total_tokens_in += input_tokens
                            if isinstance(cache_read, int) and cache_read > 0:
                                metrics.total_tokens_cached += cache_read
                            if isinstance(output_tokens, int):
                                metrics.total_tokens_out += output_tokens
                            metrics.total_iterations += 1
                            context_size = input_tokens + cache_read
                            metrics.last_context_size = context_size

                            model = part.get("model", "")
                            if isinstance(model, str) and model:
                                metrics.last_model = model
                            finish_reason = part.get("finish_reason", "")
                            if isinstance(finish_reason, str) and finish_reason:
                                metrics.last_finish_reason = finish_reason
                except json.JSONDecodeError:
                    if print_output:
                        print(f"{Colors.RED}{line}{Colors.RESET}", file=sys.stderr)
                        sys.stderr.flush()
        except Exception as exc:
            output_truncated = True
            logger.warning(
                "Reader thread error (output may be truncated): %s", exc
            )

    reader_thread = threading.Thread(target=read_output, daemon=True)
    reader_thread.start()

    try:
        reader_thread.join(timeout=timeout_seconds)
        if reader_thread.is_alive():
            timed_out = True
            proc.kill()
            reader_thread.join(timeout=5)
            proc.wait()
        else:
            proc.wait()
    except Exception:
        proc.kill()
        reader_thread.join(timeout=5)
        proc.wait()
        timed_out = True

    raw_output = "\n".join(output_lines)
    return SessionResult(
        return_code=proc.returncode if proc.returncode is not None else -1,
        raw_output=raw_output,
        timed_out=timed_out,
        metrics=metrics,
        session_id=session_id,
        output_truncated=output_truncated,
    )
