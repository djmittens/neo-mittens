#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
draw.io diagram tool -- create, read, and update .drawio.png files.

Creates PNG files with embedded draw.io XML (zTXt chunk), so the PNG
is both viewable as an image and editable in draw.io.

Requires `npx draw.io-export` on PATH for PNG rendering.

Usage:
    uv run drawio.py create --xml '<mxGraphModel>...</mxGraphModel>' -o diagram.drawio.png
    uv run drawio.py create --xml-file diagram.xml -o diagram.drawio.png
    uv run drawio.py read diagram.drawio.png
    uv run drawio.py update --xml '<mxGraphModel>...</mxGraphModel>' diagram.drawio.png
    uv run drawio.py update --xml-file updated.xml diagram.drawio.png
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
import urllib.parse
import zlib


# ============================================================
# PNG chunk helpers
#
# draw.io PNG format:
#   zTXt chunk key: "mxGraphModel"
#   zTXt value (after zlib inflate): <mxfile><diagram>PAYLOAD</diagram></mxfile>
#   PAYLOAD: base64( deflateRaw( urlEncode(mxGraphModelXml) ) )
#
# deflateRaw = raw deflate with NO zlib header (wbits=-15)
# ============================================================

import base64
import re


def _crc32(data: bytes) -> int:
    """Compute CRC32 for a PNG chunk (type + data)."""
    return zlib.crc32(data) & 0xFFFFFFFF


def _encode_diagram_payload(xml: str) -> str:
    """mxGraphModel XML -> URL-encode -> raw deflate -> base64."""
    url_encoded = urllib.parse.quote(xml, safe="")
    # wbits=-15 gives raw deflate (no zlib header)
    deflated = zlib.compress(url_encoded.encode("utf-8"), level=9, wbits=-15)
    return base64.b64encode(deflated).decode("ascii")


def _decode_diagram_payload(payload: str) -> str:
    """base64 -> raw inflate -> URL-decode -> mxGraphModel XML."""
    deflated = base64.b64decode(payload)
    # wbits=-15 for raw inflate
    url_encoded = zlib.decompress(deflated, wbits=-15).decode("utf-8")
    return urllib.parse.unquote(url_encoded)


def _build_ztxt_chunk(xml: str) -> bytes:
    """Build a PNG zTXt chunk embedding draw.io XML."""
    payload = _encode_diagram_payload(xml)
    mxfile_xml = f"<mxfile><diagram>{payload}</diagram></mxfile>"

    # zTXt format: key\0 compression_method(1 byte) compressed_data
    key = b"mxGraphModel\x00"
    compression_method = b"\x00"  # zlib
    compressed = zlib.compress(mxfile_xml.encode("utf-8"))
    chunk_data = key + compression_method + compressed

    chunk_type = b"zTXt"
    length = struct.pack(">I", len(chunk_data))
    crc = struct.pack(">I", _crc32(chunk_type + chunk_data))

    return length + chunk_type + chunk_data + crc


def embed_xml_in_png(png_path: str, xml: str) -> None:
    """Embed draw.io XML into a PNG file as a zTXt chunk."""
    data = _read_bytes(png_path)

    # Strip any existing mxGraphModel zTXt chunks first
    data = _strip_ztxt_chunks(data, key=b"mxGraphModel")

    chunk = _build_ztxt_chunk(xml)

    # Insert before IEND (last 12 bytes of a valid PNG)
    iend_start = len(data) - 12
    before = data[:iend_start]
    iend = data[iend_start:]

    with open(png_path, "wb") as f:
        f.write(before + chunk + iend)


def extract_xml_from_png(png_path: str) -> str | None:
    """Extract draw.io XML from a PNG file's zTXt metadata."""
    data = _read_bytes(png_path)

    # Walk PNG chunks looking for zTXt with key "mxGraphModel"
    pos = 8  # skip PNG signature
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        chunk_type = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + length]

        if chunk_type == b"zTXt":
            null_pos = chunk_data.index(b"\x00")
            key = chunk_data[:null_pos]
            if key == b"mxGraphModel":
                # byte after null is compression method (0), then zlib data
                compressed = chunk_data[null_pos + 2 :]
                mxfile_xml = zlib.decompress(compressed).decode("utf-8")
                # Parse <mxfile><diagram>PAYLOAD</diagram></mxfile>
                match = re.search(r"<diagram[^>]*>([\s\S]*?)</diagram>", mxfile_xml)
                if match:
                    return _decode_diagram_payload(match.group(1))
                # Fallback: return the raw mxfile XML
                return mxfile_xml

        pos += 12 + length

    return None


def _strip_ztxt_chunks(data: bytes, key: bytes) -> bytes:
    """Remove all zTXt chunks with the given key from PNG data."""
    result = data[:8]  # PNG signature
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        chunk_type = data[pos + 4 : pos + 8]
        chunk_end = pos + 12 + length

        keep = True
        if chunk_type == b"zTXt":
            chunk_data = data[pos + 8 : pos + 8 + length]
            null_pos = chunk_data.find(b"\x00")
            if null_pos >= 0 and chunk_data[:null_pos] == key:
                keep = False

        if keep:
            result += data[pos:chunk_end]
        pos = chunk_end

    return result


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


