"""Reconcile agent structured output with the ticket system via tix.

The agent outputs structured JSON as its final message. This module
parses that output and applies the corresponding ticket mutations
through the tix harness. The agent never calls tix directly.

Each stage has a specific output schema the agent must produce.
The reconcile functions validate the schema, apply mutations, and
return a summary of what was done.
"""

import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ralph.tix import Tix, TixError, TixProtocol
from ralph.validation import validate_task, validate_issue

__all__ = [
    "ReconcileResult",
    "dedup_tasks",
    "reconcile_build",
    "reconcile_verify",
    "reconcile_investigate",
    "reconcile_decompose",
    "reconcile_plan",
    "extract_structured_output",
]

# Marker the agent wraps its structured output in
OUTPUT_MARKER = "[RALPH_OUTPUT]"
OUTPUT_END_MARKER = "[/RALPH_OUTPUT]"


@dataclass
class ReconcileResult:
    """Summary of reconciliation actions taken."""

    ok: bool = True
    tasks_added: list[str] = field(default_factory=list)
    tasks_accepted: list[str] = field(default_factory=list)
    tasks_rejected: list[str] = field(default_factory=list)
    tasks_deleted: list[str] = field(default_factory=list)
    issues_added: list[str] = field(default_factory=list)
    issues_cleared: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """One-line summary of actions taken."""
        parts = []
        if self.tasks_added:
            parts.append(f"{len(self.tasks_added)} tasks added")
        if self.tasks_accepted:
            parts.append(f"{len(self.tasks_accepted)} accepted")
        if self.tasks_rejected:
            parts.append(f"{len(self.tasks_rejected)} rejected")
        if self.tasks_deleted:
            parts.append(f"{len(self.tasks_deleted)} deleted")
        if self.issues_added:
            parts.append(f"{len(self.issues_added)} issues added")
        if self.issues_cleared:
            parts.append(f"{self.issues_cleared} issues cleared")
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return ", ".join(parts) if parts else "no changes"


def _assemble_text_content(agent_output: str) -> str:
    """Concatenate decoded text from ``text`` events in the event stream.

    The raw agent output is newline-delimited JSON events.  Text events
    carry already-decoded strings (no JSON escaping), so searching this
    concatenated text for ``[RALPH_OUTPUT]`` markers works even when the
    model wraps them in markdown fences.
    """
    parts: list[str] = []
    for line in agent_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "text":
            text = event.get("part", {}).get("text", "")
            if text:
                parts.append(text)
    return "\n".join(parts)


def extract_structured_output(agent_output: str) -> Optional[dict]:
    """Extract structured JSON from agent output.

    The agent wraps its structured output between markers:
        [RALPH_OUTPUT]
        {"verdict": "done", ...}
        [/RALPH_OUTPUT]

    Weaker models sometimes write the JSON to a file via the ``write``
    tool instead of emitting it as text.  When marker-based extraction
    fails we scan ``write`` tool events in the JSON event stream for
    content that looks like structured output (contains ``tasks``,
    ``verdict``, ``results``, or ``subtasks`` keys, or is wrapped in
    ``[RALPH_OUTPUT]`` markers inside the written content).

    Args:
        agent_output: Full stdout from the agent run (JSON event stream).

    Returns:
        Parsed dict, or None if no structured output found.
    """
    # Primary: reassemble decoded text from text events and search for
    # markers there.  This handles the common case where the model wraps
    # [RALPH_OUTPUT] inside a markdown code fence — the decoded text
    # doesn't have JSON escaping, so markers + JSON are clean.
    text_content = _assemble_text_content(agent_output)
    if text_content:
        start = text_content.find(OUTPUT_MARKER)
        end = text_content.find(OUTPUT_END_MARKER)
        if start != -1 and end != -1:
            json_str = text_content[start + len(OUTPUT_MARKER):end].strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

    # Legacy: try raw stream search (works when opencode emits plain text
    # instead of JSON events, e.g. older versions).
    start = agent_output.find(OUTPUT_MARKER)
    end = agent_output.find(OUTPUT_END_MARKER)
    if start != -1 and end != -1:
        json_str = agent_output[start + len(OUTPUT_MARKER):end].strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # Fallback: scan tool events for structured output.
    # Weaker models sometimes deliver the plan JSON via a tool call
    # (write to file, bash cat/echo, etc.) instead of as plain text.
    from_tools = _extract_from_tool_events(agent_output)
    if from_tools is not None:
        print("  Schema repair: extracted output from tool call",
              file=sys.stderr)
        return from_tools

    # Last resort: find last JSON object in assembled text that has
    # at least one recognized ralph output key.  Without this check,
    # random JSON from tool outputs gets picked up and repaired into
    # nonsense (e.g. empty verdict string).
    last_json = _find_last_json_object(text_content or agent_output)
    if last_json is not None and set(last_json.keys()) & _RALPH_OUTPUT_KEYS:
        return last_json

    # Last-ditch: infer verdict from terminal phrases in the text.
    # Weaker models sometimes say "Task completed." without emitting
    # any structured output.  We scan for high-confidence terminal
    # phrases and synthesise a verdict dict so the iteration is not
    # wasted.  Only triggers when ALL other strategies failed.
    inferred = _infer_verdict_from_text(text_content or agent_output)
    if inferred is not None:
        print("  Schema repair: inferred verdict from agent text",
              file=sys.stderr)
        return inferred

    return None


