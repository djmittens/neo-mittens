"""Unit tests for ralph.git module."""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from ralph.git import (
    get_current_commit,
    get_current_branch,
    has_uncommitted_plan,
    sync_with_remote,
    push_with_retry,
)


class TestGetCurrentCommit:
    """Tests for get_current_commit function."""

    @patch("ralph.git.subprocess.run")
    def test_get_current_commit_success(self, mock_run):
        """Test getting current commit hash on success."""
        mock_run.return_value = MagicMock(returncode=0, stdout="abc1234\n")
        result = get_current_commit()
        assert result == "abc1234"
        mock_run.assert_called_once_with(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=None,
        )

    @patch("ralph.git.subprocess.run")
    def test_get_current_commit_failure(self, mock_run):
        """Test getting current commit returns 'unknown' on failure."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = get_current_commit()
        assert result == "unknown"

    @patch("ralph.git.subprocess.run")
    def test_get_current_commit_with_cwd(self, mock_run):
        """Test get_current_commit respects cwd parameter."""
        mock_run.return_value = MagicMock(returncode=0, stdout="def5678\n")
        cwd = Path("/some/path")
        result = get_current_commit(cwd=cwd)
        assert result == "def5678"
        mock_run.assert_called_once_with(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=cwd,
        )


class TestGetCurrentBranch:
    """Tests for get_current_branch function."""

    @patch("ralph.git.subprocess.run")
    def test_get_current_branch_success(self, mock_run):
        """Test getting current branch name on success."""
        mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
        result = get_current_branch()
        assert result == "main"

    @patch("ralph.git.subprocess.run")
    def test_get_current_branch_failure(self, mock_run):
        """Test getting current branch returns 'unknown' on failure."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        result = get_current_branch()
        assert result == "unknown"


class TestHasUncommittedPlan:
    """Tests for has_uncommitted_plan function."""

    @patch("ralph.git.subprocess.run")
    def test_has_uncommitted_plan_no_changes(self, mock_run, tmp_path):
        """Test returns False when no uncommitted changes."""
        plan_file = tmp_path / "plan.jsonl"
        plan_file.write_text("{}")
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = has_uncommitted_plan(plan_file)
        assert result is False

    @patch("ralph.git.subprocess.run")
    def test_has_uncommitted_plan_with_changes(self, mock_run, tmp_path):
        """Test returns True when uncommitted changes exist."""
        plan_file = tmp_path / "plan.jsonl"
        plan_file.write_text("{}")
        mock_run.return_value = MagicMock(returncode=0, stdout=" M plan.jsonl\n")
        result = has_uncommitted_plan(plan_file)
        assert result is True

    def test_has_uncommitted_plan_file_not_exists(self, tmp_path):
        """Test returns False when plan file doesn't exist."""
        plan_file = tmp_path / "nonexistent.jsonl"
        result = has_uncommitted_plan(plan_file)
        assert result is False

    @patch("ralph.git.subprocess.run")
    def test_has_uncommitted_plan_with_cwd(self, mock_run, tmp_path):
        """Test has_uncommitted_plan respects cwd parameter."""
        plan_file = tmp_path / "plan.jsonl"
        plan_file.write_text("{}")
        cwd = Path("/custom/path")
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        has_uncommitted_plan(plan_file, cwd=cwd)
        mock_run.assert_called_once_with(
            ["git", "status", "--porcelain", str(plan_file)],
            capture_output=True,
            text=True,
            cwd=cwd,
        )


