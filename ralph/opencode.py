"""OpenCode integration module for Ralph.

This module provides functions to spawn and interact with the opencode
command-line tool, parse its JSON output stream, and extract metrics
from the output.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator, Optional, Union, Iterator
import json
import os
import re
import subprocess


@dataclass
class OpenCodeMetrics:
    """Metrics extracted from opencode output.

    Attributes:
        cost: Total cost in dollars.
        tokens_in: Total input tokens.
        tokens_out: Total output tokens.
        cache_read: Tokens read from cache.
        cache_write: Tokens written to cache.
    """

    cost: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cache_write: int = 0


@dataclass
class OpenCodeEvent:
    """A parsed event from the opencode JSON stream.

    Attributes:
        type: The event type (e.g., "step_start", "text", "tool_use", "step_finish").
        part: The event-specific data.
        raw: The original raw JSON dict.
    """

    type: str
    part: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def build_opencode_env(
    stage: Optional[str] = None,
    allow_read_all: bool = False,
) -> dict[str, str]:
    """Build environment variables for opencode subprocess.

    Sets up XDG_STATE_HOME to avoid polluting session list and
    configures OPENCODE_PERMISSION to control opencode's permission system.

    Args:
        stage: Optional stage name (e.g., "DECOMPOSE") to adjust permissions.
        allow_read_all: If True, allow read access to all files.

    Returns:
        A dict of environment variables to pass to subprocess.
    """
    env = os.environ.copy()
    env["XDG_STATE_HOME"] = "/tmp/ralph-opencode-state"

    permission_config: dict[str, Any] = {
        "external_directory": "deny",
        "doom_loop": "deny",
    }

    if stage == "DECOMPOSE" or allow_read_all:
        permission_config["read"] = {"*": "allow"}
        permission_config["external_directory"] = {"*": "deny"}

    env["OPENCODE_PERMISSION"] = json.dumps(permission_config)
    return env


def check_opencode_available() -> tuple[bool, Optional[str]]:
    """Check if opencode is available and working.

    Returns:
        Tuple of (is_available, error_message).
        If available, error_message is None.
    """
    try:
        result = subprocess.run(
            ["opencode", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, None
        else:
            return False, f"opencode returned error: {result.stderr.strip()}"
    except FileNotFoundError:
        return False, (
            "opencode not found in PATH. "
            "Install it with: npm install -g @anthropic/opencode"
        )
    except subprocess.TimeoutExpired:
        return False, "opencode timed out during version check"
    except Exception as e:
        return False, f"Error checking opencode: {e}"


def spawn_opencode(
    prompt: str,
    cwd: Path,
    timeout: Optional[int] = None,
    model: Optional[str] = None,
    stage: Optional[str] = None,
    print_mode: bool = False,
) -> subprocess.Popen:
    """Spawn an opencode process.

    Args:
        prompt: The prompt content to send to opencode.
        cwd: Working directory for the subprocess.
        timeout: Optional timeout in seconds (not enforced here, caller must handle).
        model: Optional model name to use. Defaults to opencode's default.
        stage: Optional stage name for permission configuration.
        print_mode: If True, use --print mode for single-response output.

    Returns:
        The Popen object for the spawned process.

    Raises:
        FileNotFoundError: If opencode is not installed.
        subprocess.SubprocessError: If spawning fails.
    """
    cmd = ["opencode", "run"]

    if model:
        cmd.extend(["--model", model])

    if print_mode:
        cmd.append("--print")
    else:
        cmd.extend(["--format", "json"])

    cmd.append(prompt)

    env = build_opencode_env(stage=stage)

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(cwd),
        env=env,
    )
    return proc


def run_opencode_print(
    prompt: str,
    cwd: Path,
    timeout: int = 120,
    model: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run opencode and return the result.

    This is a simpler interface for cases where you just need the
    final output without streaming.

    Args:
        prompt: The prompt content to send to opencode.
        cwd: Working directory for the subprocess.
        timeout: Timeout in seconds (default 120).
        model: Optional model name to use.

    Returns:
        CompletedProcess with stdout/stderr.

    Raises:
        subprocess.TimeoutExpired: If the process times out.
        FileNotFoundError: If opencode is not installed.
    """
    cmd = ["opencode", "run"]

    if model:
        cmd.extend(["--model", model])

    cmd.append(prompt)

    env = build_opencode_env()

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=timeout,
        env=env,
    )


