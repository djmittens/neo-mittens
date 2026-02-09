"""Unit tests for ralph.git module."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from ralph.git import (
    get_current_commit,
    get_current_branch,
    get_uncommitted_diff,
    has_uncommitted_plan,
    sync_with_remote,
    push_with_retry,
    IterationCommitInfo,
    TaskVerdict,
    has_uncommitted_changes,
    lookup_task_names,
    build_commit_message,
    commit_iteration,
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


class TestIterationCommitInfo:
    """Tests for IterationCommitInfo dataclass."""

    def test_empty_info_has_no_verdicts(self):
        """Test new info has no verdicts."""
        info = IterationCommitInfo()
        assert info.has_verdicts is False
        assert info.accepted == []
        assert info.rejected == []

    def test_accepted_and_rejected_filtering(self):
        """Test verdict filtering by accepted/rejected."""
        info = IterationCommitInfo()
        info.verdicts.append(
            TaskVerdict("t-aaa", "Task A", accepted=True)
        )
        info.verdicts.append(
            TaskVerdict("t-bbb", "Task B", accepted=False, reason="failed")
        )
        info.verdicts.append(
            TaskVerdict("t-ccc", "Task C", accepted=True)
        )
        assert info.has_verdicts is True
        assert len(info.accepted) == 2
        assert len(info.rejected) == 1
        assert info.rejected[0].reason == "failed"

    def test_reset_clears_all(self):
        """Test reset clears all accumulated state."""
        info = IterationCommitInfo(iteration=5, spec="foo.md")
        info.stages_run.append("BUILD")
        info.verdicts.append(
            TaskVerdict("t-aaa", "Task A", accepted=True)
        )
        info.tasks_added.append("t-bbb")
        info.issues_added.append("i-ccc")
        info.issues_investigated = 3

        info.reset(10)

        assert info.iteration == 10
        assert info.stages_run == []
        assert info.verdicts == []
        assert info.tasks_added == []
        assert info.issues_added == []
        assert info.issues_investigated == 0


class TestLookupTaskNames:
    """Tests for lookup_task_names function."""

    def test_finds_names_from_plan(self, tmp_path):
        """Test resolving task IDs to names from plan.jsonl."""
        plan = tmp_path / "plan.jsonl"
        plan.write_text(
            '{"t":"task","id":"t-aaa","name":"Rename gc_heap.h","s":"p"}\n'
            '{"t":"accept","id":"t-aaa","name":"Rename gc_heap.h"}\n'
            '{"t":"task","id":"t-bbb","name":"Update tests","s":"p"}\n'
        )
        result = lookup_task_names(plan, ["t-aaa", "t-bbb", "t-xxx"])
        assert result == {"t-aaa": "Rename gc_heap.h", "t-bbb": "Update tests"}

    def test_missing_file_returns_empty(self, tmp_path):
        """Test returns empty dict when plan file missing."""
        plan = tmp_path / "nonexistent.jsonl"
        result = lookup_task_names(plan, ["t-aaa"])
        assert result == {}

    def test_empty_ids_returns_empty(self, tmp_path):
        """Test returns empty dict for empty ID list."""
        plan = tmp_path / "plan.jsonl"
        plan.write_text('{"t":"task","id":"t-aaa","name":"Foo"}\n')
        result = lookup_task_names(plan, [])
        assert result == {}

    def test_malformed_json_lines_skipped(self, tmp_path):
        """Test gracefully handles malformed JSON lines."""
        plan = tmp_path / "plan.jsonl"
        plan.write_text(
            'not json at all\n'
            '{"t":"task","id":"t-aaa","name":"Good task","s":"p"}\n'
            '{broken\n'
        )
        result = lookup_task_names(plan, ["t-aaa"])
        assert result == {"t-aaa": "Good task"}


class TestBuildCommitMessage:
    """Tests for build_commit_message function."""

    def test_single_accept(self):
        """Test message for single accepted task."""
        info = IterationCommitInfo(
            iteration=5, spec="heap-rename.md",
            stages_run=["BUILD", "VERIFY"],
        )
        info.verdicts.append(
            TaskVerdict("t-aaa", "Rename gc_heap.h", accepted=True)
        )
        msg = build_commit_message(info)
        assert msg.startswith("ralph: accept t-aaa Rename gc_heap.h")
        assert "Accepted:" in msg
        assert "Spec: heap-rename.md" in msg
        assert "Iteration: 5" in msg

    def test_single_reject(self):
        """Test message for single rejected task."""
        info = IterationCommitInfo(
            iteration=3, spec="types.md",
            stages_run=["VERIFY"],
        )
        info.verdicts.append(
            TaskVerdict(
                "t-bbb", "Update gc.c", accepted=False,
                reason="wrapper functions still present",
            )
        )
        msg = build_commit_message(info)
        assert msg.startswith("ralph: reject t-bbb Update gc.c")
        assert "Rejected:" in msg
        assert "reason: wrapper functions still present" in msg

    def test_mixed_accept_reject(self):
        """Test message for mixed accept and reject."""
        info = IterationCommitInfo(iteration=7, stages_run=["VERIFY"])
        info.verdicts.append(
            TaskVerdict("t-aaa", "Task A", accepted=True)
        )
        info.verdicts.append(
            TaskVerdict("t-bbb", "Task B", accepted=True)
        )
        info.verdicts.append(
            TaskVerdict("t-ccc", "Task C", accepted=False, reason="bad")
        )
        msg = build_commit_message(info)
        assert msg.startswith("ralph: accept 2, reject 1 tasks")

    def test_multiple_accepts(self):
        """Test message for multiple accepted tasks."""
        info = IterationCommitInfo(iteration=10, stages_run=["VERIFY"])
        info.verdicts.append(
            TaskVerdict("t-aaa", "Task A", accepted=True)
        )
        info.verdicts.append(
            TaskVerdict("t-bbb", "Task B", accepted=True)
        )
        info.verdicts.append(
            TaskVerdict("t-ccc", "Task C", accepted=True)
        )
        msg = build_commit_message(info)
        assert msg.startswith("ralph: accept 3 tasks")

    def test_build_only_no_verdicts(self):
        """Test message when only BUILD ran (no verdicts yet)."""
        info = IterationCommitInfo(
            iteration=4, stages_run=["BUILD"],
        )
        msg = build_commit_message(info)
        assert msg.startswith("ralph: build iteration 4")

    def test_no_stages_fallback(self):
        """Test fallback message for empty info."""
        info = IterationCommitInfo(iteration=1)
        msg = build_commit_message(info)
        assert msg.startswith("ralph: iteration 1")

    def test_investigate_message(self):
        """Test message for investigate stage."""
        info = IterationCommitInfo(
            iteration=6, stages_run=["INVESTIGATE"],
        )
        info.issues_investigated = 3
        msg = build_commit_message(info)
        assert msg.startswith("ralph: investigate 3 issues")

    def test_tasks_created_message(self):
        """Test message when tasks are created."""
        info = IterationCommitInfo(
            iteration=2, stages_run=["INVESTIGATE"],
        )
        info.tasks_added = ["t-aaa", "t-bbb", "t-ccc"]
        msg = build_commit_message(info)
        assert msg.startswith("ralph: create 3 tasks")
        assert "Tasks created: 3" in msg

    def test_long_reason_truncated(self):
        """Test that very long rejection reasons are truncated."""
        info = IterationCommitInfo(iteration=1, stages_run=["VERIFY"])
        long_reason = "x" * 300
        info.verdicts.append(
            TaskVerdict("t-aaa", "Task A", accepted=False, reason=long_reason)
        )
        msg = build_commit_message(info)
        assert "..." in msg
        # Reason should be truncated to 200 chars
        for line in msg.split("\n"):
            if "reason:" in line:
                assert len(line) < 220

    def test_stages_in_footer(self):
        """Test stages appear in footer."""
        info = IterationCommitInfo(
            iteration=5, stages_run=["BUILD", "VERIFY"],
        )
        info.verdicts.append(
            TaskVerdict("t-aaa", "Task A", accepted=True)
        )
        msg = build_commit_message(info)
        assert "Stages: BUILD -> VERIFY" in msg


class TestCommitIteration:
    """Tests for commit_iteration function."""

    @patch("ralph.git.subprocess.run")
    @patch("ralph.git.has_uncommitted_changes")
    def test_commits_when_changes_exist(self, mock_has, mock_run):
        """Test commit is created when there are changes."""
        mock_has.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
        info = IterationCommitInfo(iteration=1, stages_run=["BUILD"])
        result = commit_iteration(info)
        assert result is True
        # Should call git add -A and git commit
        assert mock_run.call_count == 2
        add_call = mock_run.call_args_list[0]
        assert add_call[0][0] == ["git", "add", "-A"]
        commit_call = mock_run.call_args_list[1]
        assert commit_call[0][0][0:3] == ["git", "commit", "-m"]

    @patch("ralph.git.has_uncommitted_changes")
    def test_skips_when_no_changes(self, mock_has):
        """Test no commit when working tree is clean."""
        mock_has.return_value = False
        info = IterationCommitInfo(iteration=1)
        result = commit_iteration(info)
        assert result is False

    @patch("ralph.git.subprocess.run")
    @patch("ralph.git.has_uncommitted_changes")
    def test_commit_message_includes_task_info(self, mock_has, mock_run):
        """Test commit message contains task details."""
        mock_has.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
        info = IterationCommitInfo(
            iteration=5, spec="heap-rename.md",
            stages_run=["BUILD", "VERIFY"],
        )
        info.verdicts.append(
            TaskVerdict("t-aaa", "Rename gc_heap.h", accepted=True)
        )
        commit_iteration(info)
        commit_call = mock_run.call_args_list[1]
        message = commit_call[0][0][3]
        assert "t-aaa" in message
        assert "Rename gc_heap.h" in message
        assert "heap-rename.md" in message

    @patch("ralph.git.subprocess.run")
    @patch("ralph.git.has_uncommitted_changes")
    def test_returns_false_on_commit_failure(self, mock_has, mock_run):
        """Test returns False when git commit fails."""
        mock_has.return_value = True
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add
            MagicMock(returncode=1),  # git commit fails
        ]
        info = IterationCommitInfo(iteration=1)
        result = commit_iteration(info)
        assert result is False


class TestHasUncommittedChanges:
    """Tests for has_uncommitted_changes function."""

    @patch("ralph.git.subprocess.run")
    def test_clean_tree(self, mock_run):
        """Test returns False for clean working tree."""
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        assert has_uncommitted_changes() is False

    @patch("ralph.git.subprocess.run")
    def test_dirty_tree(self, mock_run):
        """Test returns True for dirty working tree."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout=" M src/gc.c\n M src/gc.h\n"
        )
        assert has_uncommitted_changes() is True


