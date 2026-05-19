#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""
Google Docs operations — portable CLI script.

Usage:  uv run gdocs.py <subcommand> [options]
Run:    uv run gdocs.py --help
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

# ═══════════════════════════════════════════════════════════════════════
# AUTH (inlined from gauth.py for uv-run portability)
# ═══════════════════════════════════════════════════════════════════════

PREFERRED_PROJECT = "ck-orp-nick-dev"
ADC_PATH = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
ALL_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

def _reauth_cmd() -> str:
    return f"gcloud auth application-default login --scopes={','.join(ALL_SCOPES)}"

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
        try:
            r = subprocess.run(["gcloud", "config", "get-value", "project"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip() not in ("", "(unset)"):
                project = r.stdout.strip()
        except Exception:
            pass
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
        die("gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install")
    if r.returncode != 0:
        die(f"Failed to get access token. Fix:\n  {_reauth_cmd()}\n\ngcloud: {r.stderr.strip()}")
    return r.stdout.strip()

def _headers() -> dict[str, str]:
    token = _get_token()
    quota = _read_quota_project() or _auto_set_quota()
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if quota:
        h["x-goog-user-project"] = quota
    return h

def docs_api(endpoint: str, method: str = "GET", body=None):
    url = f"https://docs.googleapis.com{endpoint}"
    headers = _headers()
    kw: dict = {"headers": headers, "timeout": 60}
    if body is not None:
        kw["json"] = body
    resp = requests.request(method, url, **kw)
    if resp.ok:
        return resp.json() if resp.content else {}
    if resp.status_code == 403:
        try:
            err = resp.json()
        except Exception:
            err = {}
        reason = (err.get("error", {}).get("details") or [{}])[0].get("reason", "")
        if reason == "ACCESS_TOKEN_SCOPE_INSUFFICIENT":
            die(f"Insufficient scopes. Fix:\n  {_reauth_cmd()}")
        if reason == "SERVICE_DISABLED" or "quota" in resp.text.lower():
            fixed = _auto_set_quota()
            if fixed:
                headers["x-goog-user-project"] = fixed
                retry = requests.request(method, url, headers=headers, json=body, timeout=60)
                if retry.ok:
                    return retry.json() if retry.content else {}
            die("Quota project required but auto-fix failed.")
    die(f"Docs API ({resp.status_code}): {resp.text}")


def die(msg: str):
    print(json.dumps({"error": msg}))
    sys.exit(1)

def ok(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))

# ═══════════════════════════════════════════════════════════════════════
# STYLING CONFIG (from GenAI Secret Sauce patterns)
# ═══════════════════════════════════════════════════════════════════════

COLORS = {
    "HEADING_RED": "#980000",
    "HEADING_DARK": "#444444",
    "CHARCOAL": "#221F1F",
    "DARK_GRAY": "#333333",
    "TABLE_HEADER": "#333333",
    "TABLE_HEADER_TEXT": "#FFFFFF",
    "TABLE_BORDER": "#E8E8E8",
    "TABLE_ALT_ROW": "#F9F9F9",
    "LINK_BLUE": "#1155CC",
}

STYLES = {
    "fonts": {"primary": "Google Sans Text", "secondary": "Montserrat", "code": "Roboto Mono"},
    "sizes": {"title": 26, "h1": 22, "h2": 20, "h3": 18, "h4": 16, "h5": 14, "body": 11},
    "spacing": {
        "h1Before": 24, "h1After": 12,
        "h2Before": 18, "h2After": 8,
        "h3Before": 14, "h3After": 6,
        "paragraphAfter": 8,
    },
    "prefixes": {"h1": "\u2503", "h2": "\u2192"},  # ┃ and →
}


def hex_to_rgb(h: str) -> dict:
    h = h.lstrip("#")
    return {
        "red": int(h[0:2], 16) / 255,
        "green": int(h[2:4], 16) / 255,
        "blue": int(h[4:6], 16) / 255,
    }


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def extract_text(doc: dict) -> str:
    content = doc.get("body", {}).get("content", [])
    text = ""
    for el in content:
        if "paragraph" in el:
            for e in el["paragraph"].get("elements", []):
                if "textRun" in e:
                    text += e["textRun"]["content"]
        elif "table" in el:
            text += "[Table]\n"
            for row in el["table"].get("tableRows", []):
                cells = row.get("tableCells", [])
                row_text = " | ".join(
                    "".join(
                        e2.get("textRun", {}).get("content", "").strip()
                        for c2 in cell.get("content", [])
                        if "paragraph" in c2
                        for e2 in c2["paragraph"].get("elements", [])
                    )
                    for cell in cells
                )
                text += row_text + "\n"
    return text


def find_text_ranges(doc: dict, needle: str) -> list[dict]:
    """Find all {start, end} ranges of needle in the document (including tables)."""
    ranges: list[dict] = []

    def search_paragraph(paragraph):
        for elem in paragraph.get("elements", []):
            tr = elem.get("textRun", {})
            content = tr.get("content", "")
            start_idx = elem.get("startIndex", 0)
            idx = 0
            while True:
                idx = content.find(needle, idx)
                if idx == -1:
                    break
                ranges.append({"start": start_idx + idx, "end": start_idx + idx + len(needle)})
                idx += len(needle)

    for el in doc.get("body", {}).get("content", []):
        if "paragraph" in el:
            search_paragraph(el["paragraph"])
        elif "table" in el:
            for row in el["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    for cc in cell.get("content", []):
                        if "paragraph" in cc:
                            search_paragraph(cc["paragraph"])
    return ranges


def parse_table_data(raw: str, columns: int | None = None) -> list[list[str]]:
    """Parse JSON 2D array or pipe-delimited table data."""
    trimmed = raw.strip()
    if trimmed.startswith("["):
        try:
            parsed = json.loads(trimmed)
            if isinstance(parsed, list) and all(isinstance(r, list) for r in parsed):
                return parsed
        except json.JSONDecodeError:
            pass
    # Pipe-delimited fallback
    cells = [s.strip() for s in trimmed.split("|")]
    if columns and columns > 0:
        return [cells[i:i + columns] for i in range(0, len(cells), columns)]
    return [cells]


# ═══════════════════════════════════════════════════════════════════════
# SUBCOMMANDS
# ═══════════════════════════════════════════════════════════════════════

def cmd_read(args):
    doc = docs_api(f"/v1/documents/{args.document_id}")
    text = extract_text(doc)
    ok({"title": doc.get("title"), "document_id": args.document_id,
        "url": f"https://docs.google.com/document/d/{args.document_id}/edit",
        "content": text})


def cmd_get_structure(args):
    doc = docs_api(f"/v1/documents/{args.document_id}")
    headings = []
    for el in doc.get("body", {}).get("content", []):
        if "paragraph" in el:
            style = el["paragraph"].get("paragraphStyle", {}).get("namedStyleType", "")
            if style.startswith("HEADING_"):
                level = int(style.replace("HEADING_", ""))
                text = "".join(
                    e.get("textRun", {}).get("content", "")
                    for e in el["paragraph"].get("elements", [])
                ).strip()
                headings.append({"level": level, "text": text})
    ok({"title": doc.get("title"), "headings": headings})


def cmd_create(args):
    doc = docs_api("/v1/documents", method="POST", body={"title": args.title})
    doc_id = doc["documentId"]
    if args.content:
        docs_api(f"/v1/documents/{doc_id}:batchUpdate", method="POST", body={
            "requests": [{"insertText": {"location": {"index": 1}, "text": args.content}}]
        })
    ok({"title": doc.get("title"), "document_id": doc_id,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit"})


def cmd_append(args):
    doc = docs_api(f"/v1/documents/{args.document_id}")
    end_index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1)
    docs_api(f"/v1/documents/{args.document_id}:batchUpdate", method="POST", body={
        "requests": [{"insertText": {"location": {"index": end_index - 1}, "text": "\n" + args.text}}]
    })
    ok({"status": "ok", "appended_chars": len(args.text), "title": doc.get("title")})


def cmd_find_replace(args):
    result = docs_api(f"/v1/documents/{args.document_id}:batchUpdate", method="POST", body={
        "requests": [{"replaceAllText": {
            "containsText": {"text": args.find, "matchCase": args.match_case},
            "replaceText": args.replace,
        }}]
    })
    count = (result.get("replies") or [{}])[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
    ok({"status": "ok", "occurrences_changed": count, "find": args.find, "replace": args.replace})


def cmd_format_document(args):
    doc = docs_api(f"/v1/documents/{args.document_id}")
    reqs: list[dict] = []
    for el in doc.get("body", {}).get("content", []):
        if "paragraph" not in el:
            continue
        style = el["paragraph"].get("paragraphStyle", {}).get("namedStyleType", "")
        si = el.get("startIndex")
        ei = el.get("endIndex")
        if not si or not ei:
            continue
        cfg = {
            "TITLE": (STYLES["sizes"]["title"], STYLES["fonts"]["primary"], True, COLORS["HEADING_DARK"], None, None),
            "HEADING_1": (STYLES["sizes"]["h1"], STYLES["fonts"]["primary"], True, COLORS["HEADING_RED"],
                          STYLES["spacing"]["h1Before"], STYLES["spacing"]["h1After"]),
            "HEADING_2": (STYLES["sizes"]["h2"], STYLES["fonts"]["primary"], True, COLORS["HEADING_RED"],
                          STYLES["spacing"]["h2Before"], STYLES["spacing"]["h2After"]),
            "HEADING_3": (STYLES["sizes"]["h3"], STYLES["fonts"]["primary"], True, COLORS["HEADING_DARK"],
                          STYLES["spacing"]["h3Before"], STYLES["spacing"]["h3After"]),
            "HEADING_4": (STYLES["sizes"]["h4"], STYLES["fonts"]["secondary"], False, COLORS["DARK_GRAY"], None, None),
            "HEADING_5": (STYLES["sizes"]["h5"], STYLES["fonts"]["primary"], True, COLORS["DARK_GRAY"], None, None),
        }.get(style)
        if not cfg:
            continue
        sz, font, bold, color, sp_above, sp_below = cfg
        ts: dict = {
            "fontSize": {"magnitude": sz, "unit": "PT"},
            "weightedFontFamily": {"fontFamily": font},
            "foregroundColor": {"color": {"rgbColor": hex_to_rgb(color)}},
        }
        fields = ["fontSize", "weightedFontFamily", "foregroundColor"]
        if bold:
            ts["bold"] = True
            fields.append("bold")
        reqs.append({"updateTextStyle": {"range": {"startIndex": si, "endIndex": ei}, "textStyle": ts, "fields": ",".join(fields)}})
        if sp_above is not None or sp_below is not None:
            ps: dict = {}
            pf: list[str] = []
            if sp_above is not None:
                ps["spaceAbove"] = {"magnitude": sp_above, "unit": "PT"}
                pf.append("spaceAbove")
            if sp_below is not None:
                ps["spaceBelow"] = {"magnitude": sp_below, "unit": "PT"}
                pf.append("spaceBelow")
            reqs.append({"updateParagraphStyle": {"range": {"startIndex": si, "endIndex": ei}, "paragraphStyle": ps, "fields": ",".join(pf)}})
    if not reqs:
        ok({"status": "ok", "message": "No formattable content found"})
        return
    docs_api(f"/v1/documents/{args.document_id}:batchUpdate", method="POST", body={"requests": reqs})
    ok({"status": "ok", "elements_formatted": len(reqs)})


def cmd_apply_heading_style(args):
    doc = docs_api(f"/v1/documents/{args.document_id}")
    ranges = []
    for el in doc.get("body", {}).get("content", []):
        if "paragraph" in el:
            ptxt = "".join(e.get("textRun", {}).get("content", "") for e in el["paragraph"].get("elements", []))
            if args.find_text in ptxt:
                ranges.append({"start": el.get("startIndex"), "end": el.get("endIndex")})
    if not ranges:
        ok({"status": "not_found", "message": f'Text "{args.find_text}" not found'})
        return
    reqs = [{"updateParagraphStyle": {
        "range": {"startIndex": r["start"], "endIndex": r["end"]},
        "paragraphStyle": {"namedStyleType": f"HEADING_{args.level}"},
        "fields": "namedStyleType",
    }} for r in ranges]
    docs_api(f"/v1/documents/{args.document_id}:batchUpdate", method="POST", body={"requests": reqs})
    ok({"status": "ok", "paragraphs_styled": len(ranges), "level": int(args.level)})


def cmd_insert_table(args):
    data_rows = parse_table_data(args.data, args.columns) if args.data else None
    doc = docs_api(f"/v1/documents/{args.document_id}")
    insert_idx = args.index or (doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 2) - 1)
    docs_api(f"/v1/documents/{args.document_id}:batchUpdate", method="POST", body={
        "requests": [{"insertTable": {"rows": args.rows, "columns": args.columns, "location": {"index": insert_idx}}}]
    })
    if data_rows:
        _populate_and_style_table(args.document_id, insert_idx, args.rows, args.columns, data_rows)
    ok({"status": "ok", "rows": args.rows, "columns": args.columns, "index": insert_idx})


def cmd_format_text(args):
    doc = docs_api(f"/v1/documents/{args.document_id}")
    ranges = find_text_ranges(doc, args.find_text)
    if not ranges:
        ok({"status": "not_found", "message": f'Text "{args.find_text}" not found'})
        return
    ts: dict = {}
    fields: list[str] = []
    if args.bold is not None:
        ts["bold"] = args.bold; fields.append("bold")
    if args.italic is not None:
        ts["italic"] = args.italic; fields.append("italic")
    if args.underline is not None:
        ts["underline"] = args.underline; fields.append("underline")
    if args.font_size is not None:
        ts["fontSize"] = {"magnitude": args.font_size, "unit": "PT"}; fields.append("fontSize")
    if args.foreground_color:
        ts["foregroundColor"] = {"color": {"rgbColor": hex_to_rgb(args.foreground_color)}}; fields.append("foregroundColor")
    if args.background_color:
        ts["backgroundColor"] = {"color": {"rgbColor": hex_to_rgb(args.background_color)}}; fields.append("backgroundColor")
    reqs = [{"updateTextStyle": {"range": {"startIndex": r["start"], "endIndex": r["end"]}, "textStyle": ts, "fields": ",".join(fields)}} for r in ranges]
    docs_api(f"/v1/documents/{args.document_id}:batchUpdate", method="POST", body={"requests": reqs})
    ok({"status": "ok", "occurrences_formatted": len(ranges)})


def cmd_link_text(args):
    doc = docs_api(f"/v1/documents/{args.document_id}")
    ranges = find_text_ranges(doc, args.find_text)
    if not ranges:
        ok({"status": "not_found", "message": f'Text "{args.find_text}" not found'})
        return
    reqs = [{"updateTextStyle": {
        "range": {"startIndex": r["start"], "endIndex": r["end"]},
        "textStyle": {"link": {"url": args.url}},
        "fields": "link",
    }} for r in ranges]
    docs_api(f"/v1/documents/{args.document_id}:batchUpdate", method="POST", body={"requests": reqs})
    ok({"status": "ok", "occurrences_linked": len(ranges), "url": args.url})


def cmd_batch_format(args):
    ops = json.loads(args.operations)
    reqs: list[dict] = []
    for op in ops:
        if op["type"] == "heading":
            reqs.append({"updateParagraphStyle": {
                "range": {"startIndex": op["startIndex"], "endIndex": op["endIndex"]},
                "paragraphStyle": {"namedStyleType": f"HEADING_{op['level']}"},
                "fields": "namedStyleType",
            }})
        elif op["type"] == "text_style":
            ts: dict = {}; fields: list[str] = []
            for k in ("bold", "italic", "underline"):
                if k in op:
                    ts[k] = op[k]; fields.append(k)
            if "fontSize" in op:
                ts["fontSize"] = {"magnitude": op["fontSize"], "unit": "PT"}; fields.append("fontSize")
            if "foregroundColor" in op:
                ts["foregroundColor"] = {"color": {"rgbColor": hex_to_rgb(op["foregroundColor"])}}; fields.append("foregroundColor")
            reqs.append({"updateTextStyle": {"range": {"startIndex": op["startIndex"], "endIndex": op["endIndex"]}, "textStyle": ts, "fields": ",".join(fields)}})
        elif op["type"] == "paragraph_style":
            ps: dict = {}; pf: list[str] = []
            if "spaceAbove" in op:
                ps["spaceAbove"] = {"magnitude": op["spaceAbove"], "unit": "PT"}; pf.append("spaceAbove")
            if "spaceBelow" in op:
                ps["spaceBelow"] = {"magnitude": op["spaceBelow"], "unit": "PT"}; pf.append("spaceBelow")
            reqs.append({"updateParagraphStyle": {"range": {"startIndex": op["startIndex"], "endIndex": op["endIndex"]}, "paragraphStyle": ps, "fields": ",".join(pf)}})
    if not reqs:
        ok({"status": "ok", "message": "No valid operations"}); return
    docs_api(f"/v1/documents/{args.document_id}:batchUpdate", method="POST", body={"requests": reqs})
    ok({"status": "ok", "operations_applied": len(reqs)})


def cmd_insert_heading(args):
    doc = docs_api(f"/v1/documents/{args.document_id}")
    insert_idx = args.index or (doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 2) - 1)
    heading_text = args.text + "\n"
    end_idx = insert_idx + len(heading_text)
    docs_api(f"/v1/documents/{args.document_id}:batchUpdate", method="POST", body={
        "requests": [
            {"insertText": {"location": {"index": insert_idx}, "text": heading_text}},
            {"updateParagraphStyle": {
                "range": {"startIndex": insert_idx, "endIndex": end_idx},
                "paragraphStyle": {"namedStyleType": f"HEADING_{args.level}"},
                "fields": "namedStyleType",
            }},
        ]
    })
    ok({"status": "ok", "level": int(args.level), "text": args.text, "index": insert_idx})


def cmd_clear_document(args):
    doc = docs_api(f"/v1/documents/{args.document_id}")
    end_index = 1
    for el in doc.get("body", {}).get("content", []):
        ei = el.get("endIndex", 0)
        if ei > end_index:
            end_index = ei
    if end_index <= 2:
        ok({"status": "ok", "message": "Document already empty"}); return
    docs_api(f"/v1/documents/{args.document_id}:batchUpdate", method="POST", body={
        "requests": [{"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}}]
    })
    ok({"status": "ok", "title": doc.get("title")})


def cmd_write_formatted_section(args):
    blocks = json.loads(args.content)
    doc = docs_api(f"/v1/documents/{args.document_id}")
    insert_idx = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 2) - 1

    # Build full text and track positions
    positions = []
    cur = insert_idx
    for block in blocks:
        txt = block["text"] + "\n"
        positions.append({"start": cur, "end": cur + len(txt), "type": block["type"], "bold": block.get("bold")})
        cur += len(txt)
    full_text = "".join(b["text"] + "\n" for b in blocks)

    # Insert all text at once
    docs_api(f"/v1/documents/{args.document_id}:batchUpdate", method="POST", body={
        "requests": [{"insertText": {"location": {"index": insert_idx}, "text": full_text}}]
    })

    # Build formatting requests
    fmt_reqs: list[dict] = []
    for pos in positions:
        named = {"title": "TITLE", "h1": "HEADING_1", "h2": "HEADING_2", "h3": "HEADING_3", "h4": "HEADING_4"}.get(pos["type"], "NORMAL_TEXT")
        fmt_reqs.append({"updateParagraphStyle": {
            "range": {"startIndex": pos["start"], "endIndex": pos["end"]},
            "paragraphStyle": {"namedStyleType": named},
            "fields": "namedStyleType",
        }})
        if pos["type"] in ("h1", "h2"):
            fmt_reqs.append({"updateTextStyle": {
                "range": {"startIndex": pos["start"], "endIndex": pos["end"] - 1},
                "textStyle": {"foregroundColor": {"color": {"rgbColor": hex_to_rgb(COLORS["HEADING_RED"])}}, "bold": True},
                "fields": "foregroundColor,bold",
            }})
        elif pos["type"] in ("h3", "h4"):
            fmt_reqs.append({"updateTextStyle": {
                "range": {"startIndex": pos["start"], "endIndex": pos["end"] - 1},
                "textStyle": {"foregroundColor": {"color": {"rgbColor": hex_to_rgb(COLORS["HEADING_DARK"])}}, "bold": True},
                "fields": "foregroundColor,bold",
            }})
        elif pos["type"] == "bullet":
            fmt_reqs.append({"createParagraphBullets": {
                "range": {"startIndex": pos["start"], "endIndex": pos["end"]},
                "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
            }})
        elif pos["type"] == "code":
            fmt_reqs.append({"updateTextStyle": {
                "range": {"startIndex": pos["start"], "endIndex": pos["end"] - 1},
                "textStyle": {
                    "weightedFontFamily": {"fontFamily": STYLES["fonts"]["code"]},
                    "fontSize": {"magnitude": 10, "unit": "PT"},
                    "backgroundColor": {"color": {"rgbColor": hex_to_rgb("#F5F5F5")}},
                },
                "fields": "weightedFontFamily,fontSize,backgroundColor",
            }})
        elif pos["type"] == "text" and pos.get("bold"):
            fmt_reqs.append({"updateTextStyle": {
                "range": {"startIndex": pos["start"], "endIndex": pos["end"] - 1},
                "textStyle": {"bold": True},
                "fields": "bold",
            }})

    if fmt_reqs:
        docs_api(f"/v1/documents/{args.document_id}:batchUpdate", method="POST", body={"requests": fmt_reqs})
    ok({"status": "ok", "blocks_written": len(blocks)})


def cmd_insert_styled_table(args):
    # Parse headers
    trimmed = args.headers.strip()
    if trimmed.startswith("["):
        try:
            header_cells = json.loads(trimmed)
        except json.JSONDecodeError:
            header_cells = [h.strip() for h in trimmed.split(",")]
    else:
        header_cells = [h.strip() for h in trimmed.split(",")]
    data_rows = parse_table_data(args.rows, len(header_cells))
    num_cols = len(header_cells)
    num_rows = len(data_rows) + 1

    doc = docs_api(f"/v1/documents/{args.document_id}")
    insert_idx = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 2) - 1

    # Create table
    docs_api(f"/v1/documents/{args.document_id}:batchUpdate", method="POST", body={
        "requests": [{"insertTable": {"rows": num_rows, "columns": num_cols, "location": {"index": insert_idx}}}]
    })

    all_rows = [header_cells] + data_rows
    _populate_and_style_table(args.document_id, insert_idx, num_rows, num_cols, all_rows, style_header_text=True)
    ok({"status": "ok", "rows": num_rows, "columns": num_cols, "headers": header_cells})


def _populate_and_style_table(doc_id, insert_idx, num_rows, num_cols, all_rows, style_header_text=False):
    """Shared helper: populate cells and style a table that was just inserted."""
    updated = docs_api(f"/v1/documents/{doc_id}")
    table = None
    for el in updated.get("body", {}).get("content", []):
        if "table" in el and el.get("startIndex", 0) >= insert_idx:
            table = el
            break
    if not table:
        return

    text_reqs, style_reqs = [], []
    for r in range(min(num_rows, len(all_rows))):
        for c in range(min(num_cols, len(all_rows[r]) if r < len(all_rows) else 0)):
            cell = table["table"]["tableRows"][r]["tableCells"][c]
            val = all_rows[r][c] if r < len(all_rows) and c < len(all_rows[r]) else ""
            paragraph = cell.get("content", [{}])[0]
            if paragraph and val:
                text_reqs.append({"insertText": {"location": {"index": paragraph.get("startIndex", 0)}, "text": str(val)}})
            # Header row background
            if r == 0:
                style_reqs.append({"updateTableCellStyle": {
                    "tableRange": {"tableCellLocation": {"tableStartLocation": {"index": table["startIndex"]}, "rowIndex": r, "columnIndex": c}, "rowSpan": 1, "columnSpan": 1},
                    "tableCellStyle": {"backgroundColor": {"color": {"rgbColor": hex_to_rgb(COLORS["TABLE_HEADER"])}}},
                    "fields": "backgroundColor",
                }})
            elif r % 2 == 0:
                style_reqs.append({"updateTableCellStyle": {
                    "tableRange": {"tableCellLocation": {"tableStartLocation": {"index": table["startIndex"]}, "rowIndex": r, "columnIndex": c}, "rowSpan": 1, "columnSpan": 1},
                    "tableCellStyle": {"backgroundColor": {"color": {"rgbColor": hex_to_rgb(COLORS["TABLE_ALT_ROW"])}}},
                    "fields": "backgroundColor",
                }})

    if text_reqs:
        docs_api(f"/v1/documents/{doc_id}:batchUpdate", method="POST", body={"requests": list(reversed(text_reqs))})
    if style_reqs:
        docs_api(f"/v1/documents/{doc_id}:batchUpdate", method="POST", body={"requests": style_reqs})

    # Style header text white+bold
    if style_header_text:
        refreshed = docs_api(f"/v1/documents/{doc_id}")
        rtable = None
        for el in refreshed.get("body", {}).get("content", []):
            if "table" in el and el.get("startIndex", 0) >= insert_idx:
                rtable = el
                break
        if rtable:
            hdr_reqs = []
            for c in range(num_cols):
                cell = rtable["table"]["tableRows"][0]["tableCells"][c]
                p = cell.get("content", [{}])[0]
                if p:
                    si = p.get("startIndex", 0)
                    ei = p.get("endIndex", 0) - 1
                    if si < ei:
                        hdr_reqs.append({"updateTextStyle": {
                            "range": {"startIndex": si, "endIndex": ei},
                            "textStyle": {"foregroundColor": {"color": {"rgbColor": hex_to_rgb(COLORS["TABLE_HEADER_TEXT"])}}, "bold": True},
                            "fields": "foregroundColor,bold",
                        }})
            if hdr_reqs:
                docs_api(f"/v1/documents/{doc_id}:batchUpdate", method="POST", body={"requests": hdr_reqs})


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

def _add_bool_flag(parser, name, help_text):
    parser.add_argument(f"--{name}", action="store_true", default=None, help=help_text)
    parser.add_argument(f"--no-{name}", action="store_false", dest=name, help=f"Disable {name}")


def main():
    p = argparse.ArgumentParser(description="Google Docs operations", prog="gdocs.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    # read
    s = sub.add_parser("read", help="Read a Google Doc")
    s.add_argument("document_id")

    # get-structure
    s = sub.add_parser("get-structure", help="Get document heading structure")
    s.add_argument("document_id")

    # create
    s = sub.add_parser("create", help="Create a new Google Doc")
    s.add_argument("--title", required=True)
    s.add_argument("--content", default=None, help="Initial text content")

    # append
    s = sub.add_parser("append", help="Append text to end of doc")
    s.add_argument("document_id")
    s.add_argument("--text", required=True)

    # find-replace
    s = sub.add_parser("find-replace", help="Find and replace text")
    s.add_argument("document_id")
    s.add_argument("--find", required=True)
    s.add_argument("--replace", required=True)
    s.add_argument("--match-case", action="store_true", default=False)

    # format-document
    s = sub.add_parser("format-document", help="Apply professional formatting to entire doc")
    s.add_argument("document_id")

    # apply-heading-style
    s = sub.add_parser("apply-heading-style", help="Convert existing text to heading style")
    s.add_argument("document_id")
    s.add_argument("--find-text", required=True)
    s.add_argument("--level", required=True, choices=["1", "2", "3", "4", "5", "6"])

    # insert-table
    s = sub.add_parser("insert-table", help="Insert a table")
    s.add_argument("document_id")
    s.add_argument("--rows", type=int, required=True)
    s.add_argument("--columns", type=int, required=True)
    s.add_argument("--data", default=None, help='JSON 2D array or pipe-delimited data')
    s.add_argument("--index", type=int, default=None, help="Insert position (1-based)")

    # format-text
    s = sub.add_parser("format-text", help="Apply formatting to text found in doc")
    s.add_argument("document_id")
    s.add_argument("--find-text", required=True)
    _add_bool_flag(s, "bold", "Bold")
    _add_bool_flag(s, "italic", "Italic")
    _add_bool_flag(s, "underline", "Underline")
    s.add_argument("--font-size", type=float, default=None)
    s.add_argument("--foreground-color", default=None, help="Hex color e.g. #FF0000")
    s.add_argument("--background-color", default=None, help="Hex color")

    # link-text
    s = sub.add_parser("link-text", help="Add hyperlink to text in doc")
    s.add_argument("document_id")
    s.add_argument("--find-text", required=True)
    s.add_argument("--url", required=True)

    # batch-format
    s = sub.add_parser("batch-format", help="Apply multiple formatting operations")
    s.add_argument("document_id")
    s.add_argument("--operations", required=True, help="JSON array of operations")

    # insert-heading
    s = sub.add_parser("insert-heading", help="Insert a styled heading")
    s.add_argument("document_id")
    s.add_argument("--text", required=True)
    s.add_argument("--level", required=True, choices=["1", "2", "3", "4", "5", "6"])
    s.add_argument("--index", type=int, default=None)

    # clear-document
    s = sub.add_parser("clear-document", help="Clear all content from a doc")
    s.add_argument("document_id")

    # write-formatted-section
    s = sub.add_parser("write-formatted-section", help="Write content with formatting")
    s.add_argument("document_id")
    s.add_argument("--content", required=True, help="JSON array of content blocks")

    # insert-styled-table
    s = sub.add_parser("insert-styled-table", help="Insert styled table with dark header")
    s.add_argument("document_id")
    s.add_argument("--headers", required=True, help="Comma-separated or JSON array")
    s.add_argument("--rows", required=True, help="JSON array of row arrays")

    args = p.parse_args()

    dispatch = {
        "read": cmd_read, "get-structure": cmd_get_structure, "create": cmd_create,
        "append": cmd_append, "find-replace": cmd_find_replace,
        "format-document": cmd_format_document, "apply-heading-style": cmd_apply_heading_style,
        "insert-table": cmd_insert_table, "format-text": cmd_format_text,
        "link-text": cmd_link_text, "batch-format": cmd_batch_format,
        "insert-heading": cmd_insert_heading, "clear-document": cmd_clear_document,
        "write-formatted-section": cmd_write_formatted_section,
        "insert-styled-table": cmd_insert_styled_table,
    }
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
