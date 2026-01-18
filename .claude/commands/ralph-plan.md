---
description: Generate or update the Ralph implementation plan from specs
---

Generate/update the implementation plan from specs.

## Prerequisites

Check that `.ralph/` exists. If not, tell user to run `/ralph-init` first.

## Steps

1. Read all files in `.ralph/specs/` to understand requirements

2. Study the existing codebase to understand current implementation

3. Compare specs vs implementation (gap analysis):
   - What's specified but not implemented?
   - What's implemented but not in specs?
   - What's partially implemented?
   - What has TODOs, FIXMEs, or placeholders?

4. Create/update `.ralph/IMPLEMENTATION_PLAN.md` with:
   - Prioritized bullet list of tasks
   - Each task should be small enough for one iteration
   - Group by priority (P0 Critical, P1 High, P2 Medium, P3 Low)
   - Include discovered issues

5. DO NOT implement anything - planning only

## Output Format

```markdown
# Implementation Plan

## P0: Critical
- [ ] Task 1
- [ ] Task 2

## P1: High  
- [ ] Task 3

## Completed
- [x] Done task

## Discovered Issues
- Issue description
```
