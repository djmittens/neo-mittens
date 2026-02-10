"""Unit tests for ralph.acp — ACP client protocol layer.

Tests cover:
- ToolEvent property extraction (exit codes, file paths, output text)
- AcpSessionResult convenience properties
- AcpClient initialization and process lifecycle
- JSON-RPC message construction
- Notification parsing (tool_call, agent_message_chunk, usage_update)
- Error handling (process death, protocol errors, timeouts)
- Mode switching

All tests mock subprocess.Popen to avoid spawning real processes.
"""

import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from ralph.acp import (
    AcpClient,
    AcpError,
    AcpSessionResult,
    ToolEvent,
    ACP_PROTOCOL_VERSION,
)


# ─── ToolEvent tests ───


class TestToolEvent:
    """Tests for ToolEvent dataclass properties."""

    def test_exit_code_from_bash(self):
        """Exit code extracted from rawOutput metadata."""
        event = ToolEvent(
            tool_name="bash",
            raw_output={"metadata": {"exit": 0}},
        )
        assert event.exit_code == 0

    def test_exit_code_nonzero(self):
        """Non-zero exit code extracted correctly."""
        event = ToolEvent(
            tool_name="bash",
            raw_output={"metadata": {"exit": 1}},
        )
        assert event.exit_code == 1

    def test_exit_code_missing(self):
        """None when no exit code in metadata."""
        event = ToolEvent(tool_name="bash", raw_output={})
        assert event.exit_code is None

    def test_exit_code_no_metadata(self):
        """None when no metadata at all."""
        event = ToolEvent(tool_name="bash")
        assert event.exit_code is None

    def test_output_text(self):
        """Text output extracted from rawOutput."""
        event = ToolEvent(
            raw_output={"output": "hello world\n"},
        )
        assert event.output_text == "hello world\n"

    def test_output_text_empty(self):
        """Empty string when no output."""
        event = ToolEvent()
        assert event.output_text == ""

    def test_file_path_from_read(self):
        """File path extracted from rawInput."""
        event = ToolEvent(
            tool_name="read",
            raw_input={"filePath": "/tmp/foo.py"},
        )
        assert event.file_path == "/tmp/foo.py"

    def test_file_path_missing(self):
        """Empty string when no filePath."""
        event = ToolEvent(tool_name="bash", raw_input={})
        assert event.file_path == ""


# ─── AcpSessionResult tests ───


class TestAcpSessionResult:
    """Tests for AcpSessionResult convenience properties."""

    def test_bash_events(self):
        """Filter to bash tool events only."""
        result = AcpSessionResult(
            tool_events=[
                ToolEvent(tool_name="bash", status="completed"),
                ToolEvent(tool_name="read", status="completed"),
                ToolEvent(tool_name="bash", status="completed"),
            ]
        )
        assert len(result.bash_events) == 2

    def test_edit_events(self):
        """Filter to edit and write tool events."""
        result = AcpSessionResult(
            tool_events=[
                ToolEvent(tool_name="edit", status="completed"),
                ToolEvent(tool_name="write", status="completed"),
                ToolEvent(tool_name="read", status="completed"),
            ]
        )
        assert len(result.edit_events) == 2

    def test_all_exit_codes(self):
        """Collect exit codes from bash events."""
        result = AcpSessionResult(
            tool_events=[
                ToolEvent(
                    tool_name="bash", status="completed",
                    raw_output={"metadata": {"exit": 0}},
                ),
                ToolEvent(
                    tool_name="read", status="completed",
                ),
                ToolEvent(
                    tool_name="bash", status="completed",
                    raw_output={"metadata": {"exit": 1}},
                ),
            ]
        )
        assert result.all_exit_codes == [0, 1]

    def test_all_exit_codes_empty(self):
        """Empty list when no bash events."""
        result = AcpSessionResult()
        assert result.all_exit_codes == []


# ─── AcpClient._process_update tests ───


