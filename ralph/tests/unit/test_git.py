"""Unit tests for ralph.git module - git operations with mocked commands."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from ralph.git import (
    get_current_branch,
    get_current_commit,
    git_add,
    git_commit,
    has_uncommitted_plan,
    push_with_retry,
    sync_with_remote,
)


class TestGetCurrentCommit:
    """Tests for get_current_commit function."""

    @patch("ralph.git.subprocess.run")
    def test_returns_commit_hash(self, mock_run: MagicMock) -> None:
        """Test successful commit hash retrieval."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="abc123d\n",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = get_current_commit(Path(tmpdir))
            assert result == "abc123d"

    @patch("ralph.git.subprocess.run")
    def test_returns_unknown_on_error(self, mock_run: MagicMock) -> None:
        """Test returns 'unknown' when git command fails."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = get_current_commit(Path(tmpdir))
            assert result == "unknown"

    @patch("ralph.git.subprocess.run")
    def test_uses_correct_git_command(self, mock_run: MagicMock) -> None:
        """Test that correct git command is used."""
        mock_run.return_value = MagicMock(returncode=0, stdout="abc")
        with tempfile.TemporaryDirectory() as tmpdir:
            get_current_commit(Path(tmpdir))
            args = mock_run.call_args[0][0]
            assert args == ["git", "rev-parse", "--short", "HEAD"]


class TestHasUncommittedPlan:
    """Tests for has_uncommitted_plan function."""

    def test_nonexistent_file_returns_false(self) -> None:
        """Test that nonexistent file returns False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = has_uncommitted_plan(
                Path(tmpdir),
                Path(tmpdir) / "nonexistent.jsonl",
            )
            assert result is False

    @patch("ralph.git.subprocess.run")
    def test_clean_file_returns_false(self, mock_run: MagicMock) -> None:
        """Test that clean file returns False."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_file = Path(tmpdir) / "plan.jsonl"
            plan_file.write_text("{}")
            result = has_uncommitted_plan(Path(tmpdir), plan_file)
            assert result is False

    @patch("ralph.git.subprocess.run")
    def test_modified_file_returns_true(self, mock_run: MagicMock) -> None:
        """Test that modified file returns True."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=" M ralph/plan.jsonl\n",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_file = Path(tmpdir) / "plan.jsonl"
            plan_file.write_text("{}")
            result = has_uncommitted_plan(Path(tmpdir), plan_file)
            assert result is True

    @patch("ralph.git.subprocess.run")
    def test_staged_file_returns_true(self, mock_run: MagicMock) -> None:
        """Test that staged file returns True."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="M  ralph/plan.jsonl\n",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_file = Path(tmpdir) / "plan.jsonl"
            plan_file.write_text("{}")
            result = has_uncommitted_plan(Path(tmpdir), plan_file)
            assert result is True


class TestSyncWithRemote:
    """Tests for sync_with_remote function."""

    @patch("ralph.git.subprocess.run")
    def test_returns_error_on_fetch_failure(self, mock_run: MagicMock) -> None:
        """Test returns 'error' when fetch fails."""
        mock_run.return_value = MagicMock(returncode=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = sync_with_remote(Path(tmpdir), "main", quiet=True)
            assert result == "error"

    @patch("ralph.git.subprocess.run")
    def test_returns_current_when_up_to_date(self, mock_run: MagicMock) -> None:
        """Test returns 'current' when already up to date."""

        def run_side_effect(args, **kwargs):
            if args[1] == "fetch":
                return MagicMock(returncode=0)
            elif args[1] == "status":
                return MagicMock(returncode=0, stdout="Your branch is up to date")
            return MagicMock(returncode=0)

        mock_run.side_effect = run_side_effect
        with tempfile.TemporaryDirectory() as tmpdir:
            result = sync_with_remote(Path(tmpdir), "main", quiet=True)
            assert result == "current"

    @patch("ralph.git.subprocess.run")
    def test_returns_updated_on_successful_rebase(self, mock_run: MagicMock) -> None:
        """Test returns 'updated' on successful rebase."""

        def run_side_effect(args, **kwargs):
            if args[1] == "fetch":
                return MagicMock(returncode=0)
            elif args[1] == "status":
                return MagicMock(returncode=0, stdout="Your branch is behind")
            elif args[1] == "rebase":
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0)

        mock_run.side_effect = run_side_effect
        with tempfile.TemporaryDirectory() as tmpdir:
            result = sync_with_remote(Path(tmpdir), "main", quiet=True)
            assert result == "updated"

    @patch("ralph.git.subprocess.run")
    def test_returns_conflict_on_rebase_conflict(self, mock_run: MagicMock) -> None:
        """Test returns 'conflict' on rebase conflict."""

        def run_side_effect(args, **kwargs):
            if args[1] == "fetch":
                return MagicMock(returncode=0)
            elif args[1] == "status":
                return MagicMock(returncode=0, stdout="Your branch is behind")
            elif args[1] == "rebase":
                if len(args) > 2 and args[2] == "--abort":
                    return MagicMock(returncode=0)
                return MagicMock(returncode=1, stdout="CONFLICT", stderr="")
            return MagicMock(returncode=0)

        mock_run.side_effect = run_side_effect
        with tempfile.TemporaryDirectory() as tmpdir:
            result = sync_with_remote(Path(tmpdir), "main", quiet=True)
            assert result == "conflict"

    @patch("ralph.git.subprocess.run")
    def test_returns_error_on_other_rebase_failure(self, mock_run: MagicMock) -> None:
        """Test returns 'error' on other rebase failure."""

        def run_side_effect(args, **kwargs):
            if args[1] == "fetch":
                return MagicMock(returncode=0)
            elif args[1] == "status":
                return MagicMock(returncode=0, stdout="Your branch is behind")
            elif args[1] == "rebase":
                if len(args) > 2 and args[2] == "--abort":
                    return MagicMock(returncode=0)
                return MagicMock(returncode=1, stdout="", stderr="other error")
            return MagicMock(returncode=0)

        mock_run.side_effect = run_side_effect
        with tempfile.TemporaryDirectory() as tmpdir:
            result = sync_with_remote(Path(tmpdir), "main", quiet=True)
            assert result == "error"

    @patch("ralph.git.subprocess.run")
    def test_handles_diverged_branches(self, mock_run: MagicMock) -> None:
        """Test handles diverged branches."""

        def run_side_effect(args, **kwargs):
            if args[1] == "fetch":
                return MagicMock(returncode=0)
            elif args[1] == "status":
                return MagicMock(returncode=0, stdout="have diverged")
            elif args[1] == "rebase":
                return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0)

        mock_run.side_effect = run_side_effect
        with tempfile.TemporaryDirectory() as tmpdir:
            result = sync_with_remote(Path(tmpdir), "main", quiet=True)
            assert result == "updated"


class TestPushWithRetry:
    """Tests for push_with_retry function."""

    @patch("ralph.git.subprocess.run")
    def test_successful_push_returns_true(self, mock_run: MagicMock) -> None:
        """Test successful push returns True."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = push_with_retry(Path(tmpdir), "main", quiet=True)
            assert result is True

    @patch("ralph.git.subprocess.run")
    def test_non_rejection_failure_returns_false(self, mock_run: MagicMock) -> None:
        """Test non-rejection failure returns False."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="fatal: remote error",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = push_with_retry(Path(tmpdir), "main", quiet=True)
            assert result is False

    @patch("ralph.git.sync_with_remote")
    @patch("ralph.git.subprocess.run")
    def test_retries_on_rejection(
        self, mock_run: MagicMock, mock_sync: MagicMock
    ) -> None:
        """Test retries on push rejection."""
        push_results = [
            MagicMock(returncode=1, stderr="rejected"),
            MagicMock(returncode=0),
        ]
        mock_run.side_effect = push_results
        mock_sync.return_value = "updated"

        with tempfile.TemporaryDirectory() as tmpdir:
            result = push_with_retry(Path(tmpdir), "main", quiet=True)
            assert result is True
            assert mock_run.call_count == 2

    @patch("ralph.git.sync_with_remote")
    @patch("ralph.git.subprocess.run")
    def test_fails_after_max_retries(
        self, mock_run: MagicMock, mock_sync: MagicMock
    ) -> None:
        """Test fails after max retries."""
        mock_run.return_value = MagicMock(returncode=1, stderr="rejected")
        mock_sync.return_value = "updated"

        with tempfile.TemporaryDirectory() as tmpdir:
            result = push_with_retry(Path(tmpdir), "main", max_retries=3, quiet=True)
            assert result is False
            assert mock_run.call_count == 3

    @patch("ralph.git.sync_with_remote")
    @patch("ralph.git.subprocess.run")
    def test_fails_on_sync_conflict(
        self, mock_run: MagicMock, mock_sync: MagicMock
    ) -> None:
        """Test fails when sync returns conflict."""
        mock_run.return_value = MagicMock(returncode=1, stderr="rejected")
        mock_sync.return_value = "conflict"

        with tempfile.TemporaryDirectory() as tmpdir:
            result = push_with_retry(Path(tmpdir), "main", quiet=True)
            assert result is False

    @patch("ralph.git.sync_with_remote")
    @patch("ralph.git.subprocess.run")
    def test_handles_non_fast_forward(
        self, mock_run: MagicMock, mock_sync: MagicMock
    ) -> None:
        """Test handles non-fast-forward error."""
        push_results = [
            MagicMock(returncode=1, stderr="non-fast-forward"),
            MagicMock(returncode=0),
        ]
        mock_run.side_effect = push_results
        mock_sync.return_value = "updated"

        with tempfile.TemporaryDirectory() as tmpdir:
            result = push_with_retry(Path(tmpdir), "main", quiet=True)
            assert result is True


class TestGetCurrentBranch:
    """Tests for get_current_branch function."""

    @patch("ralph.git.subprocess.run")
    def test_returns_branch_name(self, mock_run: MagicMock) -> None:
        """Test successful branch name retrieval."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="feature/test-branch\n",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = get_current_branch(Path(tmpdir))
            assert result == "feature/test-branch"

    @patch("ralph.git.subprocess.run")
    def test_returns_none_on_error(self, mock_run: MagicMock) -> None:
        """Test returns None when git command fails."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = get_current_branch(Path(tmpdir))
            assert result is None

    @patch("ralph.git.subprocess.run")
    def test_returns_none_on_empty_output(self, mock_run: MagicMock) -> None:
        """Test returns None on empty output (detached HEAD)."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            result = get_current_branch(Path(tmpdir))
            assert result is None

    @patch("ralph.git.subprocess.run")
    def test_uses_correct_git_command(self, mock_run: MagicMock) -> None:
        """Test that correct git command is used."""
        mock_run.return_value = MagicMock(returncode=0, stdout="main")
        with tempfile.TemporaryDirectory() as tmpdir:
            get_current_branch(Path(tmpdir))
            args = mock_run.call_args[0][0]
            assert args == ["git", "branch", "--show-current"]