# Keys that indicate a write tool's content is structured ralph output
_RALPH_OUTPUT_KEYS = {"tasks", "verdict", "results", "subtasks"}

# Terminal phrases that indicate the model considers the task done.
# Checked case-insensitively against the last 500 chars of text.
_DONE_PHRASES = (
    "task completed",
    "task is complete",
    "task is done",
    "all acceptance criteria",
    "acceptance criteria are met",
    "acceptance criteria met",
    "implementation is complete",
    "changes are complete",
    "all tests pass",
    "build passes",
    "build succeeds",
)


def _infer_verdict_from_text(text: str) -> Optional[dict]:
    """Infer a verdict dict from terminal phrases when all else fails.

    Only returns a result for high-confidence "done" signals.  Does NOT
    infer "blocked" — ambiguity should fall through to the normal
    failure path so the harness can retry.

    Args:
        text: Assembled text content or raw agent output.

    Returns:
        ``{"verdict": "done", "summary": "..."}`` or None.
    """
    if not text:
        return None
    tail = text[-500:].lower()
    for phrase in _DONE_PHRASES:
        if phrase in tail:
            return {
                "verdict": "done",
                "summary": f"(inferred from agent text: '{phrase}')",
            }
    return None


def _extract_from_tool_events(agent_output: str) -> Optional[dict]:
    """Scan tool events for structured output delivered via tools.

    Weaker models deliver plan JSON through various tool channels
    instead of emitting it as text:
    - ``write`` tool: content field contains the JSON
    - ``bash`` tool: output field contains the JSON (e.g. ``cat << EOF``)

    Iterates over JSON event lines, extracts candidate content from
    each tool call, and returns the best match (largest ``tasks`` list).

    Args:
        agent_output: Raw newline-delimited JSON event stream.

    Returns:
        Parsed dict if found, else None.
    """
    best: Optional[dict] = None
    best_score = -1

    for line in agent_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if event.get("type") != "tool_use":
            continue

        part = event.get("part", {})
        tool = part.get("tool", "")
        state = part.get("state", {})

        # Extract candidate content based on tool type
        candidates: list[str] = []
        if tool == "write":
            content = state.get("input", {}).get("content", "")
            if content:
                candidates.append(content)
        elif tool == "bash":
            output = state.get("output", "")
            if output:
                candidates.append(output)
            # Also check metadata.output (some event formats)
            meta_output = state.get("metadata", {}).get("output", "")
            if meta_output and meta_output != output:
                candidates.append(meta_output)

        for content in candidates:
            candidate = _parse_ralph_json_from_content(content)
            if candidate is None:
                continue

            # Score: prefer candidates with more recognized keys / larger task lists
            score = len(set(candidate.keys()) & _RALPH_OUTPUT_KEYS)
            tasks = candidate.get("tasks", [])
            if isinstance(tasks, list):
                score += len(tasks)

            if score > best_score:
                best = candidate
                best_score = score

    return best


def _parse_ralph_json_from_content(content: str) -> Optional[dict]:
    """Try to extract ralph output JSON from file content.

    Handles two patterns:
    1. Content contains [RALPH_OUTPUT]...json...[/RALPH_OUTPUT] markers
    2. Content is or contains a JSON object with ralph output keys

    Args:
        content: The string content written to a file.

    Returns:
        Parsed dict if it looks like ralph output, else None.
    """
    # Pattern 1: markers inside written content
    start = content.find(OUTPUT_MARKER)
    end = content.find(OUTPUT_END_MARKER)
    if start != -1 and end != -1:
        json_str = content[start + len(OUTPUT_MARKER):end].strip()
        try:
            obj = json.loads(json_str)
            if isinstance(obj, dict) and set(obj.keys()) & _RALPH_OUTPUT_KEYS:
                return obj
        except json.JSONDecodeError:
            pass

    # Pattern 2: content is raw JSON (or has a JSON prefix like "[RALPH_OUTPUT]\n{...")
    # Try direct parse first
    try:
        obj = json.loads(content)
        if isinstance(obj, dict) and set(obj.keys()) & _RALPH_OUTPUT_KEYS:
            return obj
    except json.JSONDecodeError:
        pass

    # Pattern 3: find JSON object within the content
    obj = _find_last_json_object(content)
    if obj is not None and set(obj.keys()) & _RALPH_OUTPUT_KEYS:
        return obj

    return None


def _find_last_json_object(text: str) -> Optional[dict]:
    """Find the last valid JSON object in text."""
    # Search backwards for closing brace
    pos = len(text)
    while pos > 0:
        pos = text.rfind("}", 0, pos)
        if pos == -1:
            break
        # Find matching opening brace
        depth = 0
        for i in range(pos, -1, -1):
            if text[i] == "}":
                depth += 1
            elif text[i] == "{":
                depth -= 1
            if depth == 0:
                candidate = text[i:pos + 1]
                try:
                    obj = json.loads(candidate)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    break
        pos -= 1
    return None


