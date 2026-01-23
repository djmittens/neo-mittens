"""Unit tests for ralph.analysis module."""

import pytest
from ralph.analysis import (
    analyze_rejection_patterns,
    suggest_issues,
    PATTERN_KEYWORDS,
    REJECTION_THRESHOLD,
    PATTERN_THRESHOLD,
)
from ralph.models import Tombstone, Task, Issue


class TestAnalyzeRejectionPatternsEmpty:
    """Tests for analyze_rejection_patterns with empty input."""

    def test_analyze_rejection_patterns_empty_list(self):
        """Test analyzing an empty list of tombstones."""
        result = analyze_rejection_patterns([])
        assert result["rejections_by_task"] == {}
        assert result["error_patterns"] == {}
        assert result["repeated_tasks"] == []
        assert result["common_patterns"] == []

    def test_analyze_rejection_patterns_only_accepted(self):
        """Test analyzing tombstones with only accepted tasks (no rejections)."""
        tombstones = [
            Tombstone(
                id="t-abc1",
                done_at="commit1",
                reason="Task completed successfully",
                tombstone_type="accept",
                name="Task 1",
            ),
            Tombstone(
                id="t-abc2",
                done_at="commit2",
                reason="All tests passed",
                tombstone_type="accept",
                name="Task 2",
            ),
        ]
        result = analyze_rejection_patterns(tombstones)
        assert result["rejections_by_task"] == {}
        assert result["error_patterns"] == {}
        assert result["repeated_tasks"] == []
        assert result["common_patterns"] == []


class TestAnalyzeRejectionPatternsWithData:
    """Tests for analyze_rejection_patterns with actual rejection data."""

    def test_analyze_single_rejection(self):
        """Test analyzing a single rejection."""
        tombstones = [
            Tombstone(
                id="t-task1",
                done_at="commit1",
                reason="Test failed: file not found",
                tombstone_type="reject",
                name="Task 1",
            ),
        ]
        result = analyze_rejection_patterns(tombstones)
        assert "t-task1" in result["rejections_by_task"]
        assert len(result["rejections_by_task"]["t-task1"]) == 1
        assert result["repeated_tasks"] == []

    def test_analyze_multiple_rejections_same_task(self):
        """Test task rejected multiple times is detected as repeated."""
        tombstones = [
            Tombstone(
                id="t-task1",
                done_at="commit1",
                reason="Test failed: file not found",
                tombstone_type="reject",
            ),
            Tombstone(
                id="t-task1",
                done_at="commit2",
                reason="Still failing: file not found",
                tombstone_type="reject",
            ),
            Tombstone(
                id="t-task1",
                done_at="commit3",
                reason="Third failure: file not found",
                tombstone_type="reject",
            ),
        ]
        result = analyze_rejection_patterns(tombstones)
        assert len(result["rejections_by_task"]["t-task1"]) == 3
        assert "t-task1" in result["repeated_tasks"]

    def test_analyze_threshold_boundary(self):
        """Test task at rejection threshold boundary."""
        tombstones = [
            Tombstone(
                id="t-task1", done_at="c1", reason="fail 1", tombstone_type="reject"
            ),
            Tombstone(
                id="t-task1", done_at="c2", reason="fail 2", tombstone_type="reject"
            ),
        ]
        result = analyze_rejection_patterns(tombstones)
        assert "t-task1" not in result["repeated_tasks"]

        tombstones.append(
            Tombstone(
                id="t-task1", done_at="c3", reason="fail 3", tombstone_type="reject"
            )
        )
        result = analyze_rejection_patterns(tombstones)
        assert "t-task1" in result["repeated_tasks"]

    def test_analyze_pattern_detection(self):
        """Test detection of common error patterns."""
        tombstones = [
            Tombstone(
                id="t-task1",
                done_at="c1",
                reason="Command failed: file not found in directory",
                tombstone_type="reject",
            ),
            Tombstone(
                id="t-task2",
                done_at="c2",
                reason="Error: module not found",
                tombstone_type="reject",
            ),
        ]
        result = analyze_rejection_patterns(tombstones)
        assert "not found" in result["error_patterns"]
        occurrences = result["error_patterns"]["not found"]
        task_ids = [task_id for task_id, _ in occurrences]
        assert "t-task1" in task_ids
        assert "t-task2" in task_ids
        assert "not found" in result["common_patterns"]

    def test_analyze_mixed_accepted_and_rejected(self):
        """Test analyzing mix of accepted and rejected tombstones."""
        tombstones = [
            Tombstone(
                id="t-accept1", done_at="c1", reason="passed", tombstone_type="accept"
            ),
            Tombstone(
                id="t-reject1",
                done_at="c2",
                reason="timeout occurred",
                tombstone_type="reject",
            ),
            Tombstone(
                id="t-accept2", done_at="c3", reason="passed", tombstone_type="accept"
            ),
            Tombstone(
                id="t-reject2",
                done_at="c4",
                reason="times out on CI",
                tombstone_type="reject",
            ),
        ]
        result = analyze_rejection_patterns(tombstones)
        assert len(result["rejections_by_task"]) == 2
        assert "t-accept1" not in result["rejections_by_task"]
        assert "t-reject1" in result["rejections_by_task"]
        assert "t-reject2" in result["rejections_by_task"]

    def test_analyze_multiple_patterns(self):
        """Test detection of multiple different error patterns."""
        tombstones = [
            Tombstone(
                id="t-1", done_at="c1", reason="file not found", tombstone_type="reject"
            ),
            Tombstone(
                id="t-2",
                done_at="c2",
                reason="module not found",
                tombstone_type="reject",
            ),
            Tombstone(
                id="t-3",
                done_at="c3",
                reason="times out waiting",
                tombstone_type="reject",
            ),
            Tombstone(
                id="t-4",
                done_at="c4",
                reason="also times out here",
                tombstone_type="reject",
            ),
        ]
        result = analyze_rejection_patterns(tombstones)
        assert "not found" in result["common_patterns"]
        assert "times out" in result["common_patterns"]

    def test_pattern_keyword_case_insensitive(self):
        """Test that pattern matching is case-insensitive."""
        tombstones = [
            Tombstone(
                id="t-1", done_at="c1", reason="FILE NOT FOUND", tombstone_type="reject"
            ),
            Tombstone(
                id="t-2",
                done_at="c2",
                reason="Not Found error",
                tombstone_type="reject",
            ),
        ]
        result = analyze_rejection_patterns(tombstones)
        assert "not found" in result["error_patterns"]
        assert len(result["error_patterns"]["not found"]) == 2


