"""Compact command - placeholder for future tix-level compaction.

With tix owning all ticket data (tasks, issues, tombstones),
Ralph's compact command is no longer needed for ticket cleanup.
Orchestration metadata (spec, stage) doesn't need compaction.

A future tix 'compact' subcommand may handle tombstone pruning.
"""

from typing import Optional

from ralph.config import GlobalConfig


def cmd_compact(config: GlobalConfig, args: Optional[object] = None) -> None:
    """Compact plan.jsonl (currently a no-op with tix managing tickets).

    Ticket lifecycle (add/done/accept/reject/delete) is handled by tix.
    Tombstone pruning will be added as a tix subcommand if needed.
    """
    print("Compact: ticket data is managed by tix. No compaction needed.")
