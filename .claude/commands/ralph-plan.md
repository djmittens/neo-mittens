---
description: Generate or update the Ralph implementation plan from specs
---

Generate/update the implementation plan from specs.

## Prerequisites

Check that `ralph/` exists. If not, tell user to run `/ralph-init` first.

## Steps

1. Read all files in `ralph/specs/` to understand requirements

2. Study the existing codebase to understand current implementation

3. Compare specs vs implementation (gap analysis):
   - What's specified but not implemented?
   - What's implemented but not in specs?
   - What's partially implemented?
   - What has TODOs, FIXMEs, or placeholders?

4. Create/update `ralph/IMPLEMENTATION_PLAN.md` with:
   - Tasks grouped by their source spec file
   - Each task should be small enough for one iteration
   - Include discovered issues

5. DO NOT implement anything - planning only

## Output Format

```markdown
# Implementation Plan

**Branch:** `<current branch>`
**Last updated:** <timestamp>

## Spec: spec-filename.md

- [ ] Task 1 from this spec
- [ ] Task 2 from this spec

## Spec: another-spec.md

- [ ] Task 1 from another spec

## Completed

- [x] Done task

## Discovered Issues

- Issue description
```

Note: Tasks MUST be grouped under `## Spec: <filename>` headers so that during implementation, only the relevant spec is read and validated against.