# Stage output schemas: required fields and their expected types
_STAGE_SCHEMAS: dict[str, dict[str, type]] = {
    "build": {"verdict": str},
    "verify": {"results": list},
    "investigate": {"tasks": list},
    "decompose": {"subtasks": list},
    "plan": {"tasks": list},
}


def _repair_output(data: dict, stage: str) -> tuple[dict, list[str]]:
    """Attempt to repair common schema issues in agent output.

    Fixes:
    - Missing fields with safe defaults
    - Wrong types (e.g., string "true" -> bool True)
    - Normalized field names (e.g., "task" -> "tasks")

    Args:
        data: Parsed JSON output from agent.
        stage: Stage name for schema lookup.

    Returns:
        Tuple of (repaired_data, list_of_repairs_made).
    """
    repairs: list[str] = []
    schema = _STAGE_SCHEMAS.get(stage, {})

    for field_name, expected_type in schema.items():
        if field_name not in data:
            # Try common misspellings/singularizations
            singular = field_name.rstrip("s")
            plural = field_name + "s" if not field_name.endswith("s") else field_name
            for alt in (singular, plural):
                if alt in data and alt != field_name:
                    data[field_name] = data.pop(alt)
                    repairs.append(f"renamed '{alt}' -> '{field_name}'")
                    break

        if field_name not in data:
            # Add safe default
            if expected_type == list:
                data[field_name] = []
                repairs.append(f"added empty '{field_name}' list")
            elif expected_type == str:
                data[field_name] = ""
                repairs.append(f"added empty '{field_name}' string")

    # Fix common type issues in verify results
    if stage == "verify":
        for item in data.get("results", []):
            if isinstance(item.get("passed"), str):
                item["passed"] = item["passed"].lower() == "true"
                repairs.append(f"coerced 'passed' string to bool for {item.get('task_id', '?')}")

    # Fix build verdict normalization
    if stage == "build":
        verdict = data.get("verdict", "")
        if isinstance(verdict, str):
            data["verdict"] = verdict.lower().strip()
            if data["verdict"] in ("complete", "completed", "finished", "success"):
                data["verdict"] = "done"
                repairs.append("normalized verdict to 'done'")
            elif data["verdict"] in (
                "partial", "in_progress", "wip", "incomplete",
                "failed", "error", "cannot", "impossible",
            ):
                data["verdict"] = "blocked"
                if not data.get("reason"):
                    data["reason"] = f"Agent reported verdict '{verdict.strip()}'"
                repairs.append(
                    f"normalized verdict '{verdict.strip()}' to 'blocked'"
                )

    return data, repairs


# =============================================================================
# Stage-specific reconcilers
# =============================================================================


def _extract_and_repair(
    agent_output: str, stage: str
) -> tuple[Optional[dict], list[str]]:
    """Extract structured output and apply schema repairs.

    Args:
        agent_output: Full agent stdout.
        stage: Stage name for schema-aware repair.

    Returns:
        Tuple of (parsed_data_or_None, list_of_repairs).
    """
    data = extract_structured_output(agent_output)
    if data is None:
        return None, []
    repaired, repairs = _repair_output(data, stage)
    return repaired, repairs


def _attach_stage_telemetry(
    tix: TixProtocol,
    task_ids: list[str],
    stage_metrics: dict[str, Any],
    stage_name: str,
) -> None:
    """Attach telemetry and stage label to tickets (best-effort).

    Adds a ``stage:<name>`` label so costs can be attributed per stage
    via ``tix q "tasks all | group label | sum meta.cost"``.

    Telemetry is written under the ``meta`` sub-object so tix stores
    it in ``ticket_meta`` (key-value table).

    For VERIFY, metrics are split evenly across verified tasks since the
    stage verifies multiple tasks in one call.

    Args:
        tix: Tix harness instance.
        task_ids: Ticket IDs to update.
        stage_metrics: Dict with cost, tokens_in, tokens_out, etc.
        stage_name: Stage name for labeling (build, verify, etc.).
    """
    if not task_ids:
        return

    # Split cost/tokens across tasks when stage handles multiple
    count = len(task_ids)
    meta: dict[str, Any] = {}
    for key in ("cost", "tokens_in", "tokens_cached", "tokens_out", "iterations"):
        val = stage_metrics.get(key)
        if val:
            meta[key] = round(val / count, 6) if key == "cost" else val // count

    # Model and run_id are the same for all tasks (not split)
    model = stage_metrics.get("model", "")
    if model:
        meta["model"] = model
    run_id = stage_metrics.get("run_id", "")
    if run_id:
        meta["run_id"] = run_id

    for tid in task_ids:
        try:
            update: dict[str, Any] = {"meta": meta}
            update["labels"] = [f"stage:{stage_name}"]
            tix.task_update(tid, update)
        except (TixError, Exception):
            pass  # best-effort


