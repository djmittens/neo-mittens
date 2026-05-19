---
name: google-docs
description: "Google Workspace: Docs, Sheets, Slides, Drive, Gmail, Calendar — portable Python scripts using gcloud ADC auth"
license: MIT
compatibility: Any agent (Claude Code, OpenCode, Cursor, etc.) with shell access. Requires gcloud CLI + uv.
metadata:
  category: productivity
  system: google-workspace
---

# Google Workspace Integration

Portable Python scripts for Google Workspace APIs. No SDK-specific code — works with any agent that can run shell commands.

## Prerequisites

- `gcloud` CLI installed and authenticated
- `uv` (Python package runner): `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Quick Start

```bash
# Run any script directly — uv handles dependencies automatically
uv run scripts/gdocs.py read <DOCUMENT_ID>
uv run scripts/gsheets.py read <SPREADSHEET_ID>
uv run scripts/gdrive.py search "quarterly report"
uv run scripts/gmail.py list --max-results 5
uv run scripts/gcalendar.py list-events
uv run scripts/gslides.py read <PRESENTATION_ID>
```

All scripts output JSON to stdout, diagnostics to stderr.

## Authentication

Scripts use `gcloud auth application-default` credentials with a quota project header. Auth is automatic — scripts get tokens via `gcloud auth application-default print-access-token` and auto-detect the quota project from `~/.config/gcloud/application_default_credentials.json`.

### First-Time Setup

```bash
PROJECT="ck-orp-nick-dev"  # or your GCP project with Workspace APIs enabled

# 1. Enable APIs
gcloud services enable \
  docs.googleapis.com slides.googleapis.com drive.googleapis.com \
  sheets.googleapis.com calendar-json.googleapis.com gmail.googleapis.com \
  --project=$PROJECT

# 2. Authenticate with all scopes (sets quota project automatically)
gcloud auth application-default login \
  --billing-project=$PROJECT \
  --scopes="\
https://www.googleapis.com/auth/cloud-platform,\
https://www.googleapis.com/auth/documents,\
https://www.googleapis.com/auth/presentations,\
https://www.googleapis.com/auth/drive,\
https://www.googleapis.com/auth/drive.file,\
https://www.googleapis.com/auth/spreadsheets,\
https://www.googleapis.com/auth/calendar,\
https://www.googleapis.com/auth/calendar.events,\
https://www.googleapis.com/auth/gmail.modify,\
https://www.googleapis.com/auth/gmail.readonly,\
https://www.googleapis.com/auth/gmail.send,\
https://www.googleapis.com/auth/gmail.labels,\
https://www.googleapis.com/auth/tasks,\
https://www.googleapis.com/auth/userinfo.email,\
https://www.googleapis.com/auth/userinfo.profile"
```

### Auth Helper

```bash
uv run scripts/gauth.py token           # Print access token
uv run scripts/gauth.py quota-project   # Print current quota project
uv run scripts/gauth.py setup-info      # Print full setup instructions as JSON
```

## Scripts Reference

### `scripts/gdocs.py` — Google Docs

```bash
# Reading
uv run scripts/gdocs.py read <DOC_ID>
uv run scripts/gdocs.py get-structure <DOC_ID>

# Creating & editing
uv run scripts/gdocs.py create --title "My Doc" --content "Hello world"
uv run scripts/gdocs.py append <DOC_ID> --text "New paragraph"
uv run scripts/gdocs.py find-replace <DOC_ID> --find "old" --replace "new" [--match-case]
uv run scripts/gdocs.py clear-document <DOC_ID>

# Formatting
uv run scripts/gdocs.py format-document <DOC_ID>                    # Auto-style entire doc
uv run scripts/gdocs.py apply-heading-style <DOC_ID> --find-text "Title" --level 1
uv run scripts/gdocs.py format-text <DOC_ID> --find-text "important" --bold --foreground-color "#FF0000"
uv run scripts/gdocs.py link-text <DOC_ID> --find-text "click here" --url "https://example.com"
uv run scripts/gdocs.py insert-heading <DOC_ID> --text "New Section" --level 2 [--index 42]

