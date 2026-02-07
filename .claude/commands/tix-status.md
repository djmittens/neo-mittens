---
description: Show tix ticket status for current repository
---

Show the current tix status.

## Steps

1. Check if `.tix/` directory exists
   - If not: Report "tix not initialized. Run `tix init` first."

2. Run `tix query` to get full JSON state

3. Run `tix status` for the human-readable dashboard

4. Report both the structured data and the dashboard
