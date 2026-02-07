# DECOMPOSE Stage

A task was killed (exceeded context or timeout). Break it into smaller subtasks.

## Failed Task

```json
{{TASK_JSON}}
```

- **Name**: {{TASK_NAME}}
- **Kill reason**: {{KILL_REASON}}
- **Kill log**: {{KILL_LOG_PATH}}

## Instructions

1. **Review the kill log** (if available). The log may be HUGE — use head/tail only:
   ```bash
   head -50 <kill_log_path>    # What started
   tail -100 <kill_log_path>   # Where it stopped
   ```

2. **Use a subagent** to analyze what the task requires and how to break it down.

3. **Create 2-5 subtasks** that:
   - Can each be completed in ONE iteration (< 100k tokens)
   - Have clear, specific scope
   - Together accomplish the original task
   - Use `deps` for ordering if needed

## Output

When done, output your result between markers EXACTLY like this:

```
[RALPH_OUTPUT]
{
  "subtasks": [
    {
      "name": "Extract parser into separate module",
      "notes": "Move parse_expr() and parse_stmt() from src/main.c lines 200-400 to src/parser.c. Update includes.",
      "accept": "make build succeeds and make test passes",
      "deps": []
    },
    {
      "name": "Add error recovery to parser",
      "notes": "In src/parser.c parse_expr(): add synchronization points after syntax errors. Pattern: skip tokens until ';' or '}'.",
      "accept": "echo 'bad syntax;' | ./build/lang exits 1 without crash",
      "deps": []
    }
  ]
}
[/RALPH_OUTPUT]
```

- Each subtask `notes` MUST include specific file paths and approach (min 50 chars)
- Each subtask `accept` MUST be measurable
- Do NOT try to implement anything — just create the breakdown

**You MUST output the [RALPH_OUTPUT] block as your final action before exiting.**
