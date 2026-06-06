#!/usr/bin/env python3
# /// script
# dependencies = [
#   "requests>=2.31,<3",
# ]
# requires-python = ">=3.9"
# ///
"""
Jira CLI — portable command-line interface for Jira REST API.

Reads credentials from ~/.config/jira-credentials.json.
Outputs structured JSON to stdout; diagnostics go to stderr.
Run with: uv run scripts/jira.py <subcommand> [options]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_PATH = Path.home() / ".config" / "jira-credentials.json"

_config: dict[str, Any] | None = None


def load_config() -> dict[str, Any]:
    """Load and cache Jira config from disk."""
    global _config
    if _config is not None:
        return _config

    if not CONFIG_PATH.exists():
        die(
            f"Config not found at {CONFIG_PATH}\n\n"
            "Create it with:\n\n"
            f"  cat > {CONFIG_PATH} << 'EOF'\n"
            "  {\n"
            '    "pat": "your-personal-access-token",\n'
            '    "base_url": "https://jira.creditkarma.com",\n'
            '    "project": "FAB",\n'
            '    "board_id": 1990\n'
            "  }\n"
            "  EOF\n"
            f"  chmod 600 {CONFIG_PATH}\n\n"
            "To create a PAT:\n"
            "1. Go to Jira > Profile > Personal Access Tokens\n"
            "2. Click 'Create token', name it, and copy the value",
            code=2,
        )

    try:
        raw = json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        die(f"Failed to read config at {CONFIG_PATH}: {exc}", code=2)
        return {}  # unreachable, satisfies type checker

    if not raw.get("pat"):
        die("Missing 'pat' field in config file", code=2)

    _config = {
        "pat": raw["pat"],
        "base_url": raw.get("base_url", "https://jira.creditkarma.com").rstrip("/"),
        "project": raw.get("project", "FAB"),
        "board_id": raw.get("board_id", 1990),
        "team_defaults": raw.get("team_defaults", {}),
    }
    return _config


def cfg(key: str) -> Any:
    return load_config()[key]


def team_defaults() -> dict[str, Any]:
    return load_config().get("team_defaults", {})


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def api_url(path: str = "") -> str:
    return f"{cfg('base_url')}/rest/api/2{path}"


def agile_url(path: str = "") -> str:
    return f"{cfg('base_url')}/rest/agile/1.0{path}"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {cfg('pat')}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def jira_get(url: str, params: dict | None = None) -> Any:
    r = requests.get(url, headers=_headers(), params=params, timeout=30)
    _check(r)
    return r.json() if r.status_code != 204 else {"success": True}


def jira_post(url: str, body: dict | list | None = None) -> Any:
    r = requests.post(url, headers=_headers(), json=body, timeout=30)
    _check(r)
    if r.status_code == 204 or not r.content:
        return {"success": True}
    return r.json()


def jira_put(url: str, body: dict | None = None) -> Any:
    r = requests.put(url, headers=_headers(), json=body, timeout=30)
    _check(r)
    if r.status_code == 204 or not r.content:
        return {"success": True}
    return r.json()


def _check(r: requests.Response) -> None:
    if not r.ok:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        die(f"Jira API error ({r.status_code}): {json.dumps(detail) if isinstance(detail, (dict, list)) else detail}", code=1)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def die(msg: str, code: int = 1) -> NoReturn:
    print(msg, file=sys.stderr)
    sys.exit(code)


def emit(data: Any, *, markdown: str | None = None, use_json: bool = False) -> None:
    """Print data.  --json flag → JSON on stdout, else markdown on stdout."""
    if use_json:
        print(json.dumps(data, indent=2, default=str))
    elif markdown is not None:
        print(markdown)
    else:
        print(json.dumps(data, indent=2, default=str))


def browse_url(key: str) -> str:
    return f"{cfg('base_url')}/browse/{key}"


# ---------------------------------------------------------------------------
# Formatting (markdown)
# ---------------------------------------------------------------------------


def fmt_issue(issue: dict, verbose: bool = False) -> str:
    f = issue.get("fields", {})
    key = issue["key"]
    summary = f.get("summary", "No summary")
    status = (f.get("status") or {}).get("name", "Unknown")
    assignee = (f.get("assignee") or {}).get("displayName", "Unassigned")
    reporter = (f.get("reporter") or {}).get("displayName", "Unknown")
    priority = (f.get("priority") or {}).get("name", "None")
    itype = (f.get("issuetype") or {}).get("name", "Unknown")
    created = _short_date(f.get("created"))
    updated = _short_date(f.get("updated"))
    labels = ", ".join(f.get("labels") or []) or "None"
    components = ", ".join(c["name"] for c in (f.get("components") or [])) or "None"
    sprint_obj = f.get("sprint") or (f.get("customfield_10007") or [None])[0] if isinstance(f.get("customfield_10007"), list) else f.get("sprint")
    sprint = sprint_obj["name"] if isinstance(sprint_obj, dict) and "name" in sprint_obj else "None"
    sp = f.get("story_points") or f.get("customfield_10004") or "N/A"

    lines = [
        f"### [{key}]({browse_url(key)}) -- {summary}",
        f"- **Type:** {itype} | **Status:** {status} | **Priority:** {priority}",
        f"- **Assignee:** {assignee} | **Reporter:** {reporter}",
        f"- **Labels:** {labels} | **Components:** {components}",
        f"- **Sprint:** {sprint} | **Story Points:** {sp}",
        f"- **Created:** {created} | **Updated:** {updated}",
    ]

    if verbose and f.get("description"):
        lines.append(f"\n**Description:**\n{f['description']}")

    if verbose:
        comments = (f.get("comment") or {}).get("comments", [])
        if comments:
            lines.append(f"\n**Comments ({len(comments)}):**")
            for c in comments[-5:]:
                author = (c.get("author") or {}).get("displayName", "Unknown")
                date = _short_date(c.get("created"))
                body = (c.get("body") or "").replace("\n", "\n> ")
                lines.append(f"\n> **{author}** ({date}):\n> {body}")

    return "\n".join(lines)


def _short_date(iso: str | None) -> str:
    if not iso:
        return "Unknown"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except Exception:
        return iso[:10] if len(iso) >= 10 else iso


# ---------------------------------------------------------------------------
# Standard field sets
# ---------------------------------------------------------------------------

SUMMARY_FIELDS = [
    "summary", "status", "assignee", "priority", "issuetype",
    "labels", "created", "updated", "reporter",
    "customfield_10004", "customfield_10007",
]

DETAIL_FIELDS = SUMMARY_FIELDS + [
    "description", "components", "sprint", "story_points",
    "fixVersions", "parent", "subtasks", "issuelinks", "comment",
]


# ===========================================================================
# Subcommands
# ===========================================================================


def cmd_get_issue(args: argparse.Namespace) -> None:
    fields = list(DETAIL_FIELDS)
    if not args.include_comments and "comment" in fields:
        fields.remove("comment")
    params = {"fields": ",".join(fields)}
    data = jira_get(api_url(f"/issue/{args.issue_key}"), params=params)

    md = fmt_issue(data, verbose=True)

    # Subtasks
    subtasks = (data.get("fields") or {}).get("subtasks") or []
    if subtasks:
        md += "\n\n**Subtasks:**"
        for s in subtasks:
            sf = s.get("fields", {})
            md += f"\n- [{s['key']}] {sf.get('summary', '')} ({(sf.get('status') or {}).get('name', '')})"

    # Linked issues
    links = (data.get("fields") or {}).get("issuelinks") or []
    if links:
        md += "\n\n**Linked Issues:**"
        for lnk in links:
            if lnk.get("outwardIssue"):
                o = lnk["outwardIssue"]
                md += f"\n- {(lnk.get('type') or {}).get('outward', '')}: [{o['key']}] {(o.get('fields') or {}).get('summary', '')}"
            if lnk.get("inwardIssue"):
                i = lnk["inwardIssue"]
                md += f"\n- {(lnk.get('type') or {}).get('inward', '')}: [{i['key']}] {(i.get('fields') or {}).get('summary', '')}"

    # Parent
    parent = (data.get("fields") or {}).get("parent")
    if parent:
        md += f"\n\n**Parent:** [{parent['key']}] {(parent.get('fields') or {}).get('summary', '')}"

    emit(data, markdown=md, use_json=args.json)


def cmd_search(args: argparse.Namespace) -> None:
    field_list = args.fields.split(",") if args.fields else SUMMARY_FIELDS
    body = {
        "jql": args.jql,
        "maxResults": min(args.max_results, 50),
        "fields": [f.strip() for f in field_list],
    }
    data = jira_post(api_url("/search"), body)

    issues = data.get("issues", [])
    if not issues:
        emit(data, markdown=f"No issues found for JQL: `{args.jql}`", use_json=args.json)
        return

    md_parts = [f"## Jira Search Results ({data.get('total', 0)} total, showing {len(issues)})", f"**JQL:** `{args.jql}`\n"]
    md_parts.extend(fmt_issue(iss) for iss in issues)

    emit(data, markdown="\n\n".join(md_parts), use_json=args.json)


def cmd_create_issue(args: argparse.Namespace) -> None:
    td = team_defaults()
    fields: dict[str, Any] = {
        "project": {"key": args.project or cfg("project")},
        "issuetype": {"name": args.type},
        "summary": args.summary,
    }

    # Labels: team default + extras
    label_set: set[str] = set()
    if not args.skip_team_defaults and td.get("label"):
        label_set.add(td["label"])
    if args.labels:
        label_set.update(l.strip() for l in args.labels.split(",") if l.strip())
    if label_set:
        fields["labels"] = sorted(label_set)

    # Scrum team
    if not args.skip_team_defaults and td.get("scrum_team_field") and td.get("scrum_team_option_id"):
        fields[td["scrum_team_field"]] = {"id": td["scrum_team_option_id"]}

    # Epic link
    if args.epic_link and td.get("epic_link_field"):
        fields[td["epic_link_field"]] = args.epic_link

    if args.description:
        fields["description"] = args.description
    if args.assignee:
        fields["assignee"] = {"name": args.assignee}
    if args.priority:
        fields["priority"] = {"name": args.priority}
    if args.components:
        fields["components"] = [{"name": c.strip()} for c in args.components.split(",") if c.strip()]
    if args.parent:
        fields["parent"] = {"key": args.parent}
    if args.story_points is not None:
        fields["customfield_10004"] = args.story_points

    data = jira_post(api_url("/issue"), {"fields": fields})

    key = data.get("key", "???")
    applied = []
    if not args.skip_team_defaults and td.get("label"):
        applied.append(f"label: {td['label']}")
    if not args.skip_team_defaults and td.get("scrum_team_field"):
        applied.append(f"scrum team: {td.get('scrum_team_value', 'configured')}")
    if args.epic_link:
        applied.append(f"epic: {args.epic_link}")

    md = f"Issue created: **[{key}]({browse_url(key)})** -- {args.summary}"
    if applied:
        md += f"\n\nTeam defaults applied: {', '.join(applied)}"
    md += f"\n\nTo add to the current sprint:\n  uv run scripts/jira.py add-to-sprint {key}"

    emit(data, markdown=md, use_json=args.json)


def cmd_update_issue(args: argparse.Namespace) -> None:
    fields: dict[str, Any] = {}
    if args.summary is not None:
        fields["summary"] = args.summary
    if args.description is not None:
        fields["description"] = args.description
    if args.assignee is not None:
        fields["assignee"] = None if args.assignee == "" else {"name": args.assignee}
    if args.priority is not None:
        fields["priority"] = {"name": args.priority}
    if args.labels is not None:
        fields["labels"] = [l.strip() for l in args.labels.split(",") if l.strip()]
    if args.components is not None:
        fields["components"] = [{"name": c.strip()} for c in args.components.split(",") if c.strip()]
    if args.story_points is not None:
        fields["customfield_10004"] = args.story_points

    if not fields:
        die("No fields to update. Provide at least one field to change.")

    jira_put(api_url(f"/issue/{args.issue_key}"), {"fields": fields})

    md = f"Issue **{args.issue_key}** updated successfully.\n\nUpdated fields: {', '.join(fields.keys())}"
    emit({"success": True, "key": args.issue_key, "updated": list(fields.keys())}, markdown=md, use_json=args.json)


def cmd_transition_issue(args: argparse.Namespace) -> None:
    data = jira_get(api_url(f"/issue/{args.issue_key}/transitions"))
    transitions = data.get("transitions", [])

    match = None
    for t in transitions:
        if (t.get("name", "").lower() == args.status.lower() or
                (t.get("to") or {}).get("name", "").lower() == args.status.lower()):
            match = t
            break

    if match is None:
        avail = ", ".join(f'"{t["name"]}" -> {(t.get("to") or {}).get("name", "?")}' for t in transitions)
        die(f'Cannot transition to "{args.status}". Available transitions: {avail}')

    assert match is not None  # for type checker (die() is NoReturn)
    body: dict[str, Any] = {"transition": {"id": match["id"]}}
    if args.comment:
        body["update"] = {"comment": [{"add": {"body": args.comment}}]}

    jira_post(api_url(f"/issue/{args.issue_key}/transitions"), body)

    target = (match.get("to") or {}).get("name", args.status)
    md = f'Issue **{args.issue_key}** transitioned to **{target}**{"  with comment" if args.comment else ""}.'
    emit({"success": True, "key": args.issue_key, "status": target}, markdown=md, use_json=args.json)


def cmd_add_comment(args: argparse.Namespace) -> None:
    data = jira_post(api_url(f"/issue/{args.issue_key}/comment"), {"body": args.body})
    author = (data.get("author") or {}).get("displayName", "you")
    md = f"Comment added to **{args.issue_key}** by {author}."
    emit(data, markdown=md, use_json=args.json)


def cmd_assign_issue(args: argparse.Namespace) -> None:
    name: Any = None if args.assignee == "" else args.assignee
    jira_put(api_url(f"/issue/{args.issue_key}/assignee"), {"name": name})

    if name is None:
        md = f"Issue **{args.issue_key}** unassigned."
    else:
        md = f"Issue **{args.issue_key}** assigned to **{args.assignee}**."
    emit({"success": True, "key": args.issue_key, "assignee": name}, markdown=md, use_json=args.json)


# ---- Board & Sprint -------------------------------------------------------


def cmd_add_to_sprint(args: argparse.Namespace) -> None:
    sprint_id = args.sprint_id
    if sprint_id is None:
        board_id = cfg("board_id")
        data = jira_get(agile_url(f"/board/{board_id}/sprint"), params={"state": "active"})
        sprints = data.get("values", [])
        if not sprints:
            die(f"No active sprint found for board {board_id}. Provide --sprint-id manually.")
        sprint_id = sprints[0]["id"]
        print(f"Using active sprint: {sprints[0].get('name', sprint_id)} (id={sprint_id})", file=sys.stderr)

    jira_post(agile_url(f"/sprint/{sprint_id}/issue"), {"issues": [args.issue_key]})
    md = f"Issue **{args.issue_key}** added to sprint {sprint_id}."
    emit({"success": True, "key": args.issue_key, "sprint_id": sprint_id}, markdown=md, use_json=args.json)


def cmd_get_board(args: argparse.Namespace) -> None:
    board_id = args.board_id or cfg("board_id")
    data = jira_get(agile_url(f"/board/{board_id}"))
    loc = data.get("location") or {}
    md = (
        f"## Board: {data.get('name', '?')}\n"
        f"- **ID:** {data.get('id')}\n"
        f"- **Type:** {data.get('type', '?')}\n"
        f"- **Project:** {loc.get('projectKey', 'N/A')} -- {loc.get('displayName', 'N/A')}"
    )
    emit(data, markdown=md, use_json=args.json)


def cmd_get_sprints(args: argparse.Namespace) -> None:
    board_id = args.board_id or cfg("board_id")
    data = jira_get(agile_url(f"/board/{board_id}/sprint"), params={"state": args.state})
    sprints = data.get("values", [])
    if not sprints:
        emit(data, markdown="No sprints found.", use_json=args.json)
        return

    parts = [f"## Sprints for Board {board_id}\n"]
    for s in sprints:
        start = _short_date(s.get("startDate"))
        end = _short_date(s.get("endDate"))
        parts.append(
            f"### Sprint: {s.get('name', '?')}\n"
            f"- **ID:** {s['id']} | **State:** {s.get('state', '?')}\n"
            f"- **Start:** {start} | **End:** {end}\n"
            f"- **Goal:** {s.get('goal') or 'None'}"
        )
    emit(data, markdown="\n\n".join(parts), use_json=args.json)


def cmd_get_sprint_issues(args: argparse.Namespace) -> None:
    params = {
        "maxResults": str(min(args.max_results, 50)),
        "fields": ",".join(SUMMARY_FIELDS),
    }
    data = jira_get(agile_url(f"/sprint/{args.sprint_id}/issue"), params=params)
    issues = data.get("issues", [])
    if not issues:
        emit(data, markdown=f"No issues found in sprint {args.sprint_id}.", use_json=args.json)
        return

    # Group by status
    by_status: dict[str, list] = {}
    for iss in issues:
        st = ((iss.get("fields") or {}).get("status") or {}).get("name", "Unknown")
        by_status.setdefault(st, []).append(iss)

    parts = [f"## Sprint Issues ({data.get('total', len(issues))} total)"]
    for status, items in by_status.items():
        parts.append(f"\n### {status} ({len(items)})\n")
        parts.extend(fmt_issue(i) for i in items)

    emit(data, markdown="\n\n".join(parts), use_json=args.json)


def cmd_get_backlog(args: argparse.Namespace) -> None:
    board_id = args.board_id or cfg("board_id")
    params = {
        "maxResults": str(min(args.max_results, 50)),
        "fields": ",".join(SUMMARY_FIELDS),
    }
    data = jira_get(agile_url(f"/board/{board_id}/backlog"), params=params)
    issues = data.get("issues", [])
    if not issues:
        emit(data, markdown="Backlog is empty.", use_json=args.json)
        return

    parts = [f"## Backlog ({data.get('total', len(issues))} total, showing {len(issues)})\n"]
    parts.extend(fmt_issue(i) for i in issues)
    emit(data, markdown="\n\n".join(parts), use_json=args.json)


# ---- User & Metadata ------------------------------------------------------


def cmd_get_myself(args: argparse.Namespace) -> None:
    data = jira_get(api_url("/myself"))
    md = (
        f"## Authenticated User\n"
        f"- **Username:** {data.get('name', '?')}\n"
        f"- **Display Name:** {data.get('displayName', '?')}\n"
        f"- **Email:** {data.get('emailAddress', '?')}\n"
        f"- **Active:** {data.get('active', '?')}\n"
        f"- **Timezone:** {data.get('timeZone', '?')}"
    )
    emit(data, markdown=md, use_json=args.json)


def cmd_get_project(args: argparse.Namespace) -> None:
    project_key = args.project_key or cfg("project")
    data = jira_get(api_url(f"/project/{project_key}"))

    types = ", ".join(t["name"] for t in (data.get("issueTypes") or [])) or "None"
    comps = ", ".join(c["name"] for c in (data.get("components") or [])) or "None"
    versions = ", ".join(
        f"{v['name']} ({'released' if v.get('released') else 'archived' if v.get('archived') else 'unreleased'})"
        for v in (data.get("versions") or [])
    ) or "None"

    md = (
        f"## Project: {data.get('name', '?')} ({data.get('key', '?')})\n"
        f"- **Lead:** {(data.get('lead') or {}).get('displayName', 'Unknown')}\n"
        f"- **Description:** {data.get('description') or 'None'}\n"
        f"- **Issue Types:** {types}\n"
        f"- **Components:** {comps}\n"
        f"- **Versions:** {versions}\n"
        f"- **URL:** {browse_url(data.get('key', ''))}"
    )
    emit(data, markdown=md, use_json=args.json)


def cmd_list_transitions(args: argparse.Namespace) -> None:
    data = jira_get(api_url(f"/issue/{args.issue_key}/transitions"))
    transitions = data.get("transitions", [])
    if not transitions:
        emit(data, markdown=f"No transitions available for {args.issue_key}.", use_json=args.json)
        return

    lines = [f"## Available Transitions for {args.issue_key}\n"]
    for t in transitions:
        to_name = (t.get("to") or {}).get("name", "?")
        lines.append(f"- **{t['name']}** -> {to_name} (ID: {t['id']})")
    emit(data, markdown="\n".join(lines), use_json=args.json)


def cmd_discover_fields(args: argparse.Namespace) -> None:
    data = jira_get(api_url(f"/issue/{args.issue_key}"))
    fields = data.get("fields", {})

    results: dict[str, Any] = {}
    for key, val in fields.items():
        if val is None:
            continue
        if not key.startswith("customfield_"):
            continue
        val_str = json.dumps(val, default=str)
        if args.filter and args.filter.lower() not in val_str.lower():
            continue
        results[key] = val

    if not results:
        label = f' matching "{args.filter}"' if args.filter else ""
        emit({}, markdown=f"No custom fields{label} with values found on {args.issue_key}.", use_json=args.json)
        return

    if args.json:
        emit(results, use_json=True)
    else:
        filt = f' (filter: "{args.filter}")' if args.filter else ""
        lines = [f"## Custom Fields on {args.issue_key}{filt}\n"]
        for k, v in results.items():
            s = json.dumps(v, default=str)
            if len(s) > 200:
                s = s[:200] + "..."
            lines.append(f"**{k}:** {s}\n")
        print("\n".join(lines))


def cmd_link_issues(args: argparse.Namespace) -> None:
    body: dict[str, Any] = {
        "type": {"name": args.type},
        "inwardIssue": {"key": args.inward_issue},
        "outwardIssue": {"key": args.outward_issue},
    }
    if args.comment:
        body["comment"] = {"body": args.comment}

    jira_post(api_url("/issueLink"), body)
    md = f"Link created: **{args.inward_issue}** {args.type} **{args.outward_issue}**"
    emit({"success": True, "type": args.type, "inward": args.inward_issue, "outward": args.outward_issue}, markdown=md, use_json=args.json)


# ===========================================================================
# CLI
# ===========================================================================


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jira.py",
        description="Portable Jira CLI for agent and human use. Reads config from ~/.config/jira-credentials.json.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # -- get-issue -----------------------------------------------------------
    gi = sub.add_parser("get-issue", help="Get detailed info about a Jira issue")
    gi.add_argument("issue_key", help="Issue key (e.g., FAB-1234)")
    gi.add_argument("--no-comments", dest="include_comments", action="store_false", default=True, help="Exclude comments")
    gi.add_argument("--json", action="store_true", help="Output raw JSON")
    gi.set_defaults(func=cmd_get_issue)

    # -- search --------------------------------------------------------------
    sr = sub.add_parser("search", help="Search issues with JQL")
    sr.add_argument("jql", help="JQL query string")
    sr.add_argument("--max-results", type=int, default=20, help="Max results (default: 20, max: 50)")
    sr.add_argument("--fields", help="Comma-separated field names to include")
    sr.add_argument("--json", action="store_true", help="Output raw JSON")
    sr.set_defaults(func=cmd_search)

    # -- create-issue --------------------------------------------------------
    ci = sub.add_parser("create-issue", help="Create a new Jira issue with team defaults")
    ci.add_argument("--type", required=True, choices=["Story", "Bug", "Task", "Sub-task", "Epic"], help="Issue type")
    ci.add_argument("--summary", required=True, help="Issue title/summary")
    ci.add_argument("--description", help="Description (Jira wiki markup)")
    ci.add_argument("--project", help="Project key (default: from config)")
    ci.add_argument("--assignee", help="Assignee username")
    ci.add_argument("--priority", choices=["Blocker", "Major", "Normal", "Minor", "Trivial"], help="Priority")
    ci.add_argument("--labels", help="Comma-separated extra labels (team label added automatically)")
    ci.add_argument("--components", help="Comma-separated component names")
    ci.add_argument("--parent", help="Parent issue key (required for Sub-task)")
    ci.add_argument("--epic-link", help="Epic key to link to (e.g., FAB-11437)")
    ci.add_argument("--story-points", type=float, help="Story point estimate")
    ci.add_argument("--skip-team-defaults", action="store_true", help="Skip auto-applying team defaults")
    ci.add_argument("--json", action="store_true", help="Output raw JSON")
    ci.set_defaults(func=cmd_create_issue)

    # -- update-issue --------------------------------------------------------
    ui = sub.add_parser("update-issue", help="Update fields on an existing issue")
    ui.add_argument("issue_key", help="Issue key (e.g., FAB-1234)")
    ui.add_argument("--summary", help="New summary/title")
    ui.add_argument("--description", help="New description")
    ui.add_argument("--assignee", help="New assignee (empty string to unassign)")
    ui.add_argument("--priority", choices=["Blocker", "Major", "Normal", "Minor", "Trivial"], help="New priority")
    ui.add_argument("--labels", help="Comma-separated labels (replaces all)")
    ui.add_argument("--components", help="Comma-separated components (replaces all)")
    ui.add_argument("--story-points", type=float, help="Story point estimate")
    ui.add_argument("--json", action="store_true", help="Output raw JSON")
    ui.set_defaults(func=cmd_update_issue)

    # -- transition-issue ----------------------------------------------------
    ti = sub.add_parser("transition-issue", help="Move an issue to a new status")
    ti.add_argument("issue_key", help="Issue key (e.g., FAB-1234)")
    ti.add_argument("status", help="Target status name (e.g., 'In Progress', 'Done')")
    ti.add_argument("--comment", help="Optional comment to add with the transition")
    ti.add_argument("--json", action="store_true", help="Output raw JSON")
    ti.set_defaults(func=cmd_transition_issue)

    # -- add-comment ---------------------------------------------------------
    ac = sub.add_parser("add-comment", help="Add a comment to an issue")
    ac.add_argument("issue_key", help="Issue key (e.g., FAB-1234)")
    ac.add_argument("body", help="Comment text (Jira wiki markup supported)")
    ac.add_argument("--json", action="store_true", help="Output raw JSON")
    ac.set_defaults(func=cmd_add_comment)

    # -- assign-issue --------------------------------------------------------
    ai_ = sub.add_parser("assign-issue", help="Assign or unassign an issue")
    ai_.add_argument("issue_key", help="Issue key (e.g., FAB-1234)")
    ai_.add_argument("assignee", help="Username to assign (use '' to unassign, '-1' for auto)")
    ai_.add_argument("--json", action="store_true", help="Output raw JSON")
    ai_.set_defaults(func=cmd_assign_issue)

    # -- add-to-sprint -------------------------------------------------------
    ats = sub.add_parser("add-to-sprint", help="Add issue to a sprint (auto-detects active sprint)")
    ats.add_argument("issue_key", help="Issue key (e.g., FAB-1234)")
    ats.add_argument("--sprint-id", type=int, help="Sprint ID (default: current active sprint)")
    ats.add_argument("--json", action="store_true", help="Output raw JSON")
    ats.set_defaults(func=cmd_add_to_sprint)

    # -- get-board -----------------------------------------------------------
    gb = sub.add_parser("get-board", help="Get board information")
    gb.add_argument("--board-id", type=int, help="Board ID (default: from config)")
    gb.add_argument("--json", action="store_true", help="Output raw JSON")
    gb.set_defaults(func=cmd_get_board)

    # -- get-sprints ---------------------------------------------------------
    gs = sub.add_parser("get-sprints", help="List sprints for a board")
    gs.add_argument("--board-id", type=int, help="Board ID (default: from config)")
    gs.add_argument("--state", default="active,future", choices=["active", "future", "closed", "active,future", "active,future,closed"], help="Sprint states (default: active,future)")
    gs.add_argument("--json", action="store_true", help="Output raw JSON")
    gs.set_defaults(func=cmd_get_sprints)

    # -- get-sprint-issues ---------------------------------------------------
    gsi = sub.add_parser("get-sprint-issues", help="Get all issues in a sprint")
    gsi.add_argument("sprint_id", type=int, help="Sprint ID (use get-sprints to find it)")
    gsi.add_argument("--max-results", type=int, default=50, help="Max results (default: 50)")
    gsi.add_argument("--json", action="store_true", help="Output raw JSON")
    gsi.set_defaults(func=cmd_get_sprint_issues)

    # -- get-backlog ---------------------------------------------------------
    gbl = sub.add_parser("get-backlog", help="Get backlog issues for a board")
    gbl.add_argument("--board-id", type=int, help="Board ID (default: from config)")
    gbl.add_argument("--max-results", type=int, default=30, help="Max results (default: 30)")
    gbl.add_argument("--json", action="store_true", help="Output raw JSON")
    gbl.set_defaults(func=cmd_get_backlog)

    # -- get-myself ----------------------------------------------------------
    gm = sub.add_parser("get-myself", help="Get current authenticated user info")
    gm.add_argument("--json", action="store_true", help="Output raw JSON")
    gm.set_defaults(func=cmd_get_myself)

    # -- get-project ---------------------------------------------------------
    gp = sub.add_parser("get-project", help="Get project info (issue types, components, versions)")
    gp.add_argument("--project-key", help="Project key (default: from config)")
    gp.add_argument("--json", action="store_true", help="Output raw JSON")
    gp.set_defaults(func=cmd_get_project)

    # -- list-transitions ----------------------------------------------------
    lt = sub.add_parser("list-transitions", help="List available status transitions for an issue")
    lt.add_argument("issue_key", help="Issue key (e.g., FAB-1234)")
    lt.add_argument("--json", action="store_true", help="Output raw JSON")
    lt.set_defaults(func=cmd_list_transitions)

    # -- discover-fields -----------------------------------------------------
    df = sub.add_parser("discover-fields", help="Inspect custom fields on an issue")
    df.add_argument("issue_key", help="Issue key (e.g., FAB-11438)")
    df.add_argument("--filter", help="Filter field values by text (case-insensitive)")
    df.add_argument("--json", action="store_true", help="Output raw JSON")
    df.set_defaults(func=cmd_discover_fields)

    # -- link-issues ---------------------------------------------------------
    li = sub.add_parser("link-issues", help="Create a link between two issues")
    li.add_argument("--type", required=True, help="Link type (e.g., 'blocks', 'relates to')")
    li.add_argument("--inward-issue", required=True, help="Inward issue key (e.g., FAB-1234)")
    li.add_argument("--outward-issue", required=True, help="Outward issue key (e.g., FAB-5678)")
    li.add_argument("--comment", help="Optional comment for the link")
    li.add_argument("--json", action="store_true", help="Output raw JSON")
    li.set_defaults(func=cmd_link_issues)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