class TestGitAdd:
    """Tests for git_add function."""

    @patch("ralph.git.subprocess.run")
    def test_returns_true_on_success(self, mock_run: MagicMock) -> None:
        """Test returns True on successful add."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = git_add(Path(tmpdir), Path(tmpdir) / "file.txt")
            assert result is True

    @patch("ralph.git.subprocess.run")
    def test_returns_false_on_failure(self, mock_run: MagicMock) -> None:
        """Test returns False on failed add."""
        mock_run.return_value = MagicMock(returncode=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = git_add(Path(tmpdir), Path(tmpdir) / "file.txt")
            assert result is False

    def test_returns_true_with_no_paths(self) -> None:
        """Test returns True when no paths provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = git_add(Path(tmpdir))
            assert result is True

    @patch("ralph.git.subprocess.run")
    def test_handles_multiple_paths(self, mock_run: MagicMock) -> None:
        """Test handles multiple paths."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            git_add(
                Path(tmpdir),
                Path(tmpdir) / "file1.txt",
                Path(tmpdir) / "file2.txt",
            )
            args = mock_run.call_args[0][0]
            assert args[0:2] == ["git", "add"]
            assert len(args) == 4


class TestGitCommit:
    """Tests for git_commit function."""

    @patch("ralph.git.subprocess.run")
    def test_returns_true_on_success(self, mock_run: MagicMock) -> None:
        """Test returns True on successful commit."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = git_commit(Path(tmpdir), "Test commit message")
            assert result is True

    @patch("ralph.git.subprocess.run")
    def test_returns_false_on_failure(self, mock_run: MagicMock) -> None:
        """Test returns False on failed commit."""
        mock_run.return_value = MagicMock(returncode=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = git_commit(Path(tmpdir), "Test commit message")
            assert result is False

    @patch("ralph.git.subprocess.run")
    def test_uses_correct_command(self, mock_run: MagicMock) -> None:
        """Test uses correct git command."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            git_commit(Path(tmpdir), "My message")
            args = mock_run.call_args[0][0]
            assert args == ["git", "commit", "-m", "My message"]

    @patch("ralph.git.subprocess.run")
    def test_handles_special_characters_in_message(self, mock_run: MagicMock) -> None:
        """Test handles special characters in commit message."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            message = "Fix bug: handle 'quotes' and \"double quotes\""
            git_commit(Path(tmpdir), message)
            args = mock_run.call_args[0][0]
            assert args[3] == message
