#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""
Google Calendar operations — portable CLI script.

Usage:  uv run gcalendar.py <subcommand> [options]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode, quote

import requests

# ═══════════════════════════════════════════════════════════════════════
# AUTH (inlined)
# ═══════════════════════════════════════════════════════════════════════

PREFERRED_PROJECT = "ck-orp-nick-dev"
ADC_PATH = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"

def _read_quota_project() -> str | None:
    if not ADC_PATH.exists():
        return None
    try:
        return json.loads(ADC_PATH.read_text()).get("quota_project_id") or None
    except Exception:
        return None

def _auto_set_quota() -> str | None:
    project = PREFERRED_PROJECT
    if not project:
        return None
    try:
        r = subprocess.run(["gcloud", "auth", "application-default", "set-quota-project", project], capture_output=True, text=True, timeout=10)
        return project if r.returncode == 0 else None
    except Exception:
        return None

def _get_token() -> str:
    try:
        r = subprocess.run(["gcloud", "auth", "application-default", "print-access-token"], capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        die("gcloud CLI not found")
    if r.returncode != 0:
        die(f"Failed to get access token: {r.stderr.strip()}")
    return r.stdout.strip()

def _headers() -> dict[str, str]:
    token = _get_token()
    quota = _read_quota_project() or _auto_set_quota()
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if quota:
        h["x-goog-user-project"] = quota
    return h

CAL_BASE = "https://www.googleapis.com/calendar/v3"

def cal_api(endpoint: str, method: str = "GET", body=None):
    url = f"{CAL_BASE}{endpoint}"
    kw: dict = {"headers": _headers(), "timeout": 60}
    if body is not None:
        kw["json"] = body
    resp = requests.request(method, url, **kw)
    if resp.ok:
        return resp.json() if resp.content else {}
    # DELETE returns 204 No Content
    if method == "DELETE" and resp.status_code == 204:
        return {}
    die(f"Calendar API ({resp.status_code}): {resp.text}")

def cal_delete(endpoint: str):
    """Separate handler for DELETE since it returns 204."""
    url = f"{CAL_BASE}{endpoint}"
    resp = requests.delete(url, headers=_headers(), timeout=60)
    if resp.status_code not in (200, 204):
        die(f"Calendar API DELETE ({resp.status_code}): {resp.text}")
    return {}

def die(msg: str):
    print(json.dumps({"error": msg}))
    sys.exit(1)

def ok(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))

# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def format_event(event: dict) -> dict:
    return {
        "id": event.get("id"),
        "summary": event.get("summary", "(No title)"),
        "start": event.get("start", {}).get("dateTime") or event.get("start", {}).get("date"),
        "end": event.get("end", {}).get("dateTime") or event.get("end", {}).get("date"),
        "location": event.get("location"),
        "description": (event.get("description") or "")[:200] or None,
        "attendees": [a.get("email") for a in event.get("attendees", [])],
        "htmlLink": event.get("htmlLink"),
    }

# ═══════════════════════════════════════════════════════════════════════
# SUBCOMMANDS
# ═══════════════════════════════════════════════════════════════════════

def cmd_list_events(args):
    cal = quote(args.calendar_id or "primary", safe="")
    params: dict[str, str] = {
        "maxResults": str(args.max_results),
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeMin": args.time_min or datetime.now(timezone.utc).isoformat(),
    }
    if args.time_max:
        params["timeMax"] = args.time_max
    data = cal_api(f"/calendars/{cal}/events?{urlencode(params)}")
    events = [format_event(e) for e in data.get("items", [])]
    ok({"events": events})


def cmd_get_event(args):
    cal = quote(args.calendar_id or "primary", safe="")
    event = cal_api(f"/calendars/{cal}/events/{args.event_id}")
    ok({
        "id": event.get("id"), "status": event.get("status"),
        "summary": event.get("summary"), "description": event.get("description"),
        "start": event.get("start", {}).get("dateTime") or event.get("start", {}).get("date"),
        "end": event.get("end", {}).get("dateTime") or event.get("end", {}).get("date"),
        "location": event.get("location"),
        "creator": event.get("creator", {}).get("email"),
        "organizer": event.get("organizer", {}).get("email"),
        "attendees": [
            {"email": a.get("email"), "responseStatus": a.get("responseStatus"), "organizer": a.get("organizer", False)}
            for a in event.get("attendees", [])
        ],
        "htmlLink": event.get("htmlLink"),
    })