# ============================================================
# Export helper
# ============================================================


def export_drawio(drawio_path: str, png_path: str) -> None:
    """Export a .drawio file to PNG using npx draw.io-export."""
    result = subprocess.run(
        ["npx", "draw.io-export", drawio_path, "-o", png_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"npx draw.io-export failed (exit {result.returncode}): {result.stderr}"
        )


# ============================================================
# Subcommands
# ============================================================


def cmd_create(args: argparse.Namespace) -> int:
    xml = _get_xml(args)
    output_path: str = args.output

    if not output_path.endswith(".drawio.png"):
        output_path += ".drawio.png"

    dir_name = os.path.dirname(output_path) or "."
    base_name = os.path.basename(output_path).removesuffix(".drawio.png").removesuffix(".png")
    drawio_path = os.path.join(dir_name, f"{base_name}.drawio")

    # 1. Write .drawio file
    with open(drawio_path, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"Wrote {drawio_path}", file=sys.stderr)

    # 2. Export to PNG
    try:
        export_drawio(drawio_path, output_path)
        print(f"Exported PNG: {output_path}", file=sys.stderr)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        print(json.dumps({"error": str(e), "drawio_path": drawio_path}))
        return 1

    # 3. Embed XML into PNG
    embed_xml_in_png(output_path, xml)
    print(f"Embedded XML into PNG", file=sys.stderr)

    # 4. Clean up .drawio file
    try:
        os.unlink(drawio_path)
    except OSError:
        pass

    print(json.dumps({"path": output_path, "status": "created"}))
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    png_path: str = args.png_path

    if not os.path.exists(png_path):
        print(json.dumps({"error": f"File not found: {png_path}"}))
        return 1

    xml = extract_xml_from_png(png_path)
    if xml is None:
        print(json.dumps({"error": f"No embedded draw.io XML found in: {png_path}"}))
        return 1

    # Output raw XML to stdout (not JSON-wrapped -- it's XML)
    print(xml)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    xml = _get_xml(args)
    png_path: str = args.png_path

    if not os.path.exists(png_path):
        print(json.dumps({"error": f"File not found: {png_path}"}))
        return 1

    dir_name = os.path.dirname(png_path) or "."
    base_name = os.path.basename(png_path).removesuffix(".drawio.png").removesuffix(".png")
    drawio_path = os.path.join(dir_name, f"{base_name}.tmp.drawio")

    # 1. Write updated .drawio
    with open(drawio_path, "w", encoding="utf-8") as f:
        f.write(xml)

    # 2. Re-export PNG
    try:
        export_drawio(drawio_path, png_path)
        print(f"Re-exported PNG: {png_path}", file=sys.stderr)
    except RuntimeError as e:
        _cleanup(drawio_path)
        print(json.dumps({"error": str(e)}))
        return 1

    # 3. Re-embed XML
    embed_xml_in_png(png_path, xml)
    print(f"Re-embedded XML into PNG", file=sys.stderr)

    # 4. Clean up temp
    _cleanup(drawio_path)

    print(json.dumps({"path": png_path, "status": "updated"}))
    return 0


def _get_xml(args: argparse.Namespace) -> str:
    """Get XML from --xml or --xml-file argument."""
    if hasattr(args, "xml_file") and args.xml_file:
        with open(args.xml_file, "r", encoding="utf-8") as f:
            return f.read()
    if hasattr(args, "xml") and args.xml:
        return args.xml
    # Read from stdin if neither provided
    if not sys.stdin.isatty():
        return sys.stdin.read()
    print("Error: provide XML via --xml, --xml-file, or stdin", file=sys.stderr)
    sys.exit(1)


def _cleanup(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


# ============================================================
# CLI
# ============================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="draw.io diagram tool -- create, read, and update .drawio.png files",
        epilog="Requires `npx draw.io-export` for PNG rendering.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # create
    p_create = sub.add_parser("create", help="Create a new .drawio.png from XML")
    p_create.add_argument("--xml", help="mxGraphModel XML string")
    p_create.add_argument("--xml-file", help="Path to file containing mxGraphModel XML")
    p_create.add_argument("-o", "--output", required=True, help="Output path (should end in .drawio.png)")

    # read
    p_read = sub.add_parser("read", help="Extract draw.io XML from a .drawio.png")
    p_read.add_argument("png_path", help="Path to .drawio.png file")

    # update
    p_update = sub.add_parser("update", help="Update an existing .drawio.png with new XML")
    p_update.add_argument("--xml", help="Updated mxGraphModel XML string")
    p_update.add_argument("--xml-file", help="Path to file containing updated XML")
    p_update.add_argument("png_path", help="Path to existing .drawio.png file")

    args = parser.parse_args()

    if args.command == "create":
        return cmd_create(args)
    elif args.command == "read":
        return cmd_read(args)
    elif args.command == "update":
        return cmd_update(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