def reconcile_build(
    tix: TixProtocol,
    agent_output: str,
    task_id: str,
    stage_metrics: Optional[dict[str, Any]] = None,
    spec_name: str = "",
) -> ReconcileResult:
    """Reconcile BUILD stage output.

    Expected agent output schema:
    {
        "verdict": "done" | "blocked",
        "issues": [{"desc": "..."}],       // optional, discovered issues
        "summary": "what was done"          // optional
    }

    Args:
        tix: Tix harness instance.
        agent_output: Full agent stdout.
        task_id: The task ID that was being built.
        stage_metrics: Optional telemetry dict with keys like cost,
            tokens_in, tokens_out, iterations, model, retries, kill_count.
        spec_name: Spec this build belongs to (stamped on any new tasks).

    Returns:
        ReconcileResult with actions taken.
    """
    result = ReconcileResult()
    data, repairs = _extract_and_repair(agent_output, "build")

    if data is None:
        # No structured output — check if agent exited cleanly
        # Conservative: don't mark done without explicit verdict
        result.errors.append("No structured output from agent")
        result.ok = False
        return result

    if repairs:
        for repair in repairs:
            print(f"  Schema repair: {repair}", file=sys.stderr)

    verdict = data.get("verdict", "")

    if verdict == "done":
        try:
            tix.task_done(task_id)
            result.tasks_added.clear()  # no-op, just for clarity
        except TixError as e:
            result.errors.append(f"Failed to mark task done: {e}")
            result.ok = False

        # Attach telemetry and stage label to the ticket
        if stage_metrics and result.ok:
            try:
                meta = {
                    k: v for k, v in stage_metrics.items()
                    if k in ("cost", "tokens_in", "tokens_cached",
                             "tokens_out", "iterations", "model", "run_id")
                }
                update: dict[str, Any] = {"meta": meta}
                update["labels"] = ["stage:build"]
                tix.task_update(task_id, update)
            except TixError:
                pass  # best-effort; don't fail the build over telemetry

    elif verdict == "blocked":
        # Task could not be completed — log why
        reason = data.get("reason", "Agent reported task blocked")
        result.errors.append(f"Task blocked: {reason}")
        result.ok = False

    else:
        result.errors.append(f"Unknown verdict: {verdict!r}")
        result.ok = False

    # Process discovered issues
    _add_issues(tix, data.get("issues", []), result, spec_name=spec_name)

    return result


def reconcile_verify(
    tix: TixProtocol,
    agent_output: str,
    stage_metrics: Optional[dict[str, Any]] = None,
    spec_name: str = "",
) -> ReconcileResult:
    """Reconcile VERIFY stage output.

    Expected agent output schema:
    {
        "results": [
            {"task_id": "t-xxx", "passed": true},
            {"task_id": "t-yyy", "passed": false, "reason": "diagnostic..."}
        ],
        "issues": [{"desc": "...", "priority": "high"}],
        "spec_complete": true | false,
        "new_tasks": [{"name": "...", "notes": "...", "accept": "..."}]
    }

    VERIFY is the primary source of issues. It sees all failures and can
    synthesize cross-cutting patterns (e.g., multiple tasks failing for the
    same root cause). Issues are investigated in the next INVESTIGATE stage.

    Args:
        tix: Tix harness instance.
        agent_output: Full agent stdout.
        stage_metrics: Optional telemetry dict (cost, tokens, model, etc.).
        spec_name: Spec this verify belongs to (stamped on any new tasks).

    Returns:
        ReconcileResult with accept/reject actions taken.
    """
    result = ReconcileResult()
    data, repairs = _extract_and_repair(agent_output, "verify")

    if data is None:
        result.errors.append("No structured output from agent")
        result.ok = False
        return result

    if repairs:
        for repair in repairs:
            print(f"  Schema repair: {repair}", file=sys.stderr)

    # Process task verdicts
    for item in data.get("results", []):
        task_id = item.get("task_id", "")
        passed = item.get("passed", False)

        if not task_id:
            result.errors.append("Verify result missing task_id")
            continue

        if passed:
            _accept_task(tix, task_id, result)
        else:
            reason = item.get("reason", "Failed verification")
            _reject_task(tix, task_id, reason, result)

    # Attach verify-stage telemetry to each verified task (best-effort).
    # This accumulates with BUILD telemetry already on the ticket.
    if stage_metrics:
        verified_ids = result.tasks_accepted + result.tasks_rejected
        _attach_stage_telemetry(tix, verified_ids, stage_metrics, "verify")

    # Process cross-cutting issues surfaced by VERIFY
    _add_issues(tix, data.get("issues", []), result, spec_name=spec_name)

    # Process new tasks from uncovered spec criteria
    for task_data in data.get("new_tasks", []):
        _add_task(tix, task_data, result, spec_name=spec_name)

    return result


