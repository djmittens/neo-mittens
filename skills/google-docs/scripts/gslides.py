#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["requests"]
# ///
"""
Google Slides operations — portable CLI script.

Usage:  uv run gslides.py <subcommand> [options]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

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

def slides_api(endpoint: str, method: str = "GET", body=None):
    url = f"https://slides.googleapis.com{endpoint}"
    kw: dict = {"headers": _headers(), "timeout": 60}
    if body is not None:
        kw["json"] = body
    resp = requests.request(method, url, **kw)
    if resp.ok:
        return resp.json() if resp.content else {}
    die(f"Slides API ({resp.status_code}): {resp.text}")

def die(msg: str):
    print(json.dumps({"error": msg}))
    sys.exit(1)

def ok(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))

# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def extract_text_from_element(element: dict) -> str:
    shape = element.get("shape", {})
    if shape.get("text", {}).get("textElements"):
        return "".join(
            te.get("textRun", {}).get("content", "")
            for te in shape["text"]["textElements"]
            if "textRun" in te
        )
    table = element.get("table")
    if table:
        rows = []
        for row in table.get("tableRows", []):
            cells = " | ".join(
                "".join(
                    te.get("textRun", {}).get("content", "").strip()
                    for te in (cell.get("text", {}).get("textElements") or [])
                    if "textRun" in te
                )
                for cell in row.get("tableCells", [])
            )
            rows.append(cells)
        return "\n".join(rows)
    return ""


# ═══════════════════════════════════════════════════════════════════════
# SUBCOMMANDS
# ═══════════════════════════════════════════════════════════════════════

def cmd_read(args):
    pres = slides_api(f"/v1/presentations/{args.presentation_id}")
    slides = []
    for i, slide in enumerate(pres.get("slides", [])):
        texts = []
        for el in slide.get("pageElements", []):
            t = extract_text_from_element(el).strip()
            if t:
                texts.append(t)
        slides.append({"slide_number": i + 1, "content": texts})
    ok({"title": pres.get("title"), "presentation_id": args.presentation_id, "slides": slides})


def cmd_get_info(args):
    pres = slides_api(f"/v1/presentations/{args.presentation_id}")
    slide_info = []
    for i, s in enumerate(pres.get("slides", [])):
        title_elem = next(
            (e for e in s.get("pageElements", [])
             if e.get("shape", {}).get("placeholder", {}).get("type") in ("TITLE", "CENTERED_TITLE")),
            None,
        )
        title = extract_text_from_element(title_elem).strip()[:50] if title_elem else "Untitled"
        slide_info.append({"slide_number": i + 1, "title": title})
    page_size = pres.get("pageSize", {})
    ok({
        "title": pres.get("title"),
        "presentation_id": args.presentation_id,
        "url": f"https://docs.google.com/presentation/d/{args.presentation_id}",
        "slide_count": len(pres.get("slides", [])),
        "page_size": {
            "width": page_size.get("width", {}).get("magnitude"),
            "height": page_size.get("height", {}).get("magnitude"),
            "unit": page_size.get("width", {}).get("unit"),
        },
        "slides": slide_info,
    })


def cmd_create(args):
    result = slides_api("/v1/presentations", method="POST", body={"title": args.title})
    ok({
        "title": result.get("title"),
        "presentation_id": result["presentationId"],
        "url": f"https://docs.google.com/presentation/d/{result['presentationId']}",
    })


def cmd_add_slide(args):
    req: dict = {"createSlide": {"slideLayoutReference": {"predefinedLayout": args.layout or "TITLE_AND_BODY"}}}
    if args.insert_at is not None:
        req["createSlide"]["insertionIndex"] = args.insert_at
    result = slides_api(f"/v1/presentations/{args.presentation_id}:batchUpdate", method="POST", body={"requests": [req]})
    slide_id = (result.get("replies") or [{}])[0].get("createSlide", {}).get("objectId")
    ok({"status": "ok", "layout": args.layout, "slide_id": slide_id})


def cmd_update_text(args):
    pres = slides_api(f"/v1/presentations/{args.presentation_id}")
    has_text = False
    for slide in pres.get("slides", []):
        for el in slide.get("pageElements", []):
            if el.get("objectId") == args.object_id:
                has_text = bool(extract_text_from_element(el).strip())
                break
    reqs: list[dict] = []
    if has_text:
        reqs.append({"deleteText": {"objectId": args.object_id, "textRange": {"type": "ALL"}}})
    reqs.append({"insertText": {"objectId": args.object_id, "insertionIndex": 0, "text": args.text}})
    slides_api(f"/v1/presentations/{args.presentation_id}:batchUpdate", method="POST", body={"requests": reqs})
    ok({"status": "ok", "object_id": args.object_id})


def cmd_get_slide_elements(args):
    pres = slides_api(f"/v1/presentations/{args.presentation_id}")
    slides = pres.get("slides", [])
    if args.slide_index >= len(slides):
        die(f"Slide index {args.slide_index} out of range ({len(slides)} slides)")
    slide = slides[args.slide_index]
    elements = []
    for e in slide.get("pageElements", []):
        etype = "Shape" if "shape" in e else "Table" if "table" in e else "Image" if "image" in e else "Unknown"
        if etype == "Shape":
            etype += f" ({e['shape'].get('shapeType', '?')})"
        placeholder = e.get("shape", {}).get("placeholder", {}).get("type", "")
        text = extract_text_from_element(e).strip()[:50]
        elements.append({
            "object_id": e.get("objectId"),
            "type": etype,
            "placeholder": placeholder or None,
            "text_preview": text or "(empty)",
        })
    ok({"slide_number": args.slide_index + 1, "elements": elements})


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

LAYOUTS = ["BLANK", "TITLE", "TITLE_AND_BODY", "TITLE_AND_TWO_COLUMNS", "TITLE_ONLY", "SECTION_HEADER", "CAPTION_ONLY", "BIG_NUMBER"]

def main():
    p = argparse.ArgumentParser(description="Google Slides operations", prog="gslides.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("read", help="Read slide contents")
    s.add_argument("presentation_id")

    s = sub.add_parser("get-info", help="Get presentation info")
    s.add_argument("presentation_id")

    s = sub.add_parser("create", help="Create a new presentation")
    s.add_argument("--title", required=True)

    s = sub.add_parser("add-slide", help="Add a new slide")
    s.add_argument("presentation_id")
    s.add_argument("--layout", choices=LAYOUTS, default="TITLE_AND_BODY")
    s.add_argument("--insert-at", type=int, default=None, help="0-based position")

    s = sub.add_parser("update-text", help="Update text in a shape")
    s.add_argument("presentation_id")
    s.add_argument("--object-id", required=True)
    s.add_argument("--text", required=True)

    s = sub.add_parser("get-slide-elements", help="Get elements on a slide")
    s.add_argument("presentation_id")
    s.add_argument("--slide-index", type=int, required=True, help="0-based")

    args = p.parse_args()
    {"read": cmd_read, "get-info": cmd_get_info, "create": cmd_create,
     "add-slide": cmd_add_slide, "update-text": cmd_update_text,
     "get-slide-elements": cmd_get_slide_elements}[args.cmd](args)


if __name__ == "__main__":
    main()
