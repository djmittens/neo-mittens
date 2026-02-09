"""Unit tests for ralph.opencode — command construction and agent plumbing."""

from pathlib import Path
from unittest.mock import patch, MagicMock

from ralph.opencode import spawn_opencode, spawn_opencode_continue


class TestSpawnOpencode:
    """Tests for spawn_opencode command construction."""

    @patch("ralph.opencode.subprocess.Popen")
    def test_basic_command(self, mock_popen):
        """Test basic command without model or agent."""
        spawn_opencode("hello", Path("/tmp"), 60000)
        cmd = mock_popen.call_args[0][0]
        assert cmd == ["opencode", "run", "--format", "json", "hello"]

    @patch("ralph.opencode.subprocess.Popen")
    def test_with_model(self, mock_popen):
        """Test command includes --model when specified."""
        spawn_opencode("hello", Path("/tmp"), 60000, model="opus")
        cmd = mock_popen.call_args[0][0]
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "opus"

    @patch("ralph.opencode.subprocess.Popen")
    def test_with_agent(self, mock_popen):
        """Test command includes --agent when specified."""
        spawn_opencode("hello", Path("/tmp"), 60000, agent="ralph-build")
        cmd = mock_popen.call_args[0][0]
        assert "--agent" in cmd
        assert cmd[cmd.index("--agent") + 1] == "ralph-build"

    @patch("ralph.opencode.subprocess.Popen")
    def test_with_model_and_agent(self, mock_popen):
        """Test command includes both --model and --agent."""
        spawn_opencode(
            "hello", Path("/tmp"), 60000,
            model="devstral", agent="ralph-verify",
        )
        cmd = mock_popen.call_args[0][0]
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "devstral"
        assert "--agent" in cmd
        assert cmd[cmd.index("--agent") + 1] == "ralph-verify"

    @patch("ralph.opencode.subprocess.Popen")
    def test_no_agent_when_none(self, mock_popen):
        """Test --agent omitted when agent is None."""
        spawn_opencode("hello", Path("/tmp"), 60000, agent=None)
        cmd = mock_popen.call_args[0][0]
        assert "--agent" not in cmd

    @patch("ralph.opencode.subprocess.Popen")
    def test_no_agent_when_empty(self, mock_popen):
        """Test --agent omitted when agent is empty string."""
        spawn_opencode("hello", Path("/tmp"), 60000, agent="")
        cmd = mock_popen.call_args[0][0]
        assert "--agent" not in cmd


class TestSpawnOpencodeContinue:
    """Tests for spawn_opencode_continue command construction."""

    @patch("ralph.opencode.subprocess.Popen")
    def test_basic_continue(self, mock_popen):
        """Test basic session continue command."""
        spawn_opencode_continue("ses_123", "follow up", Path("/tmp"))
        cmd = mock_popen.call_args[0][0]
        assert cmd == [
            "opencode", "run", "--format", "json",
            "-s", "ses_123", "follow up",
        ]

    @patch("ralph.opencode.subprocess.Popen")
    def test_continue_with_agent(self, mock_popen):
        """Test session continue includes --agent."""
        spawn_opencode_continue(
            "ses_123", "follow up", Path("/tmp"),
            agent="ralph-verify",
        )
        cmd = mock_popen.call_args[0][0]
        assert "--agent" in cmd
        assert cmd[cmd.index("--agent") + 1] == "ralph-verify"

    @patch("ralph.opencode.subprocess.Popen")
    def test_continue_with_model_and_agent(self, mock_popen):
        """Test session continue with both model and agent."""
        spawn_opencode_continue(
            "ses_123", "follow up", Path("/tmp"),
            model="devstral", agent="ralph-build",
        )
        cmd = mock_popen.call_args[0][0]
        assert "--model" in cmd
        assert "--agent" in cmd
        assert "-s" in cmd