def reconcile_investigate(
    tix: TixProtocol,
    agent_output: str,
    batch_issue_ids: Optional[list[str]] = None,
    stage_metrics: Optional[dict[str, Any]] = None,
    spec_name: str = "",
) -> ReconcileResult:
    """Reconcile INVESTIGATE stage output.

    Expected agent output schema:
    {
        "tasks": [
            {"name": "...", "notes": "...", "accept": "...", "priority": "..."},
            ...
        ],
        "out_of_scope": ["i-xxx"],    // optional
        "summary": "..."              // optional
    }

    After creating tasks, only the issues in the current batch are cleared.
    This is batch-aware: issues outside the batch are preserved for the
    next batch iteration.

    Task dedup: proposed tasks are checked against existing pending tasks
    by exact name match.  If a match is found, the existing task is updated
    (upsert) instead of creating a duplicate.  This prevents the common
    VERIFY-reject -> INVESTIGATE -> duplicate-task proliferation loop.

    Args:
        tix: Tix harness instance.
        agent_output: Full agent stdout.
        batch_issue_ids: Issue IDs in the current batch to clear.
            If None, clears all issues (legacy fallback).
        stage_metrics: Optional telemetry dict (cost, tokens, model, etc.).
        spec_name: Spec this investigation belongs to (stamped on new tasks).

    Returns:
        ReconcileResult with tasks added and issues cleared.
    """
    result = ReconcileResult()
    data, repairs = _extract_and_repair(agent_output, "investigate")

    if data is None:
        result.errors.append("No structured output from agent")
        result.ok = False
        return result

    if repairs:
        for repair in repairs:
            print(f"  Schema repair: {repair}", file=sys.stderr)

    # Add investigation tasks with dedup against existing pending tasks.
    # INVESTIGATE often proposes tasks that duplicate already-pending work
    # (e.g., a rejected task goes back to pending, then INVESTIGATE creates
    # a new near-identical task for the same issue).  Use exact-match upsert
    # like reconcile_plan does for validation retries.
    existing_map = _get_existing_task_map(tix)
    seen_names: set[str] = set()

    for task_data in data.get("tasks", []):
        name = task_data.get("name", "")

        # Deduplicate within this batch
        if name and name in seen_names:
            continue
        if name:
            seen_names.add(name)

        # Upsert: if task with same name already pending, update it.
        # Semantic dedup (LLM-based) runs after reconcile via the state
        # machine's _deduplicate_tasks — this is just exact-match.
        existing_id = existing_map.get(name) if name else None
        if existing_id:
            _upsert_task(tix, existing_id, task_data, result)
            continue

        _add_task(tix, task_data, result, spec_name=spec_name)

    # Attach investigate-stage telemetry to newly created tasks (best-effort).
    if stage_metrics and result.tasks_added:
        _attach_stage_telemetry(tix, result.tasks_added, stage_metrics, "investigate")

    # Clear only the batch's issues (or all if no batch specified)
    try:
        if batch_issue_ids:
            tix.issue_done_ids(batch_issue_ids)
            result.issues_cleared = len(batch_issue_ids)
        else:
            tix.issue_done_all()
            result.issues_cleared = len(data.get("tasks", [])) + len(
                data.get("out_of_scope", [])
            )
    except TixError:
        # No issues to clear is fine
        pass

    return result


def reconcile_decompose(
    tix: TixProtocol,
    agent_output: str,
    original_task_id: str,
    parent_depth: int = 0,
    stage_metrics: Optional[dict[str, Any]] = None,
    spec_name: str = "",
) -> ReconcileResult:
    """Reconcile DECOMPOSE stage output.

    Expected agent output schema:
    {
        "subtasks": [
            {"name": "...", "notes": "...", "accept": "...", "deps": [...]},
            ...
        ]
    }

    Creates subtasks with parent link and incremented decompose_depth,
    then deletes original task.

    Args:
        tix: Tix harness instance.
        agent_output: Full agent stdout.
        original_task_id: The task being decomposed.
        parent_depth: Decompose depth of the parent task.
        stage_metrics: Optional telemetry dict (cost, tokens, model, etc.).
        spec_name: Spec this decompose belongs to (stamped on subtasks).

    Returns:
        ReconcileResult with subtasks added and original deleted.
    """
    result = ReconcileResult()
    data, repairs = _extract_and_repair(agent_output, "decompose")

    if data is None:
        result.errors.append("No structured output from agent")
        result.ok = False
        return result

    if repairs:
        for repair in repairs:
            print(f"  Schema repair: {repair}", file=sys.stderr)

    subtasks = data.get("subtasks", [])
    if not subtasks:
        result.errors.append("No subtasks in decompose output")
        result.ok = False
        return result

    # Cap subtask count to prevent task proliferation.  Weaker models
    # sometimes generate 10-15 tiny subtasks when 3-5 would suffice.
    max_subtasks = 5
    if len(subtasks) > max_subtasks:
        print(f"  Warning: capping {len(subtasks)} subtasks to {max_subtasks}",
              file=sys.stderr)
        subtasks = subtasks[:max_subtasks]

    # Add each subtask with parent link and incremented depth
    child_depth = parent_depth + 1
    for task_data in subtasks:
        task_data["parent"] = original_task_id
        task_data["decompose_depth"] = child_depth
        _add_task(tix, task_data, result, spec_name=spec_name)

    # Attach decompose-stage telemetry to subtasks (best-effort).
    if stage_metrics and result.tasks_added:
        _attach_stage_telemetry(tix, result.tasks_added, stage_metrics, "decompose")

    # Delete original task (only if subtasks were added)
    if result.tasks_added:
        try:
            tix.task_delete(original_task_id)
            result.tasks_deleted.append(original_task_id)
        except TixError as e:
            result.errors.append(f"Failed to delete original task: {e}")

    return result


