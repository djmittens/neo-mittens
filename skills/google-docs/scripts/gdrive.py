#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""
Google Drive operations — portable CLI script.

Usage:  uv run gdrive.py <subcommand> [options]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
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

def drive_api(endpoint: str, method: str = "GET", body=None):
    url = f"https://www.googleapis.com{endpoint}"
    kw: dict = {"headers": _headers(), "timeout": 60}
    if body is not None:
        kw["json"] = body
    resp = requests.request(method, url, **kw)
    if resp.ok:
        return resp.json() if resp.content else {}
    die(f"Drive API ({resp.status_code}): {resp.text}")

def die(msg: str):
    print(json.dumps({"error": msg}))
    sys.exit(1)

def ok(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))

# ═══════════════════════════════════════════════════════════════════════
# SUBCOMMANDS
# ═══════════════════════════════════════════════════════════════════════

def cmd_list(args):
    q = "trashed = false"
    if args.folder_id:
        q += f" and '{args.folder_id}' in parents"
    if args.query:
        q += f" and ({args.query})"
    params = urlencode({
        "q": q,
        "pageSize": str(args.max_results),
        "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
        "orderBy": "modifiedTime desc",
    })
    data = drive_api(f"/drive/v3/files?{params}")
    files = [
        {"name": f["name"], "id": f["id"], "mimeType": f["mimeType"],
         "modifiedTime": f.get("modifiedTime"), "webViewLink": f.get("webViewLink")}
        for f in data.get("files", [])
    ]
    ok({"files": files})


def cmd_search(args):
    q = f"trashed = false and (name contains '{args.term}' or fullText contains '{args.term}')"
    params = urlencode({
        "q": q,
        "pageSize": str(args.max_results),
        "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
        "orderBy": "modifiedTime desc",
    })
    data = drive_api(f"/drive/v3/files?{params}")
    files = [
        {"name": f["name"], "id": f["id"], "mimeType": f["mimeType"],
         "modifiedTime": f.get("modifiedTime"), "webViewLink": f.get("webViewLink")}
        for f in data.get("files", [])
    ]
    ok({"term": args.term, "files": files})


def cmd_get_file_info(args):
    params = urlencode({"fields": "id,name,mimeType,description,createdTime,modifiedTime,size,webViewLink,owners,permissions"})
    data = drive_api(f"/drive/v3/files/{args.file_id}?{params}")
    ok({
        "id": data["id"], "name": data["name"], "mimeType": data["mimeType"],
        "createdTime": data.get("createdTime"), "modifiedTime": data.get("modifiedTime"),
        "size": data.get("size"), "webViewLink": data.get("webViewLink"),
        "description": data.get("description"),
        "owners": [o.get("emailAddress") for o in data.get("owners", [])],
    })


def cmd_download(args):
    fmt = args.format or "text"
    info = drive_api(f"/drive/v3/files/{args.file_id}?fields=mimeType,name")
    mime_map = {
        "text": "text/plain", "html": "text/html", "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
    }
    headers = _headers()
    mime_type = info.get("mimeType", "")

    if mime_type.startswith("application/vnd.google-apps."):
        url = f"https://www.googleapis.com/drive/v3/files/{args.file_id}/export?mimeType={quote(mime_map[fmt], safe='')}"
    else:
        url = f"https://www.googleapis.com/drive/v3/files/{args.file_id}?alt=media"

    resp = requests.get(url, headers=headers, timeout=60)
    if not resp.ok:
        die(f"Download failed ({resp.status_code}): {resp.text}")
    ok({"name": info.get("name"), "format": fmt, "content": resp.text})


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="Google Drive operations", prog="gdrive.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="List files")
    s.add_argument("--query", default=None, help="Drive search query")
    s.add_argument("--max-results", type=int, default=10)
    s.add_argument("--folder-id", default=None)

    s = sub.add_parser("search", help="Search files by name/content")
    s.add_argument("term")
    s.add_argument("--max-results", type=int, default=10)

    s = sub.add_parser("get-file-info", help="Get file metadata")
    s.add_argument("file_id")

    s = sub.add_parser("download", help="Download/export a file")
    s.add_argument("file_id")
    s.add_argument("--format", choices=["text", "html", "pdf", "docx", "xlsx", "csv"], default="text")

    args = p.parse_args()
    {"list": cmd_list, "search": cmd_search, "get-file-info": cmd_get_file_info,
     "download": cmd_download}[args.cmd](args)


if __name__ == "__main__":
    main()
