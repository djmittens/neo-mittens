#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""
Gmail operations — portable CLI script.

Usage:  uv run gmail.py <subcommand> [options]
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

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

def gmail_api(endpoint: str, method: str = "GET", body=None):
    url = f"https://gmail.googleapis.com{endpoint}"
    kw: dict = {"headers": _headers(), "timeout": 60}
    if body is not None:
        kw["json"] = body
    resp = requests.request(method, url, **kw)
    if resp.ok:
        return resp.json() if resp.content else {}
    die(f"Gmail API ({resp.status_code}): {resp.text}")

def die(msg: str):
    print(json.dumps({"error": msg}))
    sys.exit(1)

def ok(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))

# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def decode_base64url(s: str) -> str:
    padded = s + "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def get_header(headers: list[dict], name: str) -> str:
    for h in (headers or []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def extract_body(payload: dict) -> str:
    # Direct body
    if payload.get("body", {}).get("data"):
        return decode_base64url(payload["body"]["data"])
    # Multipart
    parts = payload.get("parts", [])
    # text/plain first
    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return decode_base64url(part["body"]["data"])
    # text/html fallback
    for part in parts:
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            html = decode_base64url(part["body"]["data"])
            html = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
            html = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
            html = re.sub(r"<[^>]+>", " ", html)
            return re.sub(r"\s+", " ", html).strip()
    # Nested
    for part in parts:
        if part.get("parts"):
            nested = extract_body(part)
            if nested:
                return nested
    return ""

# ═══════════════════════════════════════════════════════════════════════
# SUBCOMMANDS
# ═══════════════════════════════════════════════════════════════════════

def cmd_list(args):
    params: dict[str, str] = {"maxResults": str(args.max_results)}
    if args.query:
        params["q"] = args.query
    if args.label:
        params["labelIds"] = args.label
    data = gmail_api(f"/gmail/v1/users/me/messages?{urlencode(params)}")
    messages = []
    for msg in (data.get("messages") or [])[:args.max_results]:
        detail = gmail_api(
            f"/gmail/v1/users/me/messages/{msg['id']}?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date"
        )
        hdrs = detail.get("payload", {}).get("headers", [])
        messages.append({
            "id": msg["id"], "threadId": msg.get("threadId"),
            "from": get_header(hdrs, "From"),
            "subject": get_header(hdrs, "Subject"),
            "date": get_header(hdrs, "Date"),
            "snippet": (detail.get("snippet") or "")[:100],
        })
    ok({"messages": messages})


def cmd_read(args):
    msg = gmail_api(f"/gmail/v1/users/me/messages/{args.message_id}?format=full")
    hdrs = msg.get("payload", {}).get("headers", [])
    body = extract_body(msg.get("payload", {}))
    ok({
        "id": args.message_id,
        "from": get_header(hdrs, "From"),
        "to": get_header(hdrs, "To"),
        "subject": get_header(hdrs, "Subject"),
        "date": get_header(hdrs, "Date"),
        "body": body,
    })


def cmd_search(args):
    params = urlencode({"q": args.query, "maxResults": str(args.max_results)})
    data = gmail_api(f"/gmail/v1/users/me/messages?{params}")
    messages = []
    for msg in data.get("messages") or []:
        detail = gmail_api(
            f"/gmail/v1/users/me/messages/{msg['id']}?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date"
        )
        hdrs = detail.get("payload", {}).get("headers", [])
        messages.append({
            "id": msg["id"],
            "from": get_header(hdrs, "From"),
            "subject": get_header(hdrs, "Subject"),
            "date": get_header(hdrs, "Date"),
        })
    ok({"query": args.query, "messages": messages})


def cmd_list_labels(args):
    data = gmail_api("/gmail/v1/users/me/labels")
    labels = [{"id": l["id"], "name": l["name"], "type": l.get("type")} for l in data.get("labels", [])]
    ok({"labels": labels})


def cmd_get_thread(args):
    thread = gmail_api(f"/gmail/v1/users/me/threads/{args.thread_id}?format=full")
    messages = []
    for msg in thread.get("messages", []):
        hdrs = msg.get("payload", {}).get("headers", [])
        body = extract_body(msg.get("payload", {}))
        messages.append({
            "id": msg["id"],
            "from": get_header(hdrs, "From"),
            "date": get_header(hdrs, "Date"),
            "body": body[:500] + ("..." if len(body) > 500 else ""),
        })
    ok({"thread_id": args.thread_id, "messages": messages})


def cmd_mark_read(args):
    gmail_api(f"/gmail/v1/users/me/messages/{args.message_id}/modify", method="POST",
              body={"removeLabelIds": ["UNREAD"]})
    ok({"status": "ok", "message_id": args.message_id, "action": "marked_read"})


def cmd_mark_unread(args):
    gmail_api(f"/gmail/v1/users/me/messages/{args.message_id}/modify", method="POST",
              body={"addLabelIds": ["UNREAD"]})
    ok({"status": "ok", "message_id": args.message_id, "action": "marked_unread"})


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="Gmail operations", prog="gmail.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="List recent emails")
    s.add_argument("--query", default=None, help="Gmail search query")
    s.add_argument("--max-results", type=int, default=10)
    s.add_argument("--label", default="INBOX")

    s = sub.add_parser("read", help="Read full email content")
    s.add_argument("message_id")

    s = sub.add_parser("search", help="Search emails")
    s.add_argument("query")
    s.add_argument("--max-results", type=int, default=10)

    s = sub.add_parser("list-labels", help="List all Gmail labels")

    s = sub.add_parser("get-thread", help="Get all messages in a thread")
    s.add_argument("thread_id")

    s = sub.add_parser("mark-read", help="Mark email as read")
    s.add_argument("message_id")

    s = sub.add_parser("mark-unread", help="Mark email as unread")
    s.add_argument("message_id")

    args = p.parse_args()
    {"list": cmd_list, "read": cmd_read, "search": cmd_search,
     "list-labels": cmd_list_labels, "get-thread": cmd_get_thread,
     "mark-read": cmd_mark_read, "mark-unread": cmd_mark_unread}[args.cmd](args)


if __name__ == "__main__":
    main()
