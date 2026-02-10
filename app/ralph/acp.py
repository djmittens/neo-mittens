"""ACP (Agent Client Protocol) client for OpenCode.

Manages a persistent opencode ACP subprocess and provides structured
session management. Each stage gets a fresh session (context isolation)
while reusing the same process (~4ms session creation vs ~2.7s cold start).

Key advantages over ``opencode run``:
- Structured tool call events with rawInput/rawOutput (no text parsing)
- Bash exit codes and file paths available directly
- Context utilization tracking via usage_update notifications
- ~300x faster session creation for multi-stage workflows

Protocol: JSON-RPC 2.0 over stdio with opencode ACP v1.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ralph.context import Metrics

logger = logging.getLogger(__name__)

# Protocol version for opencode ACP
ACP_PROTOCOL_VERSION = 1

# Timeouts
INIT_TIMEOUT_S = 30.0
SESSION_TIMEOUT_S = 10.0
DEFAULT_PROMPT_TIMEOUT_S = 900.0  # 15 minutes


@dataclass
class ToolEvent:
    """Structured tool call from an ACP session.

    Captures the tool name, arguments, output, and status
    directly from ACP notifications — no text parsing needed.

    Attributes:
        tool_call_id: Unique ID for this tool invocation.
        tool_name: Tool name (e.g. "bash", "read", "edit").
        kind: Tool category (e.g. "execute", "read", "write").
        status: Final status ("pending", "in_progress", "completed").
        raw_input: Tool arguments as dict.
        raw_output: Tool results as dict (includes exit codes, etc).
        title: Human-readable title for the tool call.
    """

    tool_call_id: str = ""
    tool_name: str = ""
    kind: str = ""
    status: str = ""
    raw_input: dict = field(default_factory=dict)
    raw_output: dict = field(default_factory=dict)
    title: str = ""

    @property
    def exit_code(self) -> Optional[int]:
        """Extract bash exit code from raw_output metadata."""
        meta = self.raw_output.get("metadata", {})
        code = meta.get("exit")
        return code if isinstance(code, int) else None

    @property
    def output_text(self) -> str:
        """Extract text output from raw_output."""
        return self.raw_output.get("output", "")

    @property
    def file_path(self) -> str:
        """Extract file path from raw_input (for read/edit/write)."""
        return self.raw_input.get("filePath", "")


@dataclass
class AcpSessionResult:
    """Result from an ACP session prompt.

    Drop-in compatible with the data needed by ``_execute_opencode``
    while also providing structured tool call data.

    Attributes:
        text: Full text response from the agent.
        tool_events: Structured tool call events with args and results.
        tokens_in: Input tokens (from usage).
        tokens_cached: Cached read tokens.
        tokens_out: Output tokens.
        cost: Session cost in USD.
        context_used: Tokens used in context window.
        context_size: Total context window size.
        stop_reason: Why the agent stopped ("end_turn", etc).
        session_id: ACP session ID (for potential continuation).
        timed_out: Whether the prompt timed out.
    """

    text: str = ""
    tool_events: list[ToolEvent] = field(default_factory=list)
    tokens_in: int = 0
    tokens_cached: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    context_used: int = 0
    context_size: int = 0
    stop_reason: str = ""
    session_id: str = ""
    timed_out: bool = False

    @property
    def bash_events(self) -> list[ToolEvent]:
        """All bash tool calls."""
        return [e for e in self.tool_events if e.tool_name == "bash"]

    @property
    def edit_events(self) -> list[ToolEvent]:
        """All file edit/write tool calls."""
        return [
            e for e in self.tool_events
            if e.tool_name in ("edit", "write")
        ]

    @property
    def all_exit_codes(self) -> list[int]:
        """All bash exit codes from this session."""
        return [
            e.exit_code for e in self.bash_events
            if e.exit_code is not None
        ]


class AcpError(Exception):
    """Error from the ACP protocol layer."""


class AcpClient:
    """Persistent ACP client managing an opencode subprocess.

    Usage::

        client = AcpClient(cwd="/path/to/repo")
        client.start()

        result = client.prompt(
            text="Fix the bug in foo.py",
            mode="ralph-build",
            model="llamacpp/devstral",
        )

        print(result.text)
        for event in result.tool_events:
            print(f"{event.tool_name}: {event.raw_input}")

        client.stop()

    The client creates a fresh session per ``prompt()`` call for context
    isolation. The persistent process avoids the ~2.7s cold start penalty
    of ``opencode run``.
    """

    def __init__(self, cwd: str | Path) -> None:
        self._cwd = str(cwd)
        self._proc: Optional[subprocess.Popen] = None
        self._msg_id = 0
        self._lock = threading.Lock()
        self._initialized = False
        self._modes: list[str] = []
        self._models: list[dict] = []

    @property
    def is_alive(self) -> bool:
        """Check if the ACP process is running."""
        return self._proc is not None and self._proc.poll() is None

    @property
    def available_modes(self) -> list[str]:
        """Agent modes available after initialization."""
        return list(self._modes)

    def start(self) -> None:
        """Start the ACP subprocess and initialize the protocol.

        Raises:
            AcpError: If the process fails to start or initialize.
        """
        if self.is_alive:
            return

        env = os.environ.copy()
        env["XDG_STATE_HOME"] = "/tmp/ralph-opencode-state"
        env["OPENCODE_PERMISSION"] = json.dumps(
            {"external_directory": "deny", "doom_loop": "deny"}
        )

        try:
            self._proc = subprocess.Popen(
                ["opencode", "acp", "--cwd", self._cwd],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
            )
        except FileNotFoundError:
            raise AcpError("opencode not found on PATH")
        except OSError as exc:
            raise AcpError(f"Failed to start opencode acp: {exc}")

        # Wait briefly for process to start
        time.sleep(0.5)
        if not self.is_alive:
            stderr = ""
            if self._proc and self._proc.stderr:
                stderr = self._proc.stderr.read()
            raise AcpError(
                f"opencode acp exited immediately: {stderr}"
            )

        # Protocol initialization
        resp = self._request("initialize", {
            "protocolVersion": ACP_PROTOCOL_VERSION,
            "clientInfo": {"name": "ralph", "version": "0.1.0"},
            "capabilities": {},
        }, timeout=INIT_TIMEOUT_S)

        if "error" in resp:
            self.stop()
            raise AcpError(
                f"ACP initialize failed: {resp['error']}"
            )

        result = resp.get("result", {})
        caps = result.get("agentCapabilities", {})
        self._initialized = True

        logger.info(
            "ACP initialized: server=%s loadSession=%s",
            result.get("agentInfo", {}).get("name"),
            caps.get("loadSession"),
        )

        # Modes and models are returned by session/new, not initialize.
        # Create a throwaway session to discover them, then close it.
        probe = self._request("session/new", {
            "cwd": self._cwd,
            "mcpServers": [],
        }, timeout=SESSION_TIMEOUT_S)
        probe_result = probe.get("result", {})
        modes_state = probe_result.get("modes", {})
        self._modes = [
            m.get("id", "") for m in
            modes_state.get("availableModes", [])
        ]
        models_state = probe_result.get("models", {})
        self._models = models_state.get("availableModels", [])
        logger.info("ACP modes=%s models=%d", self._modes, len(self._models))

    def stop(self) -> None:
        """Stop the ACP subprocess gracefully."""
        if self._proc is None:
            return

        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except OSError:
            pass

        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=5)

        self._proc = None
        self._initialized = False

    def _ensure_alive(self) -> None:
        """Restart the process if it died."""
        if not self.is_alive:
            logger.warning("ACP process died, restarting...")
            self._initialized = False
            self.start()

    def prompt(
        self,
        text: str,
        mode: str = "",
        model: str = "",
        timeout_s: float = DEFAULT_PROMPT_TIMEOUT_S,
        print_output: bool = True,
    ) -> AcpSessionResult:
        """Send a prompt and collect the full response.

        Creates a fresh session for context isolation, optionally sets
        agent mode and model via session/set_mode and session/set_model,
        then sends the prompt and streams all notifications until the
        response completes.

        Args:
            text: Prompt text to send.
            mode: Agent mode/profile (e.g. "ralph-build").
            model: Model ID (e.g. "llamacpp/devstral").
            timeout_s: Max seconds to wait for response.
            print_output: Whether to print progress to stdout.

        Returns:
            AcpSessionResult with text, tool events, and metrics.

        Raises:
            AcpError: On protocol or process errors.
        """
        self._ensure_alive()

        # Create fresh session
        session_resp = self._request("session/new", {
            "cwd": self._cwd,
            "mcpServers": [],
        }, timeout=SESSION_TIMEOUT_S)

        if "error" in session_resp:
            raise AcpError(
                f"session/new failed: {session_resp['error']}"
            )

        new_result = session_resp.get("result", {})
        session_id = new_result.get("sessionId", "")
        if not session_id:
            raise AcpError("session/new returned no sessionId")

        # Set mode if requested
        if mode:
            mode_resp = self._request("session/set_mode", {
                "sessionId": session_id,
                "modeId": mode,
            }, timeout=SESSION_TIMEOUT_S)

            if "error" in mode_resp:
                logger.warning(
                    "session/set_mode failed for %s: %s",
                    mode, mode_resp["error"],
                )

        # Set model if requested (ACP uses session/set_model, not
        # a modelId field in the prompt request)
        if model:
            model_resp = self._request("session/set_model", {
                "sessionId": session_id,
                "modelId": model,
            }, timeout=SESSION_TIMEOUT_S)

            if "error" in model_resp:
                logger.warning(
                    "session/set_model failed for %s: %s",
                    model, model_resp["error"],
                )

        # Build prompt params
        prompt_params: dict = {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": text}],
        }

        # Send prompt and collect streaming response
        return self._stream_prompt(
            session_id, prompt_params, timeout_s, print_output,
        )

    def _stream_prompt(
        self,
        session_id: str,
        params: dict,
        timeout_s: float,
        print_output: bool,
    ) -> AcpSessionResult:
        """Send session/prompt and stream notifications until response.

        Processes three notification types:
        - tool_call / tool_call_update: structured tool events
        - agent_message_chunk: streaming text
        - usage_update: token/cost tracking
        """
        result = AcpSessionResult(session_id=session_id)
        text_chunks: list[str] = []
        tool_events: dict[str, ToolEvent] = {}  # by tool_call_id

        self._msg_id += 1
        msg_id = self._msg_id
        msg = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "session/prompt",
            "params": params,
        }

        self._send(msg)
        deadline = time.time() + timeout_s

        while time.time() < deadline:
            line = self._readline(timeout=1.0)
            if line is None:
                if not self.is_alive:
                    raise AcpError("ACP process died during prompt")
                continue

            parsed = self._parse_line(line)
            if parsed is None:
                continue

            # Check if this is our response
            if "id" in parsed and parsed["id"] == msg_id:
                if "error" in parsed:
                    raise AcpError(
                        f"session/prompt error: {parsed['error']}"
                    )
                # Extract usage from response
                resp_result = parsed.get("result", {})
                usage = resp_result.get("usage", {})
                result.tokens_in = usage.get("inputTokens", 0)
                result.tokens_cached = usage.get(
                    "cachedReadTokens", 0
                )
                result.tokens_out = usage.get("outputTokens", 0)
                result.stop_reason = resp_result.get(
                    "stopReason", ""
                )
                break

            # Process notification
            if "method" in parsed and parsed["method"] == "session/update":
                update = parsed.get("params", {}).get("update", {})
                self._process_update(
                    update, text_chunks, tool_events,
                    result, print_output,
                )
        else:
            # Timeout
            result.timed_out = True
            logger.warning(
                "ACP prompt timed out after %.0fs", timeout_s
            )

        result.text = "".join(text_chunks)
        result.tool_events = [
            e for e in tool_events.values()
            if e.status == "completed"
        ]
        return result

    def _process_update(
        self,
        update: dict,
        text_chunks: list[str],
        tool_events: dict[str, ToolEvent],
        result: AcpSessionResult,
        print_output: bool,
    ) -> None:
        """Process a single session/update notification."""
        update_type = update.get("sessionUpdate", "")

        if update_type == "agent_message_chunk":
            content = update.get("content", {})
            text = content.get("text", "")
            if text:
                text_chunks.append(text)
                if print_output:
                    sys.stdout.write(text)
                    sys.stdout.flush()

        elif update_type in ("tool_call", "tool_call_update"):
            tc_id = update.get("toolCallId", "")
            if tc_id not in tool_events:
                tool_events[tc_id] = ToolEvent(
                    tool_call_id=tc_id
                )
            event = tool_events[tc_id]
            event.status = update.get("status", event.status)
            event.kind = update.get("kind", event.kind)
            event.title = update.get("title", event.title)

            # tool_call has tool name in title for "pending"
            if update_type == "tool_call":
                event.tool_name = update.get("title", event.tool_name)

            raw_in = update.get("rawInput")
            if raw_in and isinstance(raw_in, dict) and raw_in:
                event.raw_input = raw_in

            raw_out = update.get("rawOutput")
            if raw_out and isinstance(raw_out, dict):
                event.raw_output = raw_out

            if print_output and event.status == "completed":
                self._print_tool_event(event)

        elif update_type == "usage_update":
            result.context_used = update.get("used", 0)
            result.context_size = update.get("size", 0)
            cost_info = update.get("cost", {})
            result.cost = cost_info.get("amount", 0.0)

    def _print_tool_event(self, event: ToolEvent) -> None:
        """Print a completed tool event in the same style as opencode."""
        from ralph.opencode import _format_tool_output
        output = event.output_text
        _format_tool_output(
            event.tool_name, event.raw_input,
            event.title, output,
        )

    # ─── Low-level JSON-RPC ───

    def _next_id(self) -> int:
        """Get next message ID (thread-safe)."""
        with self._lock:
            self._msg_id += 1
            return self._msg_id

    def _send(self, msg: dict) -> None:
        """Send a JSON-RPC message to the ACP process."""
        if not self._proc or not self._proc.stdin:
            raise AcpError("ACP process not running")
        try:
            line = json.dumps(msg) + "\n"
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise AcpError(f"Failed to write to ACP: {exc}")

    def _readline(self, timeout: float = 5.0) -> Optional[str]:
        """Read one line from stdout with timeout.

        Uses a simple blocking read. For real production use, this
        should use select/poll or a reader thread. Good enough for
        the current sequential prompt pattern.

        Returns:
            Line string, or None on timeout/EOF.
        """
        if not self._proc or not self._proc.stdout:
            return None

        # Simple blocking readline — timeout handled by caller loop
        # The 1s check interval means we detect timeouts within 1s
        line = self._proc.stdout.readline()
        if not line:
            return None
        return line.strip()

    def _parse_line(self, line: str) -> Optional[dict]:
        """Parse a JSON-RPC message, skipping non-JSON lines."""
        if not line.startswith("{"):
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def _request(
        self, method: str, params: dict, timeout: float = 30.0
    ) -> dict:
        """Send a request and wait for the response.

        Args:
            method: JSON-RPC method name.
            params: Request parameters.
            timeout: Max seconds to wait.

        Returns:
            Response dict with 'result' or 'error' key.
        """
        msg_id = self._next_id()
        msg = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        }
        self._send(msg)

        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self._readline(timeout=1.0)
            if line is None:
                if not self.is_alive:
                    return {
                        "error": {"message": "ACP process died"}
                    }
                continue
            parsed = self._parse_line(line)
            if parsed is None:
                continue
            # Match response by ID
            if parsed.get("id") == msg_id:
                return parsed
            # Skip notifications
        return {"error": {"message": f"Timeout waiting for {method}"}}
