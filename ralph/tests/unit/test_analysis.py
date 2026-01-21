"""Unit tests for ralph.analysis module - rejection pattern detection."""

import pytest

from ralph.analysis import (
    PATTERN_KEYWORDS,
    PATTERN_THRESHOLD,
    REJECTION_THRESHOLD,
    RejectionPattern,
    analyze_rejection_patterns,
    suggest_issues,
    _desc_exists,
)
from ralph.models import Issue, Tombstone


class TestRejectionPattern:
    """Tests for the RejectionPattern dataclass."""

    def test_rejection_pattern_creation(self) -> None:
        """Test creating a RejectionPattern with all fields."""
        pattern = RejectionPattern(
            pattern_type="repeated_rejection",
            keyword="",
            task_ids=["t-abc123"],
            reasons=["reason1", "reason2", "reason3"],
            count=3,
        )
        assert pattern.pattern_type == "repeated_rejection"
        assert pattern.keyword == ""
        assert pattern.task_ids == ["t-abc123"]
        assert pattern.reasons == ["reason1", "reason2", "reason3"]
        assert pattern.count == 3

    def test_rejection_pattern_common_error(self) -> None:
        """Test creating a common_error pattern."""
        pattern = RejectionPattern(
            pattern_type="common_error",
            keyword="not found",
            task_ids=["t-abc", "t-def"],
            reasons=["File not found", "Module not found"],
            count=2,
        )
        assert pattern.pattern_type == "common_error"
        assert pattern.keyword == "not found"
        assert len(pattern.task_ids) == 2