class TestSyncWithRemote:
    """Tests for sync_with_remote function."""

    @patch("ralph.git.subprocess.run")
    @patch("ralph.git.get_current_branch")
    def test_sync_with_remote_already_current(self, mock_branch, mock_run):
        """Test sync returns 'current' when already up to date."""
        mock_branch.return_value = "main"
        mock_run.side_effect = [
            MagicMock(returncode=0),  # fetch
            MagicMock(returncode=0, stdout="Your branch is up to date"),  # status
        ]
        result = sync_with_remote()
        assert result == "current"

    @patch("ralph.git.subprocess.run")
    @patch("ralph.git.get_current_branch")
    def test_sync_with_remote_updated(self, mock_branch, mock_run):
        """Test sync returns 'updated' after successful rebase."""
        mock_branch.return_value = "main"
        mock_run.side_effect = [
            MagicMock(returncode=0),  # fetch
            MagicMock(returncode=0, stdout="Your branch is behind"),  # status
            MagicMock(returncode=0),  # rebase
        ]
        result = sync_with_remote()
        assert result == "updated"

    @patch("ralph.git.subprocess.run")
    @patch("ralph.git.get_current_branch")
    def test_sync_with_remote_fetch_error(self, mock_branch, mock_run):
        """Test sync returns 'error' when fetch fails."""
        mock_branch.return_value = "main"
        mock_run.return_value = MagicMock(returncode=1)  # fetch fails
        result = sync_with_remote()
        assert result == "error"

    @patch("ralph.git.subprocess.run")
    @patch("ralph.git.get_current_branch")
    def test_sync_with_remote_conflict(self, mock_branch, mock_run):
        """Test sync returns 'conflict' on rebase conflict."""
        mock_branch.return_value = "main"
        mock_run.side_effect = [
            MagicMock(returncode=0),  # fetch
            MagicMock(returncode=0, stdout="Your branch is behind"),  # status
            MagicMock(returncode=1, stdout="CONFLICT", stderr=""),  # rebase fails
            MagicMock(returncode=0),  # rebase --abort
        ]
        result = sync_with_remote()
        assert result == "conflict"

    @patch("ralph.git.get_current_branch")
    def test_sync_with_remote_unknown_branch(self, mock_branch):
        """Test sync returns 'error' when branch is unknown."""
        mock_branch.return_value = "unknown"
        result = sync_with_remote()
        assert result == "error"

    @patch("ralph.git.subprocess.run")
    @patch("ralph.git.get_current_branch")
    @patch("ralph.git.has_uncommitted_plan")
    def test_sync_with_remote_commits_uncommitted_plan(
        self, mock_uncommitted, mock_branch, mock_run, tmp_path
    ):
        """Test sync commits uncommitted plan changes before syncing."""
        mock_branch.return_value = "main"
        mock_uncommitted.return_value = True
        plan_file = tmp_path / "plan.jsonl"
        plan_file.write_text("{}")
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add
            MagicMock(returncode=0),  # git commit
            MagicMock(returncode=0),  # fetch
            MagicMock(returncode=0, stdout="Your branch is up to date"),  # status
        ]
        result = sync_with_remote(plan_file=plan_file)
        assert result == "current"
        assert mock_run.call_count >= 3


class TestPushWithRetry:
    """Tests for push_with_retry function."""

    @patch("ralph.git.subprocess.run")
    @patch("ralph.git.get_current_branch")
    def test_push_with_retry_success_first_try(self, mock_branch, mock_run):
        """Test push succeeds on first try."""
        mock_branch.return_value = "main"
        mock_run.return_value = MagicMock(returncode=0)
        result = push_with_retry()
        assert result is True
        mock_run.assert_called_once()

    @patch("ralph.git.subprocess.run")
    @patch("ralph.git.get_current_branch")
    @patch("ralph.git.sync_with_remote")
    def test_push_with_retry_success_after_sync(self, mock_sync, mock_branch, mock_run):
        """Test push succeeds after syncing with remote."""
        mock_branch.return_value = "main"
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="rejected"),  # first push fails
            MagicMock(returncode=0),  # second push succeeds
        ]
        mock_sync.return_value = "updated"
        result = push_with_retry()
        assert result is True
        assert mock_run.call_count == 2
        mock_sync.assert_called_once()

    @patch("ralph.git.subprocess.run")
    @patch("ralph.git.get_current_branch")
    @patch("ralph.git.sync_with_remote")
    def test_push_with_retry_fails_on_conflict(self, mock_sync, mock_branch, mock_run):
        """Test push fails when sync has conflict."""
        mock_branch.return_value = "main"
        mock_run.return_value = MagicMock(returncode=1, stderr="rejected")
        mock_sync.return_value = "conflict"
        result = push_with_retry()
        assert result is False

    @patch("ralph.git.subprocess.run")
    @patch("ralph.git.get_current_branch")
    def test_push_with_retry_fails_on_other_error(self, mock_branch, mock_run):
        """Test push fails on non-rejected error."""
        mock_branch.return_value = "main"
        mock_run.return_value = MagicMock(returncode=1, stderr="permission denied")
        result = push_with_retry()
        assert result is False

    @patch("ralph.git.get_current_branch")
    def test_push_with_retry_unknown_branch(self, mock_branch):
        """Test push returns False when branch is unknown."""
        mock_branch.return_value = "unknown"
        result = push_with_retry()
        assert result is False

    @patch("ralph.git.subprocess.run")
    @patch("ralph.git.get_current_branch")
    @patch("ralph.git.sync_with_remote")
    def test_push_with_retry_exhausts_retries(self, mock_sync, mock_branch, mock_run):
        """Test push fails after exhausting all retries."""
        mock_branch.return_value = "main"
        mock_run.return_value = MagicMock(returncode=1, stderr="rejected")
        mock_sync.return_value = "updated"
        result = push_with_retry(retries=3)
        assert result is False
        assert mock_run.call_count == 3
        assert mock_sync.call_count == 3

    @patch("ralph.git.subprocess.run")
    def test_push_with_retry_custom_branch(self, mock_run):
        """Test push with explicit branch name."""
        mock_run.return_value = MagicMock(returncode=0)
        result = push_with_retry(branch="feature-branch")
        assert result is True
        mock_run.assert_called_once_with(
            ["git", "push", "origin", "feature-branch"],
            capture_output=True,
            text=True,
            cwd=None,
        )
