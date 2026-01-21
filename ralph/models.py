"""Data models for Ralph's task and issue management."""

import json
from dataclasses import dataclass
from typing import List, Optional, Dict, Union, Any


@dataclass
class Task:
    """A task in the Ralph plan.

    Tasks are the primary units of work in Ralph. They have a lifecycle from
    pending to done, can have dependencies on other tasks, and track various
    metadata about their execution.

    Attributes:
        id: Unique identifier (e.g., 't-k5x9ab').
        name: Short task name describing what to do.
        spec: Spec file this task belongs to.
        notes: Implementation notes/context (how to do it).
        accept: Acceptance criteria / test plan (how to verify).
        deps: List of task IDs this depends on.
        status: Current status ('p' = pending, 'd' = done).
        done_at: Commit hash when marked done.
        needs_decompose: True if task was killed and needs breakdown.
        kill_reason: 'timeout' or 'context' if killed.
        kill_log: Path to log file from killed iteration.
        priority: 'high', 'medium', or 'low'.
        reject_reason: Why task was rejected by VERIFY (if retrying).
        parent: Task ID this was decomposed from (DECOMPOSE stage).
        created_from: Issue ID this task was created from (INVESTIGATE stage).
        supersedes: Task ID this replaces (when rejection leads to new approach).
        decompose_depth: How many times this task's lineage has been decomposed (max 3).
        timeout_ms: Per-task timeout override (None = use stage default).
    """

    id: str
    name: str
    spec: str
    notes: Optional[str] = None
    accept: Optional[str] = None
    deps: Optional[List[str]] = None
    status: str = "p"
    done_at: Optional[str] = None
    needs_decompose: bool = False
    kill_reason: Optional[str] = None
    kill_log: Optional[str] = None
    priority: Optional[str] = None
    reject_reason: Optional[str] = None
    parent: Optional[str] = None
    created_from: Optional[str] = None
    supersedes: Optional[str] = None
    decompose_depth: int = 0
    timeout_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Union[str, List[str], bool, int, None]]:
        """Convert task to a dictionary for JSONL serialization.

        Returns:
            Dictionary with task data, omitting None/empty optional fields.
        """
        d: Dict[str, Union[str, List[str], bool, int, None]] = {
            "t": "task",
            "id": self.id,
            "spec": self.spec,
            "name": self.name,
            "s": self.status,
        }
        if self.notes:
            d["notes"] = self.notes
        if self.accept:
            d["accept"] = self.accept
        if self.deps:
            d["deps"] = self.deps
        if self.done_at:
            d["done_at"] = self.done_at
        if self.needs_decompose:
            d["decompose"] = True
        if self.kill_reason:
            d["kill"] = self.kill_reason
        if self.kill_log:
            d["kill_log"] = self.kill_log
        if self.priority:
            d["priority"] = self.priority
        if self.reject_reason:
            d["reject"] = self.reject_reason
        if self.parent:
            d["parent"] = self.parent
        if self.created_from:
            d["created_from"] = self.created_from
        if self.supersedes:
            d["supersedes"] = self.supersedes
        if self.decompose_depth > 0:
            d["decompose_depth"] = self.decompose_depth
        if self.timeout_ms is not None:
            d["timeout_ms"] = self.timeout_ms
        return d

    def to_jsonl(self) -> str:
        """Convert task to a JSON string for JSONL file.

        Returns:
            JSON string representation of the task.
        """
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Task":
        """Create a Task from a dictionary.

        Args:
            d: Dictionary with task data (from JSONL parsing).

        Returns:
            A Task instance.
        """
        name = d.get("name") or d.get("desc", "")
        return cls(
            id=d["id"],
            name=name,
            spec=d.get("spec", ""),
            notes=d.get("notes"),
            accept=d.get("accept"),
            deps=d.get("deps"),
            status=d.get("s", "p"),
            done_at=d.get("done_at"),
            needs_decompose=d.get("decompose", False),
            kill_reason=d.get("kill"),
            kill_log=d.get("kill_log"),
            priority=d.get("priority"),
            reject_reason=d.get("reject"),
            parent=d.get("parent"),
            created_from=d.get("created_from"),
            supersedes=d.get("supersedes"),
            decompose_depth=d.get("decompose_depth", 0),
            timeout_ms=d.get("timeout_ms"),
        )

    @classmethod
    def from_jsonl(cls, d: Dict[str, Any]) -> "Task":
        """Create a Task from a JSONL dictionary.

        Args:
            d: Dictionary parsed from JSONL.

        Returns:
            A Task instance.
        """
        return cls.from_dict(d)


