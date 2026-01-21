"""Pytest fixtures for Ralph tests."""

import os
import tempfile
from typing import Generator

import pytest

from ralph.models import Issue, RalphPlanConfig, Task, Tombstone


@pytest.fixture
def sample_task() -> Task:
    """Create a sample task for testing."""
    return Task(
        id="t-abc123",
        name="Test task",
        spec="test-spec.md",
        notes="Some implementation notes",
        accept="Verify it works",
        deps=None,
        status="p",
        priority="high",
    )


@pytest.fixture
def sample_done_task() -> Task:
    """Create a sample completed task for testing."""
    return Task(
        id="t-def456",
        name="Completed task",
        spec="test-spec.md",
        status="d",
        done_at="abc123def",
        priority="medium",
    )


@pytest.fixture
def sample_issue() -> Issue:
    """Create a sample issue for testing."""
    return Issue(
        id="i-ghi789",
        desc="Something needs investigation",
        spec="test-spec.md",
        priority="high",
    )


@pytest.fixture
def sample_tombstone() -> Tombstone:
    """Create a sample tombstone for testing."""
    return Tombstone(
        id="t-jkl012",
        done_at="xyz789abc",
        reason="Task rejected due to incomplete implementation",
        tombstone_type="reject",
    )


@pytest.fixture
def sample_accept_tombstone() -> Tombstone:
    """Create a sample accept tombstone for testing."""
    return Tombstone(
        id="t-mno345",
        done_at="def456ghi",
        reason="",
        tombstone_type="accept",
    )


@pytest.fixture
def sample_config() -> RalphPlanConfig:
    """Create a sample plan config for testing."""
    return RalphPlanConfig(
        timeout_ms=300000,
        max_iterations=10,
        context_warn=0.70,
        context_compact=0.85,
        context_kill=0.95,
    )


@pytest.fixture
def temp_dir() -> Generator[str, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def temp_ralph_dir(temp_dir: str) -> Generator[str, None, None]:
    """Create a temporary ralph directory structure."""
    ralph_dir = os.path.join(temp_dir, "ralph")
    os.makedirs(ralph_dir)
    specs_dir = os.path.join(ralph_dir, "specs")
    os.makedirs(specs_dir)
    yield ralph_dir


@pytest.fixture
def sample_plan_jsonl() -> str:
    """Return sample plan.jsonl content for testing."""
    return """\
{"t": "config", "timeout_ms": 300000, "max_iterations": 10}
{"t": "task", "id": "t-abc123", "spec": "test.md", "name": "First task", "s": "p", "priority": "high"}
{"t": "task", "id": "t-def456", "spec": "test.md", "name": "Second task", "s": "d", "done_at": "commit123", "priority": "medium"}
{"t": "issue", "id": "i-ghi789", "spec": "test.md", "desc": "An issue to investigate"}
{"t": "reject", "id": "t-old001", "done_at": "oldcommit", "reason": "Did not work"}
{"t": "accept", "id": "t-old002", "done_at": "oldcommit2", "reason": ""}
"""