def cmd_create_event(args):
    cal = quote(args.calendar_id or "primary", safe="")
    event: dict = {
        "summary": args.summary,
        "start": {"dateTime": args.start},
        "end": {"dateTime": args.end},
    }
    if args.description:
        event["description"] = args.description
    if args.location:
        event["location"] = args.location
    if args.attendees:
        event["attendees"] = [{"email": e} for e in args.attendees]
    result = cal_api(f"/calendars/{cal}/events", method="POST", body=event)
    ok({
        "status": "ok", "id": result.get("id"),
        "summary": result.get("summary"),
        "start": result.get("start", {}).get("dateTime") or result.get("start", {}).get("date"),
        "end": result.get("end", {}).get("dateTime") or result.get("end", {}).get("date"),
        "htmlLink": result.get("htmlLink"),
    })


def cmd_update_event(args):
    cal = quote(args.calendar_id or "primary", safe="")
    existing = cal_api(f"/calendars/{cal}/events/{args.event_id}")
    if args.summary:
        existing["summary"] = args.summary
    if args.start:
        existing["start"] = {"dateTime": args.start}
    if args.end:
        existing["end"] = {"dateTime": args.end}
    if args.description is not None:
        existing["description"] = args.description
    if args.location is not None:
        existing["location"] = args.location
    result = cal_api(f"/calendars/{cal}/events/{args.event_id}", method="PUT", body=existing)
    ok({"status": "ok", "id": result.get("id"), "summary": result.get("summary")})


def cmd_delete_event(args):
    cal = quote(args.calendar_id or "primary", safe="")
    cal_delete(f"/calendars/{cal}/events/{args.event_id}")
    ok({"status": "ok", "deleted": args.event_id})


def cmd_search_events(args):
    cal = quote(args.calendar_id or "primary", safe="")
    one_year_ago = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    params = urlencode({
        "q": args.query,
        "maxResults": str(args.max_results),
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeMin": one_year_ago,
    })
    data = cal_api(f"/calendars/{cal}/events?{params}")
    events = [format_event(e) for e in data.get("items", [])]
    ok({"query": args.query, "events": events})


def cmd_list_calendars(args):
    data = cal_api("/users/me/calendarList")
    calendars = [
        {"id": c["id"], "summary": c.get("summary"), "accessRole": c.get("accessRole")}
        for c in data.get("items", [])
    ]
    ok({"calendars": calendars})


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="Google Calendar operations", prog="gcalendar.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list-events", help="List upcoming events")
    s.add_argument("--calendar-id", default="primary")
    s.add_argument("--max-results", type=int, default=10)
    s.add_argument("--time-min", default=None, help="ISO 8601 start filter")
    s.add_argument("--time-max", default=None, help="ISO 8601 end filter")

    s = sub.add_parser("get-event", help="Get event details")
    s.add_argument("event_id")
    s.add_argument("--calendar-id", default="primary")

    s = sub.add_parser("create-event", help="Create a new event")
    s.add_argument("--summary", required=True)
    s.add_argument("--start", required=True, help="ISO 8601")
    s.add_argument("--end", required=True, help="ISO 8601")
    s.add_argument("--description", default=None)
    s.add_argument("--location", default=None)
    s.add_argument("--attendees", nargs="*", default=None, help="Email addresses")
    s.add_argument("--calendar-id", default="primary")

    s = sub.add_parser("update-event", help="Update an existing event")
    s.add_argument("event_id")
    s.add_argument("--summary", default=None)
    s.add_argument("--start", default=None)
    s.add_argument("--end", default=None)
    s.add_argument("--description", default=None)
    s.add_argument("--location", default=None)
    s.add_argument("--calendar-id", default="primary")

    s = sub.add_parser("delete-event", help="Delete an event")
    s.add_argument("event_id")
    s.add_argument("--calendar-id", default="primary")

    s = sub.add_parser("search-events", help="Search events by text")
    s.add_argument("query")
    s.add_argument("--calendar-id", default="primary")
    s.add_argument("--max-results", type=int, default=10)

    s = sub.add_parser("list-calendars", help="List all calendars")

    args = p.parse_args()
    {"list-events": cmd_list_events, "get-event": cmd_get_event,
     "create-event": cmd_create_event, "update-event": cmd_update_event,
     "delete-event": cmd_delete_event, "search-events": cmd_search_events,
     "list-calendars": cmd_list_calendars}[args.cmd](args)


if __name__ == "__main__":
    main()