class TestProcessUpdate:
    """Tests for AcpClient._process_update notification handling."""

    def _make_client(self):
        """Create a client without starting it."""
        client = AcpClient.__new__(AcpClient)
        client._cwd = "/tmp"
        client._proc = None
        client._msg_id = 0
        client._lock = __import__("threading").Lock()
        client._initialized = False
        client._modes = []
        client._models = []
        return client

    def test_agent_message_chunk(self):
        """Text chunks accumulated from agent_message_chunk."""
        client = self._make_client()
        text_chunks: list[str] = []
        tool_events: dict = {}
        result = AcpSessionResult()

        client._process_update(
            {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "Hello "},
            },
            text_chunks, tool_events, result, False,
        )
        client._process_update(
            {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "world"},
            },
            text_chunks, tool_events, result, False,
        )

        assert text_chunks == ["Hello ", "world"]

    def test_tool_call_pending(self):
        """tool_call creates a new ToolEvent in pending state."""
        client = self._make_client()
        text_chunks: list[str] = []
        tool_events: dict = {}
        result = AcpSessionResult()

        client._process_update(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": "tc_1",
                "title": "bash",
                "kind": "execute",
                "status": "pending",
            },
            text_chunks, tool_events, result, False,
        )

        assert "tc_1" in tool_events
        assert tool_events["tc_1"].status == "pending"
        assert tool_events["tc_1"].tool_name == "bash"
        assert tool_events["tc_1"].kind == "execute"

    def test_tool_call_update_in_progress(self):
        """tool_call_update adds rawInput when in_progress."""
        client = self._make_client()
        text_chunks: list[str] = []
        tool_events: dict = {}
        result = AcpSessionResult()

        # First: pending
        client._process_update(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": "tc_1",
                "title": "bash",
                "kind": "execute",
                "status": "pending",
            },
            text_chunks, tool_events, result, False,
        )

        # Then: in_progress with args
        client._process_update(
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "tc_1",
                "status": "in_progress",
                "kind": "execute",
                "rawInput": {"command": "make build"},
            },
            text_chunks, tool_events, result, False,
        )

        assert tool_events["tc_1"].status == "in_progress"
        assert tool_events["tc_1"].raw_input == {"command": "make build"}

    def test_tool_call_update_completed(self):
        """tool_call_update adds rawOutput when completed."""
        client = self._make_client()
        text_chunks: list[str] = []
        tool_events: dict = {}
        result = AcpSessionResult()

        # Create event
        client._process_update(
            {
                "sessionUpdate": "tool_call",
                "toolCallId": "tc_1",
                "title": "bash",
                "kind": "execute",
                "status": "pending",
            },
            text_chunks, tool_events, result, False,
        )

        # Complete with output
        client._process_update(
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "tc_1",
                "status": "completed",
                "kind": "execute",
                "rawInput": {"command": "make build"},
                "rawOutput": {
                    "output": "Build succeeded\n",
                    "metadata": {"exit": 0, "truncated": False},
                },
            },
            text_chunks, tool_events, result, False,
        )

        event = tool_events["tc_1"]
        assert event.status == "completed"
        assert event.exit_code == 0
        assert event.output_text == "Build succeeded\n"

    def test_usage_update(self):
        """usage_update populates context tracking fields."""
        client = self._make_client()
        text_chunks: list[str] = []
        tool_events: dict = {}
        result = AcpSessionResult()

        client._process_update(
            {
                "sessionUpdate": "usage_update",
                "used": 15000,
                "size": 200000,
                "cost": {"amount": 0.05, "currency": "USD"},
            },
            text_chunks, tool_events, result, False,
        )

        assert result.context_used == 15000
        assert result.context_size == 200000
        assert result.cost == 0.05

    def test_unknown_update_type_ignored(self):
        """Unknown sessionUpdate types are silently ignored."""
        client = self._make_client()
        text_chunks: list[str] = []
        tool_events: dict = {}
        result = AcpSessionResult()

        # Should not raise
        client._process_update(
            {"sessionUpdate": "unknown_type", "data": "foo"},
            text_chunks, tool_events, result, False,
        )

        assert text_chunks == []
        assert tool_events == {}


# ─── AcpClient._parse_line tests ───


