---
description: Show Ralph status for current repository
---

Show the current Ralph status.

## Steps

1. Check if `.ralph/` directory exists
   - If not: Report "Ralph not initialized. Run /ralph-init first."

2. Count specs in `.ralph/specs/`:
   ```bash
   find .ralph/specs -name "*.md" | wc -l
   ```

3. If `.ralph/IMPLEMENTATION_PLAN.md` exists, count tasks:
   - Pending: lines matching `^- \[ \]`
   - Completed: lines matching `^- \[x\]`

4. Check for recent logs in `build/ralph-logs/`

5. Report summary:
   ```
   Ralph Status
   ============
   Specs: N files
   Tasks: X pending, Y completed
   Latest log: <path or "none">
   ```