@dataclass
class Issue:
    """An issue in the Ralph plan.

    Issues represent problems discovered during execution that need investigation.
    They can be converted to tasks via the INVESTIGATE stage.

    Attributes:
        id: Unique identifier (e.g., 'i-k5x9cd').
        desc: Description of the issue.
        spec: Spec file this issue belongs to.
        priority: Priority ('high', 'medium', 'low') - inherited by tasks created from this issue.
    """

    id: str
    desc: str
    spec: str
    priority: Optional[str] = None

    def to_dict(self) -> Dict[str, Union[str, None]]:
        """Convert issue to a dictionary for JSONL serialization.

        Returns:
            Dictionary with issue data, omitting None optional fields.
        """
        d: Dict[str, Union[str, None]] = {
            "t": "issue",
            "id": self.id,
            "spec": self.spec,
            "desc": self.desc,
        }
        if self.priority:
            d["priority"] = self.priority
        return d

    def to_jsonl(self) -> str:
        """Convert issue to a JSON string for JSONL file.

        Returns:
            JSON string representation of the issue.
        """
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Issue":
        """Create an Issue from a dictionary.

        Args:
            d: Dictionary with issue data (from JSONL parsing).

        Returns:
            An Issue instance.
        """
        return cls(
            id=d["id"],
            desc=d["desc"],
            spec=d.get("spec", ""),
            priority=d.get("priority"),
        )

    @classmethod
    def from_jsonl(cls, d: Dict[str, Any]) -> "Issue":
        """Create an Issue from a JSONL dictionary.

        Args:
            d: Dictionary parsed from JSONL.

        Returns:
            An Issue instance.
        """
        return cls.from_dict(d)


@dataclass
class Tombstone:
    """A tombstone marking an accepted or rejected task.

    When a task is accepted or rejected by the VERIFY stage, a tombstone is
    created to track the outcome and the commit where the task was marked done.

    Attributes:
        id: Task ID that was accepted/rejected.
        done_at: Commit hash where task was marked done.
        reason: Why the task was rejected (empty for accepts).
        tombstone_type: "accept" or "reject" to distinguish outcomes.
    """

    id: str
    done_at: str
    reason: str
    tombstone_type: str = "reject"

    def to_dict(self) -> Dict[str, str]:
        """Convert tombstone to a dictionary for JSONL serialization.

        Returns:
            Dictionary with tombstone data.
        """
        return {
            "t": self.tombstone_type,
            "id": self.id,
            "done_at": self.done_at,
            "reason": self.reason,
        }

    def to_jsonl(self) -> str:
        """Convert tombstone to a JSON string for JSONL file.

        Returns:
            JSON string representation of the tombstone.
        """
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(
        cls, d: Dict[str, Any], tombstone_type: str = "reject"
    ) -> "Tombstone":
        """Create a Tombstone from a dictionary.

        Args:
            d: Dictionary with tombstone data (from JSONL parsing).
            tombstone_type: Type of tombstone ("accept" or "reject").

        Returns:
            A Tombstone instance.
        """
        return cls(
            id=d["id"],
            done_at=d.get("done_at", ""),
            reason=d.get("reason", ""),
            tombstone_type=tombstone_type,
        )

    @classmethod
    def from_jsonl(
        cls, d: Dict[str, Any], tombstone_type: str = "reject"
    ) -> "Tombstone":
        """Create a Tombstone from a JSONL dictionary.

        Args:
            d: Dictionary parsed from JSONL.
            tombstone_type: Type of tombstone ("accept" or "reject").

        Returns:
            A Tombstone instance.
        """
        return cls.from_dict(d, tombstone_type)


@dataclass
class RalphPlanConfig:
    """Configuration from plan.jsonl config record.

    This stores per-plan configuration that can override global defaults.

    Attributes:
        timeout_ms: Default timeout per stage in milliseconds (default: 300000 = 5 min).
        max_iterations: Maximum iterations per construct run (default: 10).
        context_warn: Context usage percentage to trigger warning (default: 0.70).
        context_compact: Context usage percentage to trigger compaction (default: 0.85).
        context_kill: Context usage percentage to kill iteration (default: 0.95).
    """

    timeout_ms: int = 300000
    max_iterations: int = 10
    context_warn: float = 0.70
    context_compact: float = 0.85
    context_kill: float = 0.95

    def to_dict(self) -> Dict[str, Union[str, int, float]]:
        """Convert config to a dictionary for JSONL serialization.

        Returns:
            Dictionary with config data.
        """
        return {
            "t": "config",
            "timeout_ms": self.timeout_ms,
            "max_iterations": self.max_iterations,
            "context_warn": self.context_warn,
            "context_compact": self.context_compact,
            "context_kill": self.context_kill,
        }

    def to_jsonl(self) -> str:
        """Convert config to a JSON string for JSONL file.

        Returns:
            JSON string representation of the config.
        """
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RalphPlanConfig":
        """Create a RalphPlanConfig from a dictionary.

        Args:
            d: Dictionary with config data (from JSONL parsing).

        Returns:
            A RalphPlanConfig instance.
        """
        return cls(
            timeout_ms=d.get("timeout_ms", 300000),
            max_iterations=d.get("max_iterations", 10),
            context_warn=d.get("context_warn", 0.70),
            context_compact=d.get("context_compact", 0.85),
            context_kill=d.get("context_kill", 0.95),
        )

    @classmethod
    def from_jsonl(cls, d: Dict[str, Any]) -> "RalphPlanConfig":
        """Create a RalphPlanConfig from a JSONL dictionary.

        Args:
            d: Dictionary parsed from JSONL.

        Returns:
            A RalphPlanConfig instance.
        """
        return cls.from_dict(d)