class TestParseLine:
    """Tests for JSON line parsing."""

    def _make_client(self):
        client = AcpClient.__new__(AcpClient)
        client._cwd = "/tmp"
        return client

    def test_valid_json(self):
        """Valid JSON parsed correctly."""
        client = self._make_client()
        result = client._parse_line('{"id": 1, "result": {}}')
        assert result == {"id": 1, "result": {}}

    def test_non_json_line_skipped(self):
        """Non-JSON lines return None."""
        client = self._make_client()
        assert client._parse_line("[opencode-lmstudio] init") is None

    def test_invalid_json_skipped(self):
        """Invalid JSON returns None."""
        client = self._make_client()
        assert client._parse_line("{bad json}") is None

    def test_empty_line_skipped(self):
        """Empty line returns None."""
        client = self._make_client()
        assert client._parse_line("") is None


# ─── AcpClient lifecycle tests ───


class TestAcpClientLifecycle:
    """Tests for AcpClient start/stop and process management."""

    @patch("ralph.acp.subprocess.Popen")
    @patch("ralph.acp.time.sleep")
    def test_start_sends_initialize(self, mock_sleep, mock_popen):
        """start() sends initialize with correct protocol version."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Process alive
        mock_proc.stdin = MagicMock()

        # start() sends initialize (id=1) then probes session/new (id=2)
        init_response = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "agentCapabilities": {"loadSession": True},
                "agentInfo": {"name": "OpenCode", "version": "1.1.53"},
            },
        })
        probe_response = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "sessionId": "probe",
                "modes": {"availableModes": [
                    {"id": "build", "name": "build"},
                    {"id": "ralph-build", "name": "ralph-build"},
                ]},
            },
        })
        mock_proc.stdout.readline.side_effect = [
            init_response, probe_response,
        ]

        mock_popen.return_value = mock_proc

        client = AcpClient("/tmp")
        client.start()

        # Verify Popen was called with correct args
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert cmd == ["opencode", "acp", "--cwd", "/tmp"]

        # Verify initialize message was sent
        write_calls = mock_proc.stdin.write.call_args_list
        assert len(write_calls) >= 1
        sent = json.loads(write_calls[0][0][0].strip())
        assert sent["method"] == "initialize"
        assert sent["params"]["protocolVersion"] == ACP_PROTOCOL_VERSION

        # Verify modes were discovered from session/new probe
        assert "build" in client.available_modes
        assert "ralph-build" in client.available_modes

        client.stop()

    @patch("ralph.acp.subprocess.Popen")
    def test_start_fails_when_opencode_missing(self, mock_popen):
        """start() raises AcpError when opencode not found."""
        mock_popen.side_effect = FileNotFoundError("not found")

        client = AcpClient("/tmp")
        with pytest.raises(AcpError, match="opencode not found"):
            client.start()

    @patch("ralph.acp.subprocess.Popen")
    @patch("ralph.acp.time.sleep")
    def test_start_fails_on_immediate_exit(self, mock_sleep, mock_popen):
        """start() raises AcpError when process exits immediately."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Exited
        mock_proc.stderr.read.return_value = "some error"
        mock_popen.return_value = mock_proc

        client = AcpClient("/tmp")
        with pytest.raises(AcpError, match="exited immediately"):
            client.start()

    def test_is_alive_no_process(self):
        """is_alive returns False when no process."""
        client = AcpClient("/tmp")
        assert not client.is_alive

    @patch("ralph.acp.subprocess.Popen")
    @patch("ralph.acp.time.sleep")
    def test_stop_kills_stuck_process(self, mock_sleep, mock_popen):
        """stop() kills process that won't exit gracefully."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired("opencode", 5),
            None,  # After kill
        ]

        mock_proc.stdout.readline.side_effect = [
            json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "result": {"protocolVersion": 1, "agentCapabilities": {}},
            }),
            json.dumps({
                "jsonrpc": "2.0", "id": 2,
                "result": {"sessionId": "probe", "modes": {}},
            }),
        ]
        mock_popen.return_value = mock_proc

        client = AcpClient("/tmp")
        client.start()
        client.stop()

        mock_proc.kill.assert_called_once()

    def test_is_alive_with_dead_process(self):
        """is_alive returns False when process has exited."""
        client = AcpClient("/tmp")
        mock_proc = MagicMock()
        mock_proc.poll.return_value = -15
        client._proc = mock_proc
        assert not client.is_alive


# ─── AcpClient._request tests ───


class TestAcpClientRequest:
    """Tests for low-level JSON-RPC request/response."""

    def _make_started_client(self):
        """Create a client with mocked process."""
        client = AcpClient.__new__(AcpClient)
        client._cwd = "/tmp"
        client._msg_id = 0
        client._lock = __import__("threading").Lock()
        client._initialized = True
        client._modes = []
        client._models = []
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        client._proc.stdin = MagicMock()
        return client

    def test_request_matches_response_by_id(self):
        """_request returns response matching the message ID."""
        client = self._make_started_client()
        response = json.dumps({
            "jsonrpc": "2.0", "id": 1, "result": {"ok": True}
        })
        client._proc.stdout.readline.return_value = response

        result = client._request("test/method", {"foo": "bar"}, timeout=5)
        assert result.get("result", {}).get("ok") is True

    def test_request_skips_non_json_lines(self):
        """_request skips plugin output lines before finding response."""
        client = self._make_started_client()
        client._proc.stdout.readline.side_effect = [
            "[opencode-lmstudio] init",
            "[opencode-lmstudio] loaded",
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}),
        ]

        result = client._request("test", {}, timeout=5)
        assert result.get("result", {}).get("ok") is True

    def test_request_skips_notifications(self):
        """_request skips notifications (no id) before finding response."""
        client = self._make_started_client()
        notification = json.dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"update": {"sessionUpdate": "agent_message_chunk"}},
        })
        response = json.dumps({
            "jsonrpc": "2.0", "id": 1, "result": {"ok": True}
        })
        client._proc.stdout.readline.side_effect = [
            notification, response,
        ]

        result = client._request("test", {}, timeout=5)
        assert result.get("result", {}).get("ok") is True

    def test_request_returns_error_on_process_death(self):
        """_request returns error dict when process dies mid-request."""
        client = self._make_started_client()
        client._proc.poll.return_value = -15  # Dead
        client._proc.stdout.readline.return_value = ""

        result = client._request("test", {}, timeout=2)
        assert "error" in result
        assert "died" in result["error"]["message"]


# ─── AcpClient.prompt model/mode tests ───


class TestAcpClientPrompt:
    """Tests for session/set_mode and session/set_model in prompt()."""

    def _make_started_client(self):
        """Create a client with mocked process ready for prompt()."""
        client = AcpClient.__new__(AcpClient)
        client._cwd = "/tmp"
        client._msg_id = 0
        client._lock = __import__("threading").Lock()
        client._initialized = True
        client._modes = []
        client._models = []
        client._proc = MagicMock()
        client._proc.poll.return_value = None
        client._proc.stdin = MagicMock()
        client.timer = None
        return client

    def test_prompt_calls_set_model(self):
        """prompt() calls session/set_model when model is provided."""
        client = self._make_started_client()

        # Track all requests sent
        sent_messages = []

        def capture_write(line):
            try:
                sent_messages.append(json.loads(line.strip()))
            except (json.JSONDecodeError, TypeError):
                pass

        client._proc.stdin.write.side_effect = capture_write

        # Responses: session/new, set_mode, set_model, then prompt
        responses = [
            json.dumps({"jsonrpc": "2.0", "id": i + 1, "result": r})
            for i, r in enumerate([
                {"sessionId": "s1"},                    # session/new
                {},                                      # set_mode
                {},                                      # set_model
                {"stopReason": "end_turn"},              # session/prompt
            ])
        ]
        client._proc.stdout.readline.side_effect = responses

        result = client.prompt(
            text="test", mode="ralph-build",
            model="llamacpp/devstral", timeout_s=5,
            print_output=False,
        )

        # Verify session/set_model was called
        methods = [m.get("method") for m in sent_messages]
        assert "session/set_model" in methods, (
            f"session/set_model not called, sent: {methods}"
        )

        # Find the set_model message and verify params
        set_model_msg = next(
            m for m in sent_messages
            if m.get("method") == "session/set_model"
        )
        assert set_model_msg["params"]["sessionId"] == "s1"
        assert set_model_msg["params"]["modelId"] == "llamacpp/devstral"

    def test_prompt_skips_set_model_when_empty(self):
        """prompt() does not call session/set_model when model is empty."""
        client = self._make_started_client()

        sent_messages = []

        def capture_write(line):
            try:
                sent_messages.append(json.loads(line.strip()))
            except (json.JSONDecodeError, TypeError):
                pass

        client._proc.stdin.write.side_effect = capture_write

        # Responses: session/new, then prompt (no set_mode/set_model)
        responses = [
            json.dumps({"jsonrpc": "2.0", "id": i + 1, "result": r})
            for i, r in enumerate([
                {"sessionId": "s1"},                    # session/new
                {"stopReason": "end_turn"},              # session/prompt
            ])
        ]
        client._proc.stdout.readline.side_effect = responses

        result = client.prompt(
            text="test", mode="", model="",
            timeout_s=5, print_output=False,
        )

        methods = [m.get("method") for m in sent_messages]
        assert "session/set_model" not in methods
        assert "session/set_mode" not in methods

    def test_prompt_no_model_id_in_prompt_params(self):
        """prompt() does not pass modelId in session/prompt params."""
        client = self._make_started_client()

        sent_messages = []

        def capture_write(line):
            try:
                sent_messages.append(json.loads(line.strip()))
            except (json.JSONDecodeError, TypeError):
                pass

        client._proc.stdin.write.side_effect = capture_write

        responses = [
            json.dumps({"jsonrpc": "2.0", "id": i + 1, "result": r})
            for i, r in enumerate([
                {"sessionId": "s1"},                    # session/new
                {},                                      # set_model
                {"stopReason": "end_turn"},              # session/prompt
            ])
        ]
        client._proc.stdout.readline.side_effect = responses

        result = client.prompt(
            text="test", model="llamacpp/devstral",
            timeout_s=5, print_output=False,
        )

        # Find the session/prompt message
        prompt_msg = next(
            m for m in sent_messages
            if m.get("method") == "session/prompt"
        )
        assert "modelId" not in prompt_msg.get("params", {}), (
            "modelId should not be in session/prompt params"
        )


# ─── Environment setup tests ───


class TestAcpEnvironment:
    """Tests for ACP subprocess environment configuration."""

    def _make_start_responses(self):
        """Responses for start(): initialize + session/new probe."""
        return [
            json.dumps({
                "jsonrpc": "2.0", "id": 1,
                "result": {"protocolVersion": 1, "agentCapabilities": {}},
            }),
            json.dumps({
                "jsonrpc": "2.0", "id": 2,
                "result": {"sessionId": "probe", "modes": {}},
            }),
        ]

    @patch("ralph.acp.subprocess.Popen")
    @patch("ralph.acp.time.sleep")
    def test_xdg_state_home_set(self, mock_sleep, mock_popen):
        """XDG_STATE_HOME set to /tmp/ralph-opencode-state."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdout.readline.side_effect = self._make_start_responses()
        mock_popen.return_value = mock_proc

        client = AcpClient("/tmp")
        client.start()

        env = mock_popen.call_args[1]["env"]
        assert env["XDG_STATE_HOME"] == "/tmp/ralph-opencode-state"

        client.stop()

    @patch("ralph.acp.subprocess.Popen")
    @patch("ralph.acp.time.sleep")
    def test_permission_env_set(self, mock_sleep, mock_popen):
        """OPENCODE_PERMISSION set with deny policies."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdout.readline.side_effect = self._make_start_responses()
        mock_popen.return_value = mock_proc

        client = AcpClient("/tmp")
        client.start()

        env = mock_popen.call_args[1]["env"]
        perms = json.loads(env["OPENCODE_PERMISSION"])
        assert perms["external_directory"] == "deny"
        assert perms["doom_loop"] == "deny"

        client.stop()


import subprocess