class TestAnalyzeRejectionPatterns:
    """Tests for analyze_rejection_patterns function."""

    def test_empty_tombstones(self) -> None:
        """Test with empty tombstone list."""
        patterns = analyze_rejection_patterns([])
        assert patterns == []

    def test_single_rejection_below_threshold(self) -> None:
        """Test single rejection doesn't trigger pattern."""
        tombstones = [
            Tombstone(
                id="t-abc123",
                done_at="commit1",
                reason="Failed to compile",
                tombstone_type="reject",
            )
        ]
        patterns = analyze_rejection_patterns(tombstones)
        assert patterns == []

    def test_multiple_rejections_at_threshold(self) -> None:
        """Test exactly REJECTION_THRESHOLD rejections triggers pattern."""
        tombstones = [
            Tombstone(
                id="t-abc123",
                done_at=f"commit{i}",
                reason=f"Failed attempt {i}",
                tombstone_type="reject",
            )
            for i in range(REJECTION_THRESHOLD)
        ]
        patterns = analyze_rejection_patterns(tombstones)
        assert len(patterns) == 1
        assert patterns[0].pattern_type == "repeated_rejection"
        assert patterns[0].task_ids == ["t-abc123"]
        assert patterns[0].count == REJECTION_THRESHOLD

    def test_multiple_rejections_above_threshold(self) -> None:
        """Test more than REJECTION_THRESHOLD rejections triggers pattern."""
        tombstones = [
            Tombstone(
                id="t-abc123",
                done_at=f"commit{i}",
                reason=f"Failed attempt {i}",
                tombstone_type="reject",
            )
            for i in range(REJECTION_THRESHOLD + 2)
        ]
        patterns = analyze_rejection_patterns(tombstones)
        assert len(patterns) == 1
        assert patterns[0].count == REJECTION_THRESHOLD + 2

    def test_common_error_pattern_single_task(self) -> None:
        """Test common error with only one task doesn't trigger pattern."""
        tombstones = [
            Tombstone(
                id="t-abc123",
                done_at="commit1",
                reason="File not found",
                tombstone_type="reject",
            ),
            Tombstone(
                id="t-abc123",
                done_at="commit2",
                reason="Resource not found",
                tombstone_type="reject",
            ),
        ]
        patterns = analyze_rejection_patterns(tombstones)
        assert not any(p.pattern_type == "common_error" for p in patterns)

    def test_common_error_pattern_multiple_tasks(self) -> None:
        """Test common error affecting multiple tasks triggers pattern."""
        tombstones = [
            Tombstone(
                id="t-abc",
                done_at="commit1",
                reason="File not found",
                tombstone_type="reject",
            ),
            Tombstone(
                id="t-def",
                done_at="commit2",
                reason="Module not found",
                tombstone_type="reject",
            ),
        ]
        patterns = analyze_rejection_patterns(tombstones)
        common_patterns = [p for p in patterns if p.pattern_type == "common_error"]
        assert len(common_patterns) == 1
        assert common_patterns[0].keyword == "not found"
        assert set(common_patterns[0].task_ids) == {"t-abc", "t-def"}

    def test_mixed_patterns(self) -> None:
        """Test detection of both repeated_rejection and common_error patterns."""
        tombstones = [
            Tombstone(
                id="t-repeat", done_at="c1", reason="Fail 1", tombstone_type="reject"
            ),
            Tombstone(
                id="t-repeat", done_at="c2", reason="Fail 2", tombstone_type="reject"
            ),
            Tombstone(
                id="t-repeat", done_at="c3", reason="Fail 3", tombstone_type="reject"
            ),
            Tombstone(
                id="t-error1", done_at="c4", reason="Times out", tombstone_type="reject"
            ),
            Tombstone(
                id="t-error2",
                done_at="c5",
                reason="Request times out",
                tombstone_type="reject",
            ),
        ]
        patterns = analyze_rejection_patterns(tombstones)
        pattern_types = {p.pattern_type for p in patterns}
        assert "repeated_rejection" in pattern_types
        assert "common_error" in pattern_types

    def test_multiple_common_error_patterns(self) -> None:
        """Test multiple different common error patterns are detected."""
        tombstones = [
            Tombstone(
                id="t-1", done_at="c1", reason="File not found", tombstone_type="reject"
            ),
            Tombstone(
                id="t-2",
                done_at="c2",
                reason="Module not found",
                tombstone_type="reject",
            ),
            Tombstone(
                id="t-3",
                done_at="c3",
                reason="Operation times out",
                tombstone_type="reject",
            ),
            Tombstone(
                id="t-4",
                done_at="c4",
                reason="Request timeout",
                tombstone_type="reject",
            ),
        ]
        patterns = analyze_rejection_patterns(tombstones)
        common_patterns = [p for p in patterns if p.pattern_type == "common_error"]
        keywords = {p.keyword for p in common_patterns}
        assert "not found" in keywords

    def test_pattern_keywords_detection(self) -> None:
        """Test each pattern keyword can be detected."""
        for keyword in PATTERN_KEYWORDS[:3]:
            tombstones = [
                Tombstone(
                    id=f"t-task{i}",
                    done_at=f"commit{i}",
                    reason=f"Error: {keyword} occurred",
                    tombstone_type="reject",
                )
                for i in range(PATTERN_THRESHOLD)
            ]
            patterns = analyze_rejection_patterns(tombstones)
            common_patterns = [p for p in patterns if p.pattern_type == "common_error"]
            assert len(common_patterns) >= 1, f"Keyword '{keyword}' should be detected"

    def test_case_insensitive_keyword_matching(self) -> None:
        """Test keyword matching is case-insensitive."""
        tombstones = [
            Tombstone(
                id="t-1", done_at="c1", reason="FILE NOT FOUND", tombstone_type="reject"
            ),
            Tombstone(
                id="t-2",
                done_at="c2",
                reason="Module Not Found",
                tombstone_type="reject",
            ),
        ]
        patterns = analyze_rejection_patterns(tombstones)
        common_patterns = [p for p in patterns if p.pattern_type == "common_error"]
        assert len(common_patterns) == 1
        assert common_patterns[0].keyword == "not found"

    def test_only_first_keyword_matched(self) -> None:
        """Test that only the first matching keyword is counted per tombstone."""
        tombstones = [
            Tombstone(
                id="t-1",
                done_at="c1",
                reason="Not found and timeout occurred",
                tombstone_type="reject",
            ),
            Tombstone(
                id="t-2",
                done_at="c2",
                reason="File not found with timeout",
                tombstone_type="reject",
            ),
        ]
        patterns = analyze_rejection_patterns(tombstones)
        common_patterns = [p for p in patterns if p.pattern_type == "common_error"]
        assert len(common_patterns) == 1


