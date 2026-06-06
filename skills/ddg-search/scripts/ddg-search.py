#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["duckduckgo-search>=7.0"]
# ///
"""
DuckDuckGo web search. Returns JSON results to stdout.

Usage:
    uv run ddg-search.py "search query"
    uv run ddg-search.py "search query" --max-results 10
"""

from __future__ import annotations

import argparse
import json
import sys

from duckduckgo_search import DDGS


def main() -> int:
    parser = argparse.ArgumentParser(description="Search the web using DuckDuckGo")
    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="Maximum number of results (default: 5)",
    )
    args = parser.parse_args()

    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(args.query, max_results=args.max_results))

        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in raw
        ]

        json.dump(results, sys.stdout, indent=2)
        print()  # trailing newline
        return 0

    except Exception as e:
        print(f"Search failed: {e}", file=sys.stderr)
        json.dump({"error": str(e)}, sys.stdout)
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
