"""Ralph data models for tasks, issues, and tombstones.

These dataclasses define the schema for ticket records. The tix binary
owns the plan.jsonl file — all reads and writes go through the tix CLI
(see ralph.tix). These models are used only for deserializing tix CLI
JSON output and for the powerplant/ralph legacy monolith.

Note: RalphPlanConfig was removed — configuration now lives in
~/.config/ralph/config.toml via GlobalConfig.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Task:
    """A task in the Ralph plan."""

    id: str
    name: str
    spec: str
    notes: Optional[str] = None
    accept: Optional[str] = None
    deps: Optional[list] = None
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

    def __post_init__(self):
        """Validate task state consistency after initialization."""
        # A killed task cannot be marked as done - these states are mutually exclusive
        # If both are set, prioritize kill_reason (task needs decomposition, not acceptance)
        if self.kill_reason and self.status == "d":
            self.status = "p"
            self.done_at = None

    def _serialize_optional_fields(self, d: dict[str, Any]) -> None:
        """Add optional fields to dict if they have truthy values."""
        optional_fields = [
            ("notes", self.notes),
            ("accept", self.accept),
            ("deps", self.deps),
            ("done_at", self.done_at),
            ("kill", self.kill_reason),
            ("kill_log", self.kill_log),
            ("priority", self.priority),
            ("reject", self.reject_reason),
            ("parent", self.parent),
            ("created_from", self.created_from),
            ("supersedes", self.supersedes),
            ("decompose_depth", self.decompose_depth),
            ("timeout_ms", self.timeout_ms),
        ]
        for key, value in optional_fields:
            if value:
                d[key] = value
        if self.needs_decompose:
            d["decompose"] = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize task to dict for JSONL storage."""
        d: dict[str, Any] = {
            "t": "task",
            "id": self.id,
            "name": self.name,
            "spec": self.spec,
            "s": self.status,
        }
        self._serialize_optional_fields(d)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        """Deserialize task from dict."""
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


@dataclass
class Issue:
    """An issue discovered during Ralph stages."""

    id: str
    desc: str
    spec: str
    priority: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize issue to dict for JSONL storage."""
        d: dict[str, Any] = {
            "t": "issue",
            "id": self.id,
            "desc": self.desc,
            "spec": self.spec,
        }
        if self.priority:
            d["priority"] = self.priority
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Issue":
        """Deserialize issue from dict."""
        return cls(
            id=d["id"],
            desc=d.get("desc", ""),
            spec=d.get("spec", ""),
            priority=d.get("priority"),
        )


@dataclass
class Tombstone:
    """A completed task that has been accepted or rejected."""

    id: str
    done_at: str
    reason: str
    tombstone_type: str = "reject"
    name: str = ""
    timestamp: Optional[str] = None
    changed_files: Optional[list] = None
    log_file: Optional[str] = None
    iteration: Optional[int] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize tombstone to dict for JSONL storage."""
        d: dict[str, Any] = {
            "t": self.tombstone_type,
            "id": self.id,
            "done_at": self.done_at,
            "reason": self.reason,
        }
        if self.name:
            d["name"] = self.name
        if self.timestamp:
            d["timestamp"] = self.timestamp
        if self.changed_files:
            d["changed_files"] = self.changed_files
        if self.log_file:
            d["log_file"] = self.log_file
        if self.iteration is not None:
            d["iteration"] = self.iteration
        if self.notes:
            d["notes"] = self.notes
        return d

    @classmethod
    def from_dict(cls, d: dict, tombstone_type: str = "reject") -> "Tombstone":
        """Deserialize tombstone from dict."""
        return cls(
            id=d["id"],
            done_at=d.get("done_at", ""),
            reason=d.get("reason", ""),
            tombstone_type=tombstone_type,
            name=d.get("name", ""),
            timestamp=d.get("timestamp"),
            changed_files=d.get("changed_files"),
            log_file=d.get("log_file"),
            iteration=d.get("iteration"),
            notes=d.get("notes"),
        )