def reconcile_plan(
    tix: TixProtocol,
    agent_output: str,
    spec_name: str,
) -> ReconcileResult:
    """Reconcile PLAN stage output — incremental add/drop.

    Expected agent output schema:
    {
        "tasks": [
            {"name": "...", "notes": "...", "accept": "...", "deps": [...]},
            ...
        ],
        "drop": ["t-abc123", ...]  // optional: IDs of obsolete tasks to remove
    }

    The agent only outputs NEW tasks to add. Existing pending tasks that
    the agent wants to keep are simply omitted from output. Tasks the
    agent wants to remove are listed in the "drop" array.

    Args:
        tix: Tix harness instance.
        agent_output: Full agent stdout.
        spec_name: The spec file being planned.

    Returns:
        ReconcileResult with tasks added and dropped.
    """
    result = ReconcileResult()
    data, repairs = _extract_and_repair(agent_output, "plan")

    if data is None:
        result.errors.append("No structured output from agent")
        result.ok = False
        return result

    if repairs:
        for repair in repairs:
            print(f"  Schema repair: {repair}", file=sys.stderr)

    raw_tasks = data.get("tasks", [])
    drop_ids = data.get("drop", [])

    # Drop obsolete tasks first (so IDs don't conflict with new tasks)
    for task_id in drop_ids:
        if not isinstance(task_id, str) or not task_id:
            continue
        try:
            tix.task_delete(task_id)
            result.tasks_deleted.append(task_id)
        except TixError as e:
            result.errors.append(f"Failed to drop {task_id}: {e}")

    # Allow plans with only drops and no new tasks
    if not raw_tasks and not drop_ids:
        result.errors.append("No tasks or drops in plan output")
        result.ok = False
        return result

    # Build map of existing task names for upsert detection.
    # Validation retries often re-emit previously accepted tasks with
    # improved notes/accept — update in place rather than duplicating.
    existing_map = _get_existing_task_map(tix)
    seen_names: set[str] = set()

    # Validate and filter tasks before adding.
    # PLAN runs on the expensive reasoning model — bad tasks waste
    # downstream BUILD and VERIFY calls. Strict validation here ensures
    # every task has targeted acceptance criteria that the pre-check
    # harness can auto-execute, avoiding expensive VERIFY agent calls.
    tasks_to_add = []
    for task_data in raw_tasks:
        if not task_data.get("name"):
            result.errors.append("Task missing name field")
            continue

        name = task_data.get("name", "")
        notes = task_data.get("notes", "")
        accept = task_data.get("accept", "")

        # Deduplicate within this batch
        if name in seen_names:
            continue
        seen_names.add(name)

        vr = validate_task(name, notes, accept, is_modification=True, strict=True)
        if not vr.valid:
            reasons = "; ".join(e.message for e in vr.errors)
            result.errors.append(f"PLAN task '{name}' rejected by validation: {reasons}")
            continue

        # Sanitize deps before sending to tix
        if "deps" in task_data:
            task_data["deps"] = _sanitize_deps(task_data["deps"], result)

        # Upsert: if task with same name exists, update it
        existing_id = existing_map.get(name)
        if existing_id:
            _upsert_task(tix, existing_id, task_data, result)
            continue

        task_data["spec"] = spec_name
        task_data.setdefault("assigned", "ralph")
        tasks_to_add.append(task_data)

    if tasks_to_add:
        # Batch add via tix (single subprocess call)
        try:
            added = tix.task_batch_add(tasks_to_add)
            for resp in added:
                task_id = resp.get("id", "")
                if task_id:
                    result.tasks_added.append(task_id)
        except TixError as e:
            result.errors.append(f"Batch add failed: {e}")
            # Fallback: try individual adds
            for task_data in tasks_to_add:
                _add_task(tix, task_data, result)

    return result


# =============================================================================
# Helpers
# =============================================================================


def _token_similarity(a: str, b: str) -> float:
    """Jaccard similarity over word tokens (case-insensitive).

    Returns a score between 0.0 and 1.0.  Used by reconcile_investigate
    to detect near-duplicate tasks (e.g. "Complete heap rename across
    all files" vs "Complete heap rename across all source files").
    """
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _find_similar_task(
    name: str,
    existing_map: dict[str, str],
    threshold: float = 0.7,
) -> Optional[str]:
    """Find an existing pending task with a similar name.

    Returns the task ID if a match is found above the threshold, else None.
    Uses Jaccard token similarity — the same approach as issue dedup in
    the state machine.
    """
    if not name:
        return None
    for existing_name, task_id in existing_map.items():
        if _token_similarity(name, existing_name) >= threshold:
            return task_id
    return None