# Batch formatting (JSON operations array)
uv run scripts/gdocs.py batch-format <DOC_ID> --operations '[{"type":"heading","startIndex":2,"endIndex":50,"level":1}]'

# Formatted sections (JSON content blocks)
uv run scripts/gdocs.py write-formatted-section <DOC_ID> --content '[
  {"type":"h1","text":"Section Title"},
  {"type":"text","text":"Body paragraph."},
  {"type":"bullet","text":"First point"},
  {"type":"code","text":"example_code()"}
]'

# Tables
uv run scripts/gdocs.py insert-table <DOC_ID> --rows 3 --columns 2 --data '[["H1","H2"],["a","b"],["c","d"]]'
uv run scripts/gdocs.py insert-styled-table <DOC_ID> --headers "Name,Type,Desc" \
  --rows '[["INT64","Number","Primary key"],["STRING","Text","Labels"]]'
```

**format-text flags:** `--bold/--no-bold`, `--italic/--no-italic`, `--underline/--no-underline`, `--font-size N`, `--foreground-color "#HEX"`, `--background-color "#HEX"`

**write-formatted-section block types:** `title`, `h1`, `h2`, `h3`, `h4`, `text`, `bullet`, `code`. Text blocks accept `"bold": true`.

**Styling:** `format-document` applies professional styling (Google Sans Text font, red headings for H1/H2, dark headers for H3+, proper spacing). Tables get dark `#333333` header rows with white text and `#F9F9F9` alternating rows.

### `scripts/gsheets.py` — Google Sheets

```bash
uv run scripts/gsheets.py read <SHEET_ID> [--range "Sheet1!A1:D10"]
uv run scripts/gsheets.py get-info <SHEET_ID>
uv run scripts/gsheets.py create --title "New Sheet" [--sheet-names '["Data","Summary"]']
uv run scripts/gsheets.py write <SHEET_ID> --range "A1" --values '[["Name","Age"],["Alice","30"]]'
uv run scripts/gsheets.py append-rows <SHEET_ID> --values '[["new","row"]]' [--sheet-name "Sheet1"]
uv run scripts/gsheets.py insert-rows <SHEET_ID> --row-index 5 --values '[["inserted","row"]]'
uv run scripts/gsheets.py clear <SHEET_ID> --range "Sheet1!A1:D10"
```

**Hyperlinks:** Use `[text](url)` in cell values — auto-converted to `=HYPERLINK()`.

### `scripts/gslides.py` — Google Slides

```bash
uv run scripts/gslides.py read <PRES_ID>
uv run scripts/gslides.py get-info <PRES_ID>
uv run scripts/gslides.py create --title "New Deck"
uv run scripts/gslides.py add-slide <PRES_ID> [--layout TITLE_AND_BODY] [--insert-at 0]
uv run scripts/gslides.py update-text <PRES_ID> --object-id <OBJ_ID> --text "New text"
uv run scripts/gslides.py get-slide-elements <PRES_ID> --slide-index 0
```

**Layouts:** `BLANK`, `TITLE`, `TITLE_AND_BODY`, `TITLE_AND_TWO_COLUMNS`, `TITLE_ONLY`, `SECTION_HEADER`, `CAPTION_ONLY`, `BIG_NUMBER`

### `scripts/gdrive.py` — Google Drive

```bash
uv run scripts/gdrive.py list [--query "mimeType='application/vnd.google-apps.document'"] [--folder-id ID]
uv run scripts/gdrive.py search "quarterly report" [--max-results 20]
uv run scripts/gdrive.py get-file-info <FILE_ID>
uv run scripts/gdrive.py download <FILE_ID> [--format text|html|pdf|docx|xlsx|csv]
```

### `scripts/gmail.py` — Gmail