class TestSuggestIssues:
    """Tests for suggest_issues function."""

    def test_empty_patterns(self) -> None:
        """Test with empty patterns list."""
        issues = suggest_issues([], "test.md")
        assert issues == []

    def test_repeated_rejection_issue(self) -> None:
        """Test issue generation for repeated_rejection pattern."""
        patterns = [
            RejectionPattern(
                pattern_type="repeated_rejection",
                keyword="",
                task_ids=["t-abc123"],
                reasons=["r1", "r2", "r3"],
                count=3,
            )
        ]
        issues = suggest_issues(patterns, "test-spec.md")
        assert len(issues) == 1
        assert issues[0].spec == "test-spec.md"
        assert issues[0].priority == "high"
        assert "t-abc123" in issues[0].desc
        assert "3 times" in issues[0].desc

    def test_common_error_issue(self) -> None:
        """Test issue generation for common_error pattern."""
        patterns = [
            RejectionPattern(
                pattern_type="common_error",
                keyword="not found",
                task_ids=["t-1", "t-2", "t-3"],
                reasons=["r1", "r2", "r3"],
                count=3,
            )
        ]
        issues = suggest_issues(patterns, "test-spec.md")
        assert len(issues) == 1
        assert "not found" in issues[0].desc
        assert "3 tasks" in issues[0].desc

    def test_common_error_truncates_task_list(self) -> None:
        """Test that task list is truncated when more than 3 tasks."""
        patterns = [
            RejectionPattern(
                pattern_type="common_error",
                keyword="timeout",
                task_ids=["t-1", "t-2", "t-3", "t-4", "t-5"],
                reasons=["r1", "r2", "r3", "r4", "r5"],
                count=5,
            )
        ]
        issues = suggest_issues(patterns, "test.md")
        assert len(issues) == 1
        assert "(+2 more)" in issues[0].desc

    def test_skip_existing_issues(self) -> None:
        """Test that existing issues are not duplicated."""
        patterns = [
            RejectionPattern(
                pattern_type="repeated_rejection",
                keyword="",
                task_ids=["t-abc123"],
                reasons=["r1", "r2", "r3"],
                count=3,
            )
        ]
        existing = [
            "Task t-abc123 rejected 3 times - needs investigation or decomposition"
        ]
        issues = suggest_issues(patterns, "test.md", existing)
        assert len(issues) == 0

    def test_skip_partial_match_existing_issues(self) -> None:
        """Test that partial matches are skipped."""
        patterns = [
            RejectionPattern(
                pattern_type="repeated_rejection",
                keyword="",
                task_ids=["t-abc123"],
                reasons=["r1", "r2", "r3"],
                count=3,
            )
        ]
        existing = ["t-abc123 needs investigation"]
        issues = suggest_issues(patterns, "test.md", existing)
        assert len(issues) == 1

    def test_multiple_patterns_generate_multiple_issues(self) -> None:
        """Test multiple patterns generate multiple issues."""
        patterns = [
            RejectionPattern(
                pattern_type="repeated_rejection",
                keyword="",
                task_ids=["t-abc"],
                reasons=["r1", "r2", "r3"],
                count=3,
            ),
            RejectionPattern(
                pattern_type="common_error",
                keyword="timeout",
                task_ids=["t-1", "t-2"],
                reasons=["r1", "r2"],
                count=2,
            ),
        ]
        issues = suggest_issues(patterns, "test.md")
        assert len(issues) == 2

    def test_issues_have_unique_ids(self) -> None:
        """Test that generated issues have unique IDs."""
        patterns = [
            RejectionPattern(
                pattern_type="repeated_rejection",
                keyword="",
                task_ids=["t-abc"],
                reasons=["r1", "r2", "r3"],
                count=3,
            ),
            RejectionPattern(
                pattern_type="common_error",
                keyword="timeout",
                task_ids=["t-1", "t-2"],
                reasons=["r1", "r2"],
                count=2,
            ),
        ]
        issues = suggest_issues(patterns, "test.md")
        ids = [i.id for i in issues]
        assert len(ids) == len(set(ids))

    def test_issues_start_with_i_prefix(self) -> None:
        """Test that generated issue IDs start with 'i-'."""
        patterns = [
            RejectionPattern(
                pattern_type="repeated_rejection",
                keyword="",
                task_ids=["t-abc"],
                reasons=["r1", "r2", "r3"],
                count=3,
            ),
        ]
        issues = suggest_issues(patterns, "test.md")
        assert all(i.id.startswith("i-") for i in issues)


class TestDescExists:
    """Tests for _desc_exists helper function."""

    def test_empty_existing(self) -> None:
        """Test with no existing descriptions."""
        assert _desc_exists("new description", []) is False

    def test_exact_match(self) -> None:
        """Test exact match detection."""
        existing = ["task rejected", "another issue"]
        assert _desc_exists("task rejected", existing) is True

    def test_case_insensitive_match(self) -> None:
        """Test case-insensitive matching."""
        existing = ["task rejected"]
        assert _desc_exists("Task Rejected", existing) is True

    def test_substring_match_new_in_existing(self) -> None:
        """Test when new description is substring of existing."""
        existing = ["task rejected multiple times"]
        assert _desc_exists("task rejected", existing) is True

    def test_substring_match_existing_in_new(self) -> None:
        """Test when existing is substring of new description."""
        existing = ["task rejected"]
        assert _desc_exists("task rejected multiple times", existing) is True

    def test_no_match(self) -> None:
        """Test when no match exists."""
        existing = ["unrelated issue", "another problem"]
        assert _desc_exists("new issue", existing) is False


class TestConstants:
    """Tests for module constants."""

    def test_rejection_threshold_value(self) -> None:
        """Test REJECTION_THRESHOLD has expected value."""
        assert REJECTION_THRESHOLD == 3

    def test_pattern_threshold_value(self) -> None:
        """Test PATTERN_THRESHOLD has expected value."""
        assert PATTERN_THRESHOLD == 2

    def test_pattern_keywords_not_empty(self) -> None:
        """Test PATTERN_KEYWORDS is not empty."""
        assert len(PATTERN_KEYWORDS) > 0

    def test_pattern_keywords_are_lowercase(self) -> None:
        """Test all pattern keywords are lowercase."""
        for keyword in PATTERN_KEYWORDS:
            assert keyword == keyword.lower()
