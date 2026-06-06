---
name: ddg-search
description: Search the web using DuckDuckGo -- no API key required
license: MIT
compatibility: Requires Python 3.10+ and uv
metadata:
  category: search
  system: web
---

# DuckDuckGo Web Search

Search the web and get structured JSON results. No API key required.

## Usage

```bash
uv run scripts/ddg-search.py "search query"
uv run scripts/ddg-search.py "search query" --max-results 10
```

## Output

JSON array on stdout:

```json
[
  {
    "title": "Result Title",
    "url": "https://example.com",
    "snippet": "Description text..."
  }
]
```

Errors are printed to stderr. On failure, stdout contains `{"error": "..."}`.

## When to Use

- Finding documentation, API references, library homepages
- Looking up current information (versions, changelogs, status pages)
- Researching error messages or stack traces
- Discovering examples and tutorials
