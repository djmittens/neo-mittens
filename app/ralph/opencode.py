"""OpenCode process spawning and output parsing for Ralph."""

import json
import os
import subprocess
from pathlib import Path
from typing import Iterator, Optional

from ralph.context import Metrics


def spawn_opencode(
    prompt: str,
    cwd: Path,
    timeout: int,
    model: Optional[str] = None,
) -> subprocess.Popen:
    """Spawn an opencode process with the given prompt.

    Args:
        prompt: The prompt content to send to opencode
        cwd: Working directory for the process
        timeout: Timeout in milliseconds (used by caller, not subprocess)
        model: Optional model override (uses opencode default if not specified)

    Returns:
        subprocess.Popen instance with stdout=PIPE for reading output
    """
    opencode_env = os.environ.copy()
    opencode_env["XDG_STATE_HOME"] = "/tmp/ralph-opencode-state"

    permission_config = {"external_directory": "deny", "doom_loop": "deny"}
    opencode_env["OPENCODE_PERMISSION"] = json.dumps(permission_config)

    cmd = ["opencode", "run", "--format", "json"]
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)

    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        env=opencode_env,
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


def extract_metrics(output: str) -> Metrics:
    """Extract cost and token metrics from opencode JSON output.

    Parses step_finish events to accumulate cost and token usage.

    Args:
        output: Raw output string from opencode (newline-delimited JSON)

    Returns:
        Metrics instance with accumulated cost and token counts
    """
    metrics = Metrics()

    for event in parse_json_stream(output):
        event_type = event.get("type", "")

        if event_type == "step_finish":
            part = event.get("part", {})

            cost = part.get("cost", 0)
            if isinstance(cost, (int, float)):
                metrics.total_cost += cost

            tokens = part.get("tokens", {})
            input_tokens = tokens.get("input", 0)
            output_tokens = tokens.get("output", 0)
            cache = tokens.get("cache", {})
            cache_read = cache.get("read", 0)

            if isinstance(input_tokens, int):
                metrics.total_tokens_in += input_tokens + cache_read
            if isinstance(output_tokens, int):
                metrics.total_tokens_out += output_tokens

            metrics.total_iterations += 1

    return metrics
