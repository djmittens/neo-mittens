---
description: Initialize Ralph in the current repository
---

Initialize Ralph Wiggum autonomous development in this repository.

## Steps

1. Create the `.ralph/` directory structure:
   ```
   .ralph/
   ├── PROMPT_plan.md
   ├── PROMPT_build.md
   ├── IMPLEMENTATION_PLAN.md
   └── specs/
   ```

2. Create `.ralph/PROMPT_plan.md` with planning mode instructions

3. Create `.ralph/PROMPT_build.md` with build mode instructions that:
   - Pick ONE task from implementation plan
   - Implement it fully
   - Run tests
   - Commit and push
   - EXIT (so loop restarts fresh)

4. Create empty `.ralph/IMPLEMENTATION_PLAN.md`

5. Create `.ralph/specs/` directory for requirement specs

6. Add to `.gitignore`:
   ```
   .ralph/IMPLEMENTATION_PLAN.md
   build/ralph-logs/
   ```

7. Report what was created

After initialization, the user should:
1. Write specs in `.ralph/specs/`
2. Run `ralph plan` to generate implementation plan
3. Run `ralph` to start building