class TestSuggestIssues:
    """Tests for suggest_issues function."""

    def test_suggest_issues_empty_patterns(self):
        """Test suggesting issues from empty patterns."""
        patterns = {
            "rejections_by_task": {},
            "error_patterns": {},
            "repeated_tasks": [],
            "common_patterns": [],
        }
        issues = suggest_issues(patterns)
        assert issues == []

    def test_suggest_issues_for_repeated_task(self):
        """Test suggesting issues for repeatedly rejected tasks."""
        patterns = {
            "rejections_by_task": {
                "t-stubborn": ["fail 1", "fail 2", "fail 3"],
            },
            "error_patterns": {},
            "repeated_tasks": ["t-stubborn"],
            "common_patterns": [],
        }
        issues = suggest_issues(patterns, spec="test-spec.md")
        assert len(issues) == 1
        assert "REPEATED REJECTION" in issues[0].desc
        assert "t-stubborn" in issues[0].desc
        assert issues[0].priority == "high"
        assert issues[0].spec == "test-spec.md"

    def test_suggest_issues_with_task_name_lookup(self):
        """Test that task names are looked up from tasks list."""
        patterns = {
            "rejections_by_task": {
                "t-task123": ["fail 1", "fail 2", "fail 3"],
            },
            "error_patterns": {},
            "repeated_tasks": ["t-task123"],
            "common_patterns": [],
        }
        tasks = [
            Task(id="t-task123", name="Implement feature X", spec="spec.md"),
            Task(id="t-other", name="Other task", spec="spec.md"),
        ]
        issues = suggest_issues(patterns, tasks=tasks)
        assert len(issues) == 1
        assert "Implement feature X" in issues[0].desc

    def test_suggest_issues_for_common_pattern(self):
        """Test suggesting issues for common failure patterns."""
        patterns = {
            "rejections_by_task": {},
            "error_patterns": {
                "not found": [
                    ("t-1", "file not found"),
                    ("t-2", "module not found"),
                ],
            },
            "repeated_tasks": [],
            "common_patterns": ["not found"],
        }
        issues = suggest_issues(patterns, spec="test.md")
        assert len(issues) == 1
        assert "COMMON FAILURE PATTERN" in issues[0].desc
        assert "not found" in issues[0].desc
        assert "2 tasks" in issues[0].desc
        assert issues[0].priority == "high"

    def test_suggest_issues_avoids_duplicates(self):
        """Test that existing issues are not duplicated."""
        patterns = {
            "rejections_by_task": {
                "t-task1": ["fail 1", "fail 2", "fail 3"],
            },
            "error_patterns": {},
            "repeated_tasks": ["t-task1"],
            "common_patterns": [],
        }
        existing_issues = [
            Issue(id="i-exist", desc="repeated rejection: t-task1", spec="spec.md"),
        ]
        issues = suggest_issues(patterns, existing_issues=existing_issues)
        assert len(issues) == 0

    def test_suggest_issues_multiple_repeated_tasks(self):
        """Test suggesting issues for multiple repeated tasks."""
        patterns = {
            "rejections_by_task": {
                "t-1": ["f1", "f2", "f3"],
                "t-2": ["f1", "f2", "f3", "f4"],
            },
            "error_patterns": {},
            "repeated_tasks": ["t-1", "t-2"],
            "common_patterns": [],
        }
        issues = suggest_issues(patterns)
        assert len(issues) == 2
        descs = [i.desc for i in issues]
        assert any("t-1" in d for d in descs)
        assert any("t-2" in d for d in descs)

    def test_suggest_issues_both_repeated_and_patterns(self):
        """Test suggesting issues for both repeated tasks and common patterns."""
        patterns = {
            "rejections_by_task": {
                "t-stubborn": ["not found", "not found again", "still not found"],
            },
            "error_patterns": {
                "not found": [
                    ("t-stubborn", "not found"),
                    ("t-other", "also not found"),
                ],
            },
            "repeated_tasks": ["t-stubborn"],
            "common_patterns": ["not found"],
        }
        issues = suggest_issues(patterns)
        assert len(issues) == 2
        descs = [i.desc for i in issues]
        assert any("REPEATED REJECTION" in d for d in descs)
        assert any("COMMON FAILURE PATTERN" in d for d in descs)

    def test_suggest_issues_reason_truncation(self):
        """Test that long reasons are truncated in issue descriptions."""
        long_reason = "x" * 200
        patterns = {
            "rejections_by_task": {
                "t-task1": [long_reason, "short", "medium"],
            },
            "error_patterns": {},
            "repeated_tasks": ["t-task1"],
            "common_patterns": [],
        }
        issues = suggest_issues(patterns)
        assert len(issues) == 1
        assert len(issues[0].desc) < 500

    def test_suggest_issues_generates_unique_ids(self):
        """Test that generated issues have unique IDs."""
        patterns = {
            "rejections_by_task": {
                "t-1": ["f", "f", "f"],
                "t-2": ["f", "f", "f"],
            },
            "error_patterns": {},
            "repeated_tasks": ["t-1", "t-2"],
            "common_patterns": [],
        }
        issues = suggest_issues(patterns)
        ids = [i.id for i in issues]
        assert len(ids) == len(set(ids))


class TestConstants:
    """Tests for module constants."""

    def test_pattern_keywords_exist(self):
        """Test that pattern keywords are defined."""
        assert len(PATTERN_KEYWORDS) > 0
        assert isinstance(PATTERN_KEYWORDS, list)
        assert all(isinstance(k, str) for k in PATTERN_KEYWORDS)

    def test_thresholds_are_positive(self):
        """Test that thresholds are positive integers."""
        assert REJECTION_THRESHOLD > 0
        assert PATTERN_THRESHOLD > 0

    def test_threshold_values(self):
        """Test expected threshold values."""
        assert REJECTION_THRESHOLD == 3
        assert PATTERN_THRESHOLD == 2