```bash
uv run scripts/gmail.py list [--query "is:unread"] [--label INBOX] [--max-results 10]
uv run scripts/gmail.py read <MESSAGE_ID>
uv run scripts/gmail.py search "from:user@example.com subject:invoice" [--max-results 10]
uv run scripts/gmail.py list-labels
uv run scripts/gmail.py get-thread <THREAD_ID>
uv run scripts/gmail.py mark-read <MESSAGE_ID>
uv run scripts/gmail.py mark-unread <MESSAGE_ID>
```

### `scripts/gcalendar.py` — Google Calendar

```bash
uv run scripts/gcalendar.py list-events [--time-min ISO] [--time-max ISO] [--max-results 10]
uv run scripts/gcalendar.py get-event <EVENT_ID> [--calendar-id primary]
uv run scripts/gcalendar.py create-event --summary "Meeting" --start "2025-01-20T10:00:00-05:00" --end "2025-01-20T11:00:00-05:00" [--description "..."] [--location "..."] [--attendees a@x.com b@x.com]
uv run scripts/gcalendar.py update-event <EVENT_ID> [--summary "New title"] [--start ISO] [--end ISO]
uv run scripts/gcalendar.py delete-event <EVENT_ID>
uv run scripts/gcalendar.py search-events "standup" [--max-results 10]
uv run scripts/gcalendar.py list-calendars
```

## Common Patterns

### Find a Doc then read it

```bash
uv run scripts/gdrive.py search "design doc"
# grab the ID from output, then:
uv run scripts/gdocs.py read 1AbCdEfGhIjKlMnOpQrStUvWxYz
```

### Create a formatted document

```bash
uv run scripts/gdocs.py create --title "My Report"
# Use the returned document_id:
uv run scripts/gdocs.py write-formatted-section <DOC_ID> --content '[
  {"type":"h1","text":"Executive Summary"},
  {"type":"text","text":"This report covers Q4 metrics."},
  {"type":"h2","text":"Revenue"},
  {"type":"bullet","text":"Total: $1.2M"},
  {"type":"bullet","text":"Growth: 15% QoQ"}
]'
uv run scripts/gdocs.py insert-styled-table <DOC_ID> \
  --headers "Metric,Q3,Q4,Change" \
  --rows '[["Revenue","$1.0M","$1.2M","+20%"],["Users","50K","62K","+24%"]]'
uv run scripts/gdocs.py format-document <DOC_ID>
```

## Gotchas

- **Table data with commas/parens:** Always use JSON arrays for `--rows`, never comma-delimited strings, when cell values contain commas or special characters.
- **`write-formatted-section` content:** Must be valid JSON. Avoid `#` characters inside text values — they can cause parse issues in some agents' JSON handling. Use `insert-heading` + `append` as a workaround.
- **`append` is plain text only.** It does not render markdown. Use `insert-heading` for headings and `format-text` for styling.
- **Quota project:** If you get `SERVICE_DISABLED` or `quota project` errors, the scripts try to auto-set the quota project to `ck-orp-nick-dev`. If that fails, run the setup commands above.
- **Scope errors (`ACCESS_TOKEN_SCOPE_INSUFFICIENT`):** Re-run the `gcloud auth application-default login` command from the setup section.
- **Rate limits:** Google APIs have per-second quotas. If you hit them, wait a few seconds and retry.
- **Exit codes:** 0 = success, 1 = error. Errors include a JSON `{"error": "..."}` message on stdout.
- **All scripts are self-contained.** Each bundles its own auth code so `uv run` works without import dependencies.

## Troubleshooting

| Error | Fix |
|-------|-----|
| `ACCESS_TOKEN_SCOPE_INSUFFICIENT` | Re-run gcloud login with all scopes (see setup) |
| `SERVICE_DISABLED` / quota errors | Enable APIs on your project, set quota project |
| `gcloud CLI not found` | Install gcloud: https://cloud.google.com/sdk/docs/install |
| `Document not found` | Check ID is correct; use `gdrive.py search` to find it |
| `Permission denied` | Check document sharing settings in Drive |
| `uv: command not found` | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
