#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""
Google Sheets operations — portable CLI script.

Usage:  uv run gsheets.py <subcommand> [options]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import requests

# ═══════════════════════════════════════════════════════════════════════
# AUTH (inlined from gauth.py)
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

def sheets_api(endpoint: str, method: str = "GET", body=None):
    url = f"https://sheets.googleapis.com{endpoint}"
    kw: dict = {"headers": _headers(), "timeout": 60}
    if body is not None:
        kw["json"] = body
    resp = requests.request(method, url, **kw)
    if resp.ok:
        return resp.json() if resp.content else {}
    die(f"Sheets API ({resp.status_code}): {resp.text}")

def die(msg: str):
    print(json.dumps({"error": msg}))
    sys.exit(1)

def ok(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))

# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

LINK_RE = re.compile(r"^\[([^\]]+)\]\(([^)]+)\)$")

def convert_links(values: list[list[str]]) -> list[list[str]]:
    """Convert markdown [text](url) to Sheets HYPERLINK formulas."""
    def convert_cell(cell: str) -> str:
        m = LINK_RE.match(cell)
        if m:
            return f'=HYPERLINK("{m.group(2)}","{m.group(1)}")'
        return cell
    return [[convert_cell(c) for c in row] for row in values]

# ═══════════════════════════════════════════════════════════════════════
# SUBCOMMANDS
# ═══════════════════════════════════════════════════════════════════════

def cmd_read(args):
    rng = args.range or "A1:Z100"
    data = sheets_api(f"/v4/spreadsheets/{args.spreadsheet_id}/values/{quote(rng, safe='')}")
    ok({"range": data.get("range", rng), "values": data.get("values", [])})


def cmd_get_info(args):
    data = sheets_api(f"/v4/spreadsheets/{args.spreadsheet_id}?fields=properties,sheets.properties")
    sheets = [
        {"title": s["properties"]["title"],
         "sheetId": s["properties"]["sheetId"],
         "rows": s["properties"]["gridProperties"]["rowCount"],
         "columns": s["properties"]["gridProperties"]["columnCount"]}
        for s in data.get("sheets", [])
    ]
    ok({"title": data["properties"]["title"], "spreadsheet_id": args.spreadsheet_id,
        "url": f"https://docs.google.com/spreadsheets/d/{args.spreadsheet_id}", "sheets": sheets})


def cmd_write(args):
    values = json.loads(args.values)
    rng = args.range
    result = sheets_api(
        f"/v4/spreadsheets/{args.spreadsheet_id}/values/{quote(rng, safe='')}?valueInputOption=USER_ENTERED",
        method="PUT", body={"values": convert_links(values)},
    )
    ok({"status": "ok", "updated_cells": result.get("updatedCells", 0), "updated_range": result.get("updatedRange", rng)})


def cmd_append_rows(args):
    values = json.loads(args.values)
    sheet_name = args.sheet_name or "Sheet1"
    rng = f"{sheet_name}!A:A"
    result = sheets_api(
        f"/v4/spreadsheets/{args.spreadsheet_id}/values/{quote(rng, safe='')}:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS",
        method="POST", body={"values": convert_links(values)},
    )
    ok({"status": "ok", "rows_appended": len(values), "updated_range": result.get("updates", {}).get("updatedRange", "")})


def cmd_create(args):
    sheet_names = json.loads(args.sheet_names) if args.sheet_names else ["Sheet1"]
    sheets = [{"properties": {"title": n}} for n in sheet_names]
    result = sheets_api("/v4/spreadsheets", method="POST", body={
        "properties": {"title": args.title}, "sheets": sheets,
    })
    ok({"title": result["properties"]["title"], "spreadsheet_id": result["spreadsheetId"],
        "url": result["spreadsheetUrl"]})


def cmd_insert_rows(args):
    values = json.loads(args.values)
    sheet_name = args.sheet_name or "Sheet1"
    # Get sheet ID
    info = sheets_api(f"/v4/spreadsheets/{args.spreadsheet_id}?fields=sheets.properties")
    sheet = next((s for s in info["sheets"] if s["properties"]["title"] == sheet_name), None)
    if not sheet:
        die(f"Sheet '{sheet_name}' not found")
    sheet_id = sheet["properties"]["sheetId"]
    # Insert blank rows
    sheets_api(f"/v4/spreadsheets/{args.spreadsheet_id}:batchUpdate", method="POST", body={
        "requests": [{"insertDimension": {
            "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": args.row_index, "endIndex": args.row_index + len(values)},
            "inheritFromBefore": args.row_index > 0,
        }}]
    })
    # Write values
    rng = f"{sheet_name}!A{args.row_index + 1}"
    result = sheets_api(
        f"/v4/spreadsheets/{args.spreadsheet_id}/values/{quote(rng, safe='')}?valueInputOption=USER_ENTERED",
        method="PUT", body={"values": convert_links(values)},
    )
    ok({"status": "ok", "rows_inserted": len(values), "at_row": args.row_index + 1, "updated_range": result.get("updatedRange", "")})


def cmd_clear(args):
    sheets_api(
        f"/v4/spreadsheets/{args.spreadsheet_id}/values/{quote(args.range, safe='')}:clear",
        method="POST", body={},
    )
    ok({"status": "ok", "cleared_range": args.range})


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="Google Sheets operations", prog="gsheets.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("read", help="Read data from a sheet")
    s.add_argument("spreadsheet_id")
    s.add_argument("--range", default=None, help="A1 notation (default: A1:Z100)")

    s = sub.add_parser("get-info", help="Get spreadsheet metadata")
    s.add_argument("spreadsheet_id")

    s = sub.add_parser("write", help="Write data to a range")
    s.add_argument("spreadsheet_id")
    s.add_argument("--range", required=True, help="A1 notation range")
    s.add_argument("--values", required=True, help="JSON 2D array")

    s = sub.add_parser("append-rows", help="Append rows after last data")
    s.add_argument("spreadsheet_id")
    s.add_argument("--values", required=True, help="JSON 2D array")
    s.add_argument("--sheet-name", default=None, help="Sheet name (default: Sheet1)")

    s = sub.add_parser("create", help="Create a new spreadsheet")
    s.add_argument("--title", required=True)
    s.add_argument("--sheet-names", default=None, help='JSON array of sheet names')

    s = sub.add_parser("insert-rows", help="Insert rows at a position")
    s.add_argument("spreadsheet_id")
    s.add_argument("--row-index", type=int, required=True, help="0-based row index")
    s.add_argument("--values", required=True, help="JSON 2D array")
    s.add_argument("--sheet-name", default=None, help="Sheet name (default: Sheet1)")

    s = sub.add_parser("clear", help="Clear values from a range")
    s.add_argument("spreadsheet_id")
    s.add_argument("--range", required=True, help="A1 notation range")

    args = p.parse_args()
    {"read": cmd_read, "get-info": cmd_get_info, "write": cmd_write,
     "append-rows": cmd_append_rows, "create": cmd_create,
     "insert-rows": cmd_insert_rows, "clear": cmd_clear}[args.cmd](args)


if __name__ == "__main__":
    main()