class TestGetUncommittedDiff:
    """Tests for get_uncommitted_diff function."""

    @patch("ralph.git.subprocess.run")
    def test_returns_diff_with_stat_header(self, mock_run):
        """Test returns diff with stat summary prepended."""
        diff_text = "diff --git a/src/gc.c b/src/gc.c\n-old\n+new\n"
        stat_text = " src/gc.c | 2 +-\n 1 file changed\n"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=diff_text),   # git diff HEAD
            MagicMock(returncode=0, stdout=stat_text),    # git diff HEAD --stat
        ]
        result = get_uncommitted_diff()
        assert "DIFF STAT" in result
        assert "src/gc.c | 2 +-" in result
        assert "FULL DIFF" in result
        assert diff_text in result

    @patch("ralph.git.subprocess.run")
    def test_falls_back_to_cached(self, mock_run):
        """Test falls back to git diff --cached when HEAD diff is empty."""
        cached_diff = "diff --git a/new.c b/new.c\n+added\n"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=""),            # git diff HEAD: empty
            MagicMock(returncode=0, stdout=cached_diff),   # git diff --cached
            MagicMock(returncode=0, stdout=""),             # git diff HEAD --stat
        ]
        result = get_uncommitted_diff()
        assert cached_diff in result

    @patch("ralph.git.subprocess.run")
    def test_empty_when_no_changes(self, mock_run):
        """Test returns empty string when no changes at all."""
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = get_uncommitted_diff()
        assert result == ""

    @patch("ralph.git.subprocess.run")
    def test_truncates_large_diff_with_dynamic_message(self, mock_run):
        """Test truncates diff and uses actual limit in message."""
        large_diff = "x" * 250_000
        stat_text = " big.c | 9999 +-\n 1 file changed"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=large_diff),   # git diff HEAD
            MagicMock(returncode=0, stdout=stat_text),     # git diff HEAD --stat
        ]
        result = get_uncommitted_diff(max_bytes=50_000)
        assert len(result) < 250_000
        assert "diff truncated at 48KB" in result
        # Stat header is always present even when diff is truncated
        assert "big.c | 9999 +-" in result

    @patch("ralph.git.subprocess.run")
    def test_handles_git_failure(self, mock_run):
        """Test returns empty string on git command failure."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = get_uncommitted_diff()
        assert result == ""

    @patch("ralph.git.subprocess.run")
    def test_respects_cwd(self, mock_run):
        """Test passes cwd to subprocess."""
        diff_text = "diff\n"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=diff_text),    # git diff HEAD
            MagicMock(returncode=0, stdout=""),             # git diff HEAD --stat
        ]
        cwd = Path("/my/repo")
        get_uncommitted_diff(cwd=cwd)
        # First call is git diff HEAD with correct cwd
        first_call = mock_run.call_args_list[0]
        assert first_call[0][0] == ["git", "diff", "HEAD"]
        assert first_call[1]["cwd"] == cwd

    @patch("ralph.git.subprocess.run")
    def test_default_max_bytes_is_200k(self, mock_run):
        """Test default max_bytes is 200KB (enough for large specs)."""
        diff_text = "x" * 150_000
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=diff_text),
            MagicMock(returncode=0, stdout=""),
        ]
        result = get_uncommitted_diff()
        # 150KB should NOT be truncated with 200KB default
        assert "truncated" not in result

    @patch("ralph.git.subprocess.run")
    def test_stat_failure_still_returns_diff(self, mock_run):
        """Test diff is returned even when stat command fails."""
        diff_text = "diff --git a/f.c b/f.c\n+line\n"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=diff_text),    # git diff HEAD
            MagicMock(returncode=1, stdout=""),             # git diff HEAD --stat fails
        ]
        result = get_uncommitted_diff()
        assert diff_text in result
        # No stat header when stat fails
        assert "DIFF STAT" not in result
