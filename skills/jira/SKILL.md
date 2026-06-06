---
name: jira
description: >-
  Manage Jira issues, sprints, and boards. Create, update, transition, search, and
  link issues; manage sprints and backlogs; inspect custom fields. Use when the user
  mentions Jira tickets, issues, sprints, boards, backlogs, or JQL queries.
license: MIT
compatibility: Requires Python 3.9+, uv, and a Jira PAT in ~/.config/jira-credentials.json
metadata:
  category: project-management
  system: jira
---

# Jira Issue Management

Use `scripts/jira.py` for all Jira operations. Run with:

```bash
uv run scripts/jira.py <subcommand> [options]
```

Every subcommand supports `--help` and `--json` (raw API response instead of markdown).

## Setup

Credentials live at `~/.config/jira-credentials.json`:

```json
{
  "pat": "your-personal-access-token",
  "base_url": "https://jira.creditkarma.com",
  "project": "FAB",
  "board_id": 1990,
  "team_defaults": {
    "label": "AppPlatformData",
    "scrum_team_field": "customfield_XXXXX",
    "scrum_team_value": "Portals",
    "scrum_team_option_id": "12345",
    "epic_link_field": "customfield_YYYYY",
    "sprint_field": "customfield_ZZZZZ"
  }
}
```

If the file is missing, the script prints setup instructions and exits with code 2.

To create a PAT: Jira > Profile > Personal Access Tokens > Create token.

## Quick Reference

### Reading issues

```bash
uv run scripts/jira.py get-issue FAB-1234
uv run scripts/jira.py get-issue FAB-1234 --no-comments
uv run scripts/jira.py get-issue FAB-1234 --json
```

### Searching (JQL)

```bash
uv run scripts/jira.py search "project = FAB AND status = 'In Progress'"
uv run scripts/jira.py search "assignee = currentUser() AND sprint in openSprints()"
uv run scripts/jira.py search "project = FAB AND created >= -7d" --max-results 10
uv run scripts/jira.py search "text ~ 'search term'"
```

### Creating issues

```bash
uv run scripts/jira.py create-issue --type Story --summary "Implement feature X"
uv run scripts/jira.py create-issue --type Bug --summary "Fix crash" --priority Major \
  --description "Steps to reproduce..." --assignee jsmith
uv run scripts/jira.py create-issue --type Sub-task --summary "Subtask" --parent FAB-1234
uv run scripts/jira.py create-issue --type Story --summary "Feature" --epic-link FAB-11437 \
  --labels "frontend,urgent" --story-points 5
```

Team defaults (label, scrum team) are applied automatically. Use `--skip-team-defaults` to suppress.

After creating an issue, add it to the sprint:

```bash
uv run scripts/jira.py add-to-sprint FAB-9999
```

### Updating issues

```bash
uv run scripts/jira.py update-issue FAB-1234 --summary "New title"
uv run scripts/jira.py update-issue FAB-1234 --assignee jsmith --priority Major
uv run scripts/jira.py update-issue FAB-1234 --labels "backend,blocked"
uv run scripts/jira.py update-issue FAB-1234 --assignee ""   # unassign
```

### Transitioning issues

```bash
uv run scripts/jira.py transition-issue FAB-1234 "In Progress"
uv run scripts/jira.py transition-issue FAB-1234 "Done" --comment "Completed in PR #42"
```

If the target status is invalid, the error lists available transitions.

To check available transitions first:

```bash
uv run scripts/jira.py list-transitions FAB-1234
```

### Comments

```bash
uv run scripts/jira.py add-comment FAB-1234 "Fixed in commit abc123"
```

### Assigning

```bash
uv run scripts/jira.py assign-issue FAB-1234 jsmith
uv run scripts/jira.py assign-issue FAB-1234 ""     # unassign
uv run scripts/jira.py assign-issue FAB-1234 -1     # auto-assign
```

### Sprints & boards

```bash
uv run scripts/jira.py get-board
uv run scripts/jira.py get-sprints
uv run scripts/jira.py get-sprints --state active
uv run scripts/jira.py get-sprint-issues 4567
uv run scripts/jira.py get-sprint-issues 4567 --max-results 20
uv run scripts/jira.py get-backlog
uv run scripts/jira.py get-backlog --max-results 10
uv run scripts/jira.py add-to-sprint FAB-1234
uv run scripts/jira.py add-to-sprint FAB-1234 --sprint-id 4567
```

### Linking issues

```bash
uv run scripts/jira.py link-issues --type "blocks" --inward-issue FAB-100 --outward-issue FAB-200
uv run scripts/jira.py link-issues --type "relates to" --inward-issue FAB-100 --outward-issue FAB-200
```

Link types: `blocks`, `is blocked by`, `relates to`, `duplicates`, `is duplicated by`, `clones`, `is cloned by`.

### Metadata

```bash
uv run scripts/jira.py get-myself
uv run scripts/jira.py get-project
uv run scripts/jira.py get-project --project-key OTHER
uv run scripts/jira.py discover-fields FAB-11438
uv run scripts/jira.py discover-fields FAB-11438 --filter "Portals"
```

## Common Workflows

### Create a story and add to sprint

```bash
uv run scripts/jira.py create-issue --type Story --summary "Build auth flow" \
  --description "Implement OAuth2 flow" --epic-link FAB-11437
# note the returned key, e.g. FAB-9999
uv run scripts/jira.py add-to-sprint FAB-9999
```

### Find my in-progress work

```bash
uv run scripts/jira.py search "assignee = currentUser() AND status = 'In Progress'"
```

### Move an issue through the workflow

```bash
uv run scripts/jira.py transition-issue FAB-1234 "In Progress"
# ... do the work ...
uv run scripts/jira.py transition-issue FAB-1234 "Done" --comment "Resolved in PR #42"
```

### Find the right custom field IDs for team config

```bash
uv run scripts/jira.py discover-fields FAB-11438 --filter "Portals"
uv run scripts/jira.py discover-fields FAB-11438 --json | jq .
```

## Gotchas

- **JQL strings with spaces** must be quoted: `"status = 'In Progress'"`. Use single quotes around status names inside JQL.
- **`--labels` and `--components` on update-issue replace all values**, not append. Read the issue first if you need to preserve existing labels.
- **`transition-issue` uses fuzzy matching** on both transition name and target status name. If you get "Cannot transition", run `list-transitions` first.
- **`add-to-sprint` without `--sprint-id`** auto-detects the active sprint for the configured board. It fails if no sprint is active.
- **Issue types are case-sensitive**: `Story`, `Bug`, `Task`, `Sub-task`, `Epic` (capital first letter).
- **`create-issue` with `--type Sub-task` requires `--parent`**.
- **Assignee is a username** (e.g., `jsmith`), not a display name. Use `get-myself` to check yours.
- **Story points use `customfield_10004`** -- this is the common default. If your instance uses a different field, update team_defaults accordingly.
- **`search` max is capped at 50 results** regardless of `--max-results` value. Use JQL `ORDER BY` + pagination for larger result sets.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Jira API error (auth failure, not found, invalid request) |
| 2 | Configuration error (missing file, missing PAT) |

## Output

- **Default**: human-readable markdown on stdout
- **`--json`**: raw Jira API response as JSON on stdout
- **Diagnostics** (sprint auto-detection, errors): stderr
