# BUILD Stage

Implement the task below.

## Current Task

```json
{{TASK_JSON}}
```

**Task**: {{TASK_NAME}}
**Spec**: `ralph/specs/{{SPEC_FILE}}`
**Is Retry**: {{IS_RETRY}}

{{#if IS_RETRY}}
## Retry Context

This task was previously rejected:
> {{TASK_REJECT}}

**Do NOT re-explore the codebase.** The code is already there. Fix the specific gap identified above.
{{/if}}

## Implementation Notes

{{TASK_NOTES}}

## Acceptance Criteria

{{TASK_ACCEPT}}

## Instructions

1. **Implement the task** - complete implementations only, no stubs
2. **Check acceptance criteria** before marking done
3. **Use subagents for research** (>3 files) - your context is limited

### Subagent Usage

For codebase research, spawn subagents:
```
Task: "Find how X is implemented. Report: files, current behavior, changes needed for Y"
```

### Running Tests

**Always redirect test output to logs:**
```bash
mkdir -p build/logs
make build > build/logs/build.log 2>&1 && make test > build/logs/test.log 2>&1
echo "Exit code: $?"
```

**Only check exit code.** Do NOT read log files unless tests fail.
If tests fail, read LAST 50 lines of `build/logs/test.log` to diagnose.

### Timeout/Hang Failures - ESCALATE, DON'T RETRY

If tests **timeout or hang** (no clear error, just stops):

1. **Do NOT guess at fixes** - async bugs require execution traces
2. **Capture with rr** (if available):
   ```bash
   timeout 120 rr record --chaos build/test_<name> 2>&1 || true
   ```
3. **Create issue and move on**:
   ```
   ralph2 issue add "Test <name> hangs. rr recording captured. Needs human debugging."
   ```

Signs to escalate: timeout with no error, intermittent failures, TSAN races.

### Completing the Task

When implementation passes acceptance criteria:
```
ralph2 task done
```

## Issue Discovery

Record problems you notice (even if unrelated):
```
ralph2 issue add "description"
```

**Always report**: test warnings, compiler warnings, TODOs, potential bugs, missing coverage.

## Spec Ambiguities

**Do NOT interpret ambiguous specs.** Instead:
1. Log: `ralph2 issue add "Spec ambiguity: X vs Y. Options: (1)... (2)..."`
2. Skip or stub the ambiguous part

---

## Spec Content (Reference)

<spec>
{{SPEC_CONTENT}}
</spec>
