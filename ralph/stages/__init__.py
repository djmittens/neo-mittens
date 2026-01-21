"""
Ralph stages package.

This module exports the core stage-related types for the construct state machine.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class Stage(Enum):
    """Stages within construct mode's iteration loop."""

    INVESTIGATE = auto()  # Turn issues into tasks
    BUILD = auto()  # Execute tasks
    VERIFY = auto()  # Verify done tasks against spec
    DECOMPOSE = auto()  # Handle failures by breaking down work
    COMPLETE = auto()  # Spec fully implemented


class StageOutcome(Enum):
    """Outcome of running a stage."""

    SUCCESS = auto()  # Stage completed normally
    FAILURE = auto()  # Stage failed (timeout/context/error)
    SKIP = auto()  # Stage skipped (no work to do)


@dataclass
class StageResult:
    """Result of running a single stage."""

    stage: Stage
    outcome: StageOutcome
    exit_code: int = 0
    duration_seconds: float = 0.0
    cost: float = 0.0
    tokens_used: int = 0
    kill_reason: Optional[str] = None  # "timeout", "context_limit", "compaction_failed"
    kill_log: Optional[str] = None  # Path to log file if killed
    task_id: Optional[str] = None  # Task that was being executed (for BUILD/DECOMPOSE)
    error: Optional[str] = None  # Error message if any


__all__ = ["Stage", "StageOutcome", "StageResult"]