def parse_json_stream(
    output: str,
) -> Generator[OpenCodeEvent, None, None]:
    """Parse opencode JSON stream output into structured events.

    Args:
        output: The raw output from opencode in JSON format.
            Can be a single JSON object or newline-delimited JSON.

    Yields:
        OpenCodeEvent objects for each successfully parsed event.
        Invalid JSON lines are silently skipped.
    """
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = data.get("type", "")
        part = data.get("part", {})

        yield OpenCodeEvent(
            type=event_type,
            part=part,
            raw=data,
        )


def parse_json_stream_iter(
    lines_iter: Iterator[Union[str, bytes]],
) -> Generator[OpenCodeEvent, None, None]:
    """Parse opencode JSON stream from an iterator of lines.

    This is useful for parsing output line-by-line as it arrives
    from a subprocess pipe.

    Args:
        lines_iter: An iterator that yields lines of JSON output as str or bytes.

    Yields:
        OpenCodeEvent objects for each successfully parsed event.
    """
    for line in lines_iter:
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        line = line.strip()
        if not line:
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = data.get("type", "")
        part = data.get("part", {})

        yield OpenCodeEvent(
            type=event_type,
            part=part,
            raw=data,
        )


def extract_metrics(output: str) -> OpenCodeMetrics:
    """Extract cost and token metrics from opencode output.

    This function parses the opencode output to find cost and token
    information, either from the JSON stream or from formatted output.

    Args:
        output: The raw output from opencode.

    Returns:
        OpenCodeMetrics with extracted values. Zero values if no metrics found.
    """
    metrics = OpenCodeMetrics()

    for event in parse_json_stream(output):
        if event.type == "step_finish":
            cost = event.part.get("cost", 0)
            if cost:
                metrics.cost += float(cost)

            tokens = event.part.get("tokens", {})
            metrics.tokens_in += int(tokens.get("input", 0))
            metrics.tokens_out += int(tokens.get("output", 0))

            cache = tokens.get("cache", {})
            metrics.cache_read += int(cache.get("read", 0))
            metrics.cache_write += int(cache.get("write", 0))

    if metrics.tokens_in == 0 and metrics.tokens_out == 0:
        match = re.search(
            r"Cost: \$([0-9.]+) \| Tokens: (\d+)in/(\d+)out",
            output,
        )
        if match:
            metrics.cost = float(match.group(1))
            metrics.tokens_in = int(match.group(2))
            metrics.tokens_out = int(match.group(3))

    return metrics


def extract_metrics_from_line(line: str) -> Optional[tuple[float, int, int]]:
    """Parse a cost line from ralph-stream output.

    This is a utility function for parsing individual lines during
    real-time stream processing.

    Args:
        line: A single line of output.

    Returns:
        Tuple of (cost, tokens_in, tokens_out) or None if not a cost line.
    """
    match = re.search(r"Cost: \$([0-9.]+) \| Tokens: (\d+)in/(\d+)out", line)
    if match:
        return (float(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def count_running_opencode(repo_root: Path) -> int:
    """Count opencode processes spawned by ralph in this repo.

    On macOS, uses pgrep to find opencode processes.
    Note: This function checks /proc which only works on Linux. On macOS,
    it falls back to just counting pgrep results without parent filtering.

    Args:
        repo_root: The repository root directory to check.

    Returns:
        Number of opencode processes running in this repo, or 0 if unable to determine.
    """
    import sys

    count = 0
    try:
        result = subprocess.run(
            ["pgrep", "-x", "opencode"],
            capture_output=True,
            text=True,
        )
        pids = [p for p in result.stdout.strip().split("\n") if p]

        if sys.platform == "darwin":
            return len(pids)

        for pid in pids:
            try:
                cwd = Path(f"/proc/{pid}/cwd").resolve()
                if not str(cwd).startswith(str(repo_root)):
                    continue

                ppid = Path(f"/proc/{pid}/stat").read_text().split()[3]
                parent_cmdline = (
                    Path(f"/proc/{ppid}/cmdline")
                    .read_bytes()
                    .decode("utf-8", errors="replace")
                )
                if "ralph" in parent_cmdline:
                    count += 1
            except (OSError, PermissionError, FileNotFoundError):
                pass
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return count


__all__ = [
    "OpenCodeMetrics",
    "OpenCodeEvent",
    "build_opencode_env",
    "check_opencode_available",
    "spawn_opencode",
    "run_opencode_print",
    "parse_json_stream",
    "parse_json_stream_iter",
    "extract_metrics",
    "extract_metrics_from_line",
    "count_running_opencode",
]