# =============================================================================
# LLM-based task deduplication
# =============================================================================

# Type alias for the LLM callback used by dedup_tasks.
# Takes a prompt string, returns the model's output string (or None on failure).
LlmCallable = Callable[[str], Optional[str]]


def _build_dedup_prompt(tasks: list[dict]) -> str:
    """Build a prompt asking the model to deduplicate the task list.

    The prompt is self-contained — no codebase context needed.  The model
    sees task IDs, names, and truncated notes, and returns which IDs to
    keep (choosing the best version of each duplicate group).
    """
    task_lines = []
    for t in tasks:
        tid = t.get("id", "?")
        name = t.get("name", "untitled")
        notes = t.get("notes", "")
        short_notes = notes[:120] + "..." if len(notes) > 120 else notes
        task_lines.append(f"- [{tid}] {name}")
        if short_notes:
            task_lines.append(f"  Notes: {short_notes}")
    task_block = "\n".join(task_lines)

    return (
        "Review this task list and remove duplicates.  Some tasks describe "
        "the same work with slightly different names (e.g. different "
        "line-range formats, minor wording changes, or rephrased "
        "descriptions of the same operation).\n\n"
        f"## Tasks ({len(tasks)} total)\n\n"
        f"{task_block}\n\n"
        "## Instructions\n\n"
        "For each group of duplicate tasks, keep the ONE with the best/"
        "most detailed name and notes.\n"
        "Do NOT modify task names or notes — just choose which IDs to keep.\n"
        "Do NOT remove tasks that target different files or different "
        "operations, even if they sound similar.\n\n"
        "Output your answer inside [RALPH_OUTPUT] markers:\n\n"
        "[RALPH_OUTPUT]\n"
        '{"keep": ["t-id1", "t-id2", ...], '
        '"dropped": ["t-id3", "t-id4", ...]}\n'
        "[/RALPH_OUTPUT]\n\n"
        'The "keep" array must contain every task ID that should remain.\n'
        'The "dropped" array contains IDs that are duplicates and should '
        "be removed.\n"
        "Every task ID must appear in exactly one of the two arrays.\n"
    )


def dedup_tasks(
    tix: TixProtocol,
    llm_fn: LlmCallable,
    min_tasks: int = 8,
) -> int:
    """Ask the LLM to deduplicate the pending task list.

    Sends just task IDs + names + truncated notes to the model.  The
    model returns keep/drop decisions.  Safety checks reject obviously
    bad results (empty keep list, >50% dropped, contradictory IDs).

    This is used after PLAN retries and after INVESTIGATE creates new
    tasks — any time the pending queue may have accumulated duplicates.

    Args:
        tix: Tix harness instance.
        llm_fn: Callable that takes a prompt string and returns the
            model's output string, or None on failure.
        min_tasks: Skip dedup if fewer than this many tasks.

    Returns:
        Number of tasks dropped.
    """
    tasks = tix.query_tasks()
    if len(tasks) <= min_tasks:
        return 0

    prompt = _build_dedup_prompt(tasks)
    output_str = llm_fn(prompt)
    if output_str is None:
        print("  Dedup pass: no output from model", file=sys.stderr)
        return 0

    data = extract_structured_output(output_str)
    if data is None:
        print("  Dedup pass: could not parse output", file=sys.stderr)
        return 0

    keep_ids = set(data.get("keep", []))
    dropped_ids = data.get("dropped", [])

    if not keep_ids:
        return 0

    # Sanity check: keep list should contain most tasks
    task_ids = {t.get("id") for t in tasks}
    if len(keep_ids) < len(task_ids) * 0.5:
        print(
            f"  Dedup pass: keep list too small "
            f"({len(keep_ids)}/{len(task_ids)}), skipping",
            file=sys.stderr,
        )
        return 0

    dropped = 0
    for tid in dropped_ids:
        if not isinstance(tid, str) or not tid:
            continue
        if tid not in task_ids:
            continue
        if tid in keep_ids:
            continue  # Contradictory
        try:
            tix.task_delete(tid)
            dropped += 1
        except TixError:
            pass

    return dropped


# Regex for valid tix task IDs: "t-" followed by hex chars.
_VALID_TASK_ID_RE = re.compile(r"^t-[0-9a-f]+$")


def _get_existing_task_map(tix: TixProtocol) -> dict[str, str]:
    """Get mapping of task name -> task ID for existing pending tasks.

    Used by reconcile_plan (validation retries) and reconcile_investigate
    (reject-investigate loops) to upsert tasks instead of duplicating.
    """
    try:
        tasks = tix.query_tasks()
        return {
            t["name"]: t["id"]
            for t in tasks
            if t.get("name") and t.get("id")
        }
    except TixError:
        return {}


def _upsert_task(
    tix: TixProtocol,
    task_id: str,
    task_data: dict,
    result: ReconcileResult,
) -> None:
    """Update an existing task with improved notes/accept from a retry.

    Validation retries re-emit tasks with better details. Rather than
    adding duplicates, update the existing task in place.
    """
    fields: dict[str, str] = {}
    if task_data.get("notes"):
        fields["notes"] = task_data["notes"]
    if task_data.get("accept"):
        fields["accept"] = task_data["accept"]
    if not fields:
        return
    try:
        tix.task_update(task_id, fields)
    except TixError as e:
        result.errors.append(f"Failed to update {task_id}: {e}")


def _sanitize_deps(deps: Any, result: ReconcileResult) -> list[str]:
    """Filter deps to only valid tix task IDs (``t-<hex>``).

    Weaker models emit task *names* instead of IDs, or use object
    references like ``{"name": "..."}``.  We silently drop those and
    warn via result.errors so the task can still be created.

    Args:
        deps: Raw deps value from agent output (may be list, None, etc.).
        result: ReconcileResult to append warnings to.

    Returns:
        List of valid task ID strings.
    """
    if not deps or not isinstance(deps, list):
        return []
    valid: list[str] = []
    for dep in deps:
        if isinstance(dep, str) and _VALID_TASK_ID_RE.match(dep):
            valid.append(dep)
        else:
            # Don't fail — just drop the bad dep and warn
            desc = repr(dep) if not isinstance(dep, str) else dep[:60]
            result.errors.append(f"Dropped invalid dep: {desc}")
    return valid


def _add_task(
    tix: TixProtocol,
    task_data: dict,
    result: ReconcileResult,
    spec_name: str = "",
) -> None:
    """Add a single task via tix, updating result.

    Validates the task before adding. Invalid tasks are rejected
    programmatically to prevent wasting BUILD cycles on bad tasks.
    """
    name = task_data.get("name", "")
    if not name:
        result.errors.append("Task missing name field")
        return

    # Sanitize deps before sending to tix
    if "deps" in task_data:
        task_data["deps"] = _sanitize_deps(task_data["deps"], result)

    # Validate task quality before adding (non-strict to allow decompose subtasks)
    notes = task_data.get("notes", "")
    accept = task_data.get("accept", "")
    vr = validate_task(name, notes, accept, is_modification=True, strict=False)
    if not vr.valid:
        reasons = "; ".join(e.message for e in vr.errors)
        result.errors.append(f"Task '{name}' rejected by validation: {reasons}")
        return

    # Tag all tasks created by ralph so they can be filtered by assignee
    task_data.setdefault("assigned", "ralph")
    # Stamp spec so construct-mode queries can scope to the active spec
    if spec_name:
        task_data.setdefault("spec", spec_name)

    try:
        resp = tix.task_add(task_data)
        task_id = resp.get("id", "")
        if task_id:
            result.tasks_added.append(task_id)
    except TixError as e:
        result.errors.append(f"Failed to add task '{name}': {e}")


def _accept_task(tix: TixProtocol, task_id: str, result: ReconcileResult) -> None:
    """Accept a task via tix, updating result."""
    try:
        tix.task_accept(task_id)
        result.tasks_accepted.append(task_id)
    except TixError as e:
        result.errors.append(f"Failed to accept {task_id}: {e}")


def _reject_task(
    tix: TixProtocol, task_id: str, reason: str, result: ReconcileResult
) -> None:
    """Reject a task via tix, updating result.

    Also increments reject_count so the harness can detect stuck tasks.
    """
    try:
        tix.task_reject(task_id, reason)
        result.tasks_rejected.append(task_id)
    except TixError as e:
        result.errors.append(f"Failed to reject {task_id}: {e}")
        return

    _increment_reject_count(tix, task_id)


# Module-level reject counter for the current session.
# Persists to tix meta so TQL queries can aggregate retry counts.
# Reset per-process; the ConstructStateMachine's _retry_counts is
# the authoritative source for escalation decisions.
_reject_counts: dict[str, int] = {}


def _increment_reject_count(tix: TixProtocol, task_id: str) -> None:
    """Increment retries on a task for pattern detection.

    Writes the accumulated count to ``meta.retries`` in ticket_meta
    so TQL queries can aggregate retry counts (``sum meta.retries``).
    Best-effort: failure here does not affect reconciliation.
    """
    current = _reject_counts.get(task_id, 0) + 1
    _reject_counts[task_id] = current
    try:
        tix.task_update(task_id, {"meta": {"retries": current}})
    except (TixError, Exception):
        pass


def _add_issues(
    tix: TixProtocol,
    issues: list[dict],
    result: ReconcileResult,
    spec_name: str = "",
) -> None:
    """Add discovered issues via tix, updating result.

    Validates issue descriptions before adding. Too-short or empty
    descriptions are rejected to prevent noise in the issue queue.
    """
    for issue in issues:
        desc = issue.get("desc", "")
        if not desc:
            continue
        vr = validate_issue(desc)
        if not vr.valid:
            reasons = "; ".join(e.message for e in vr.errors)
            result.errors.append(f"Issue rejected by validation: {reasons}")
            continue
        try:
            resp = tix.issue_add(desc, spec=spec_name)
            issue_id = resp.get("id", "")
            if issue_id:
                result.issues_added.append(issue_id)
        except TixError as e:
            result.errors.append(f"Failed to add issue: {e}")
