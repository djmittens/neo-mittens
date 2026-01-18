#!/usr/bin/env python3
"""
Ralph Wiggum - Autonomous AI Development Loop
https://ghuntley.com/ralph/

Usage: ralph [command] [options]
  ralph              - Build mode, unlimited iterations
  ralph 10           - Build mode, max 10 iterations
  ralph plan         - Plan mode, generate implementation plan
  ralph init         - Initialize ralph in current repo
  ralph status       - Show current status
  ralph watch        - Live dashboard
  ralph log          - Tail the current log
  ralph metrics      - Show session metrics

Options:
  --max-cost N             Stop when cumulative cost exceeds $N
  --max-failures N         Circuit breaker: stop after N consecutive failures (default: 3)
  --completion-promise T   Stop when output contains TEXT
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# Colors
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color


@dataclass
class Metrics:
    total_cost: float = 0.0
    total_iterations: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    failures: int = 0
    successes: int = 0
    started_at: Optional[str] = None

    def save(self, path: Path):
        path.write_text(json.dumps(self.__dict__, indent=2))

    @classmethod
    def load(cls, path: Path) -> 'Metrics':
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return cls(**data)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()


@dataclass
class RalphConfig:
    repo_root: Path
    ralph_dir: Path
    log_dir: Path
    prompt_plan: Path
    prompt_build: Path
    impl_plan: Path
    specs_dir: Path
    metrics_file: Path

    @classmethod
    def from_repo(cls, repo_root: Path) -> 'RalphConfig':
        ralph_dir = repo_root / 'ralph'
        log_dir = repo_root / 'build' / 'ralph-logs'
        return cls(
            repo_root=repo_root,
            ralph_dir=ralph_dir,
            log_dir=log_dir,
            prompt_plan=ralph_dir / 'PROMPT_plan.md',
            prompt_build=ralph_dir / 'PROMPT_build.md',
            impl_plan=ralph_dir / 'IMPLEMENTATION_PLAN.md',
            specs_dir=ralph_dir / 'specs',
            metrics_file=log_dir / 'metrics.json',
        )


def find_repo_root() -> Optional[Path]:
    """Find git repository root."""
    dir = Path.cwd()
    while dir != dir.parent:
        if (dir / '.git').exists():
            return dir
        dir = dir.parent
    return None


def get_current_branch() -> str:
    """Get current git branch name."""
    try:
        result = subprocess.run(
            ['git', 'branch', '--show-current'],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return 'unknown'


def count_running_opencode(repo_root: Path) -> int:
    """Count opencode processes spawned by ralph in this repo."""
    count = 0
    try:
        result = subprocess.run(['pgrep', '-x', 'opencode'], capture_output=True, text=True)
        for pid in result.stdout.strip().split('\n'):
            if not pid:
                continue
            try:
                # Check if it's in this repo
                cwd = Path(f'/proc/{pid}/cwd').resolve()
                if not str(cwd).startswith(str(repo_root)):
                    continue
                
                # Check if parent is ralph (python running ralph.py)
                ppid = Path(f'/proc/{pid}/stat').read_text().split()[3]
                parent_cmdline = Path(f'/proc/{ppid}/cmdline').read_bytes().decode('utf-8', errors='replace')
                if 'ralph' in parent_cmdline:
                    count += 1
            except (OSError, PermissionError, FileNotFoundError):
                pass
    except subprocess.CalledProcessError:
        pass
    return count


def parse_impl_plan(path: Path) -> dict:
    """Parse implementation plan for task counts."""
    result = {'pending': 0, 'done': 0, 'next_task': None, 'issues': {'open': 0, 'fixed': 0, 'items': []}}
    
    if not path.exists():
        return result
    
    content = path.read_text()
    
    # Count tasks
    result['pending'] = len(re.findall(r'^- \[ \]', content, re.MULTILINE))
    result['done'] = len(re.findall(r'^- \[x\]', content, re.MULTILINE | re.IGNORECASE))
    
    # Get next task
    match = re.search(r'^- \[ \] (.+)$', content, re.MULTILINE)
    if match:
        result['next_task'] = match.group(1)
    
    # Parse discovered issues section
    issues_match = re.search(r'## Discovered Issues\n(.*?)(?=\n## |\Z)', content, re.DOTALL)
    if issues_match:
        issues_section = issues_match.group(1)
        result['issues']['open'] = len(re.findall(r'^- \[ \]', issues_section, re.MULTILINE))
        result['issues']['open'] += len(re.findall(r'^- [^\[]', issues_section, re.MULTILINE))
        result['issues']['fixed'] = len(re.findall(r'^- \[[xX]\]', issues_section, re.MULTILINE))
        # Extract individual issue items with their status
        for line in issues_section.split('\n'):
            line = line.strip()
            if line.startswith('- [ ] '):
                result['issues']['items'].append(('open', line[6:]))
            elif re.match(r'^- \[[xX]\] ', line):
                result['issues']['items'].append(('fixed', line[6:]))
            elif line.startswith('- ') and not line.startswith('- ('):
                # Plain bullet (not placeholder text)
                result['issues']['items'].append(('open', line[2:]))
    
    return result


def extract_costs_from_log(log_path: Path) -> list[tuple[float, int, int]]:
    """Extract all cost entries from ralph-stream output in log file.
    
    Looks for lines like: Cost: $0.1234 | Tokens: 1000in/500out (cache: 123)
    Returns list of (cost, tokens_in, tokens_out) tuples.
    """
    results = []
    
    if not log_path.exists():
        return results
    
    try:
        content = log_path.read_text()
        for match in re.finditer(r'Cost: \$([0-9.]+) \| Tokens: (\d+)in/(\d+)out', content):
            results.append((
                float(match.group(1)),
                int(match.group(2)),
                int(match.group(3))
            ))
    except Exception:
        pass
    
    return results


# ============================================================================
# Commands
# ============================================================================

def cmd_init(config: RalphConfig):
    """Initialize ralph in current repo."""
    if config.ralph_dir.exists():
        print(f"{Colors.YELLOW}Ralph already initialized in this repo{Colors.NC}")
        print(f"  {config.ralph_dir}")
        return

    print(f"{Colors.BLUE}Initializing Ralph in {config.repo_root}{Colors.NC}")
    
    config.ralph_dir.mkdir(parents=True, exist_ok=True)
    config.specs_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)

    # Create plan prompt
    config.prompt_plan.write_text('''\
0a. Run `git branch --show-current` to identify the current branch.
0b. Study `ralph/specs/*` to learn the project specifications.
0c. Study the source code to understand the current implementation.

## Task: Gap Analysis

Compare specs against the CURRENT codebase and generate a fresh task list:

1. Use subagents to study specs and source code thoroughly
2. For each spec requirement, check if it's already implemented
3. Create tasks ONLY for what's missing or broken
4. DO NOT implement anything - planning only

## Updating an Existing Plan

The plan is disposable - regenerate it based on current reality, not the old plan.

If @ralph/IMPLEMENTATION_PLAN.md exists:
- IGNORE the old pending tasks (they may be stale)
- KEEP the "## Completed" section as historical record
- KEEP the "## Discovered Issues" section
- Generate NEW pending tasks from fresh gap analysis

## Output

Write @ralph/IMPLEMENTATION_PLAN.md with:

```markdown
# Implementation Plan

**Branch:** `<current branch>`
**Last updated:** <timestamp>

## Pending Tasks

- [ ] Task 1 (highest priority)
- [ ] Task 2
...

## Completed

- [x] Previous completed tasks (preserve from old plan)

## Discovered Issues

- Issues found during implementation (preserve from old plan)
```

Rules:
- Each task should be completable in ONE iteration
- Order by priority (most important first)
- Be specific - "Add X to Y" not "Improve Z"
''')

    # Create build prompt
    config.prompt_build.write_text('''\
0a. Run `git branch --show-current` to identify the current branch.
0b. Study `ralph/specs/*` to understand requirements.
0c. Study @ralph/IMPLEMENTATION_PLAN.md for current task list.

## Branch Awareness

IMPORTANT: Check the **Branch:** field in @ralph/IMPLEMENTATION_PLAN.md.
- If it matches current branch, continue with tasks.
- If it doesn't match, the plan is from different work - proceed carefully or run `ralph plan` first.
- Update **Last updated:** when you complete a task.

## CRITICAL: ONE TASK, THEN EXIT

1. Pick ONE incomplete item from @ralph/IMPLEMENTATION_PLAN.md
2. Implement it (search first - don't assume not implemented)
3. Run tests to validate
4. Update @ralph/IMPLEMENTATION_PLAN.md (mark complete, update timestamp)
5. `git add -A && git commit && git push`
6. **EXIT** - the loop restarts you fresh

## Progress Reporting

```
[RALPH] BRANCH: <current branch>
[RALPH] === START: <task> ===
[RALPH] FILE: <file>
```

```
[RALPH] === DONE: <task> ===
[RALPH] RESULT: <summary>
```

## Issue Handling

1. Document issues in @ralph/IMPLEMENTATION_PLAN.md under "## Discovered Issues"
2. DO NOT work around problems - fix them or document them
3. If stuck >5 min, document and EXIT

## Rules

- ONE task, then EXIT
- Complete implementations only, no stubs
- No comments in code unless asked
''')

    # Create implementation plan
    branch = get_current_branch()
    config.impl_plan.write_text(f'''\
# Implementation Plan

**Branch:** `{branch}`
**Last updated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

Run `ralph plan` to generate this from specs.

## Pending Tasks

- [ ] (Add tasks here or run `ralph plan`)

## Completed

- (Tasks move here when done)

## Discovered Issues

- (Document issues found during implementation)
''')

    # Create example spec
    (config.specs_dir / 'example.md').write_text('''\
# Example Specification

Delete this file and create your own specs.

## Overview

Describe what you want to build.

## Requirements

- Requirement 1
- Requirement 2

## Acceptance Criteria

- [ ] Criterion 1
- [ ] Criterion 2
''')

    # Add logs to gitignore
    gitignore = config.repo_root / '.gitignore'
    if gitignore.exists():
        content = gitignore.read_text()
        if 'build/ralph-logs' not in content:
            with gitignore.open('a') as f:
                f.write('\n# Ralph logs\nbuild/ralph-logs/\n')

    print(f"{Colors.GREEN}Ralph initialized!{Colors.NC}")
    print()
    print("Next steps:")
    print("  1. Write specs in ralph/specs/")
    print("  2. Run 'ralph plan' to generate implementation plan")
    print("  3. Run 'ralph' to start building")
    print()
    print("Files created:")
    print(f"  {config.ralph_dir}/")
    print("  ├── PROMPT_plan.md    (planning mode prompt)")
    print("  ├── PROMPT_build.md   (build mode prompt)")
    print("  ├── IMPLEMENTATION_PLAN.md")
    print("  └── specs/")
    print("      └── example.md    (delete and add your own)")


def cmd_status(config: RalphConfig):
    """Show current status."""
    if not config.ralph_dir.exists():
        print(f"{Colors.YELLOW}Ralph not initialized. Run 'ralph init' first.{Colors.NC}")
        return 1

    print(f"{Colors.BLUE}Ralph Status{Colors.NC}")
    print(f"  Repo: {config.repo_root}")
    print(f"  Ralph dir: {config.ralph_dir}")
    print()
    
    # Count specs
    spec_count = len(list(config.specs_dir.glob('*.md'))) if config.specs_dir.exists() else 0
    print(f"  Specs: {spec_count} files")
    
    # Count tasks
    plan = parse_impl_plan(config.impl_plan)
    print(f"  Tasks: {plan['pending']} pending, {plan['done']} completed")
    
    # Running status
    running = count_running_opencode(config.repo_root)
    if running > 0:
        print(f"  Status: {Colors.GREEN}Running{Colors.NC} ({running} process(es))")
    else:
        print(f"  Status: {Colors.YELLOW}Stopped{Colors.NC}")
    
    # Latest log
    logs = sorted(config.log_dir.glob('ralph-*.log'), key=lambda p: p.stat().st_mtime, reverse=True)
    if logs:
        print(f"  Latest log: {logs[0]}")
    
    # Metrics
    print()
    metrics = Metrics.load(config.metrics_file)
    print(f"{Colors.CYAN}Session Metrics:{Colors.NC}")
    print(f"  Cost:       ${metrics.total_cost:.4f}")
    print(f"  Iterations: {metrics.total_iterations} ({metrics.successes} ok, {metrics.failures} failed)")
    print(f"  Tokens:     {metrics.total_tokens_in} in / {metrics.total_tokens_out} out")


def cmd_metrics(config: RalphConfig):
    """Show detailed metrics."""
    if not config.metrics_file.exists():
        print(f"{Colors.YELLOW}No metrics available. Run 'ralph' first.{Colors.NC}")
        return 1
    
    metrics = Metrics.load(config.metrics_file)
    print(f"{Colors.BLUE}Ralph Session Metrics{Colors.NC}")
    print()
    print(f"  Cost:       ${metrics.total_cost:.4f}")
    print(f"  Iterations: {metrics.total_iterations}")
    print(f"  Successes:  {metrics.successes}")
    print(f"  Failures:   {metrics.failures}")
    print(f"  Tokens in:  {metrics.total_tokens_in}")
    print(f"  Tokens out: {metrics.total_tokens_out}")
    if metrics.started_at:
        print(f"  Started:    {metrics.started_at}")
    print()
    print(f"Raw file: {config.metrics_file}")


def cmd_log(config: RalphConfig):
    """Tail the current log."""
    logs = sorted(config.log_dir.glob('ralph-*.log'), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        print(f"{Colors.YELLOW}No logs found{Colors.NC}")
        return 1
    
    latest = logs[0]
    print(f"{Colors.BLUE}Tailing: {latest}{Colors.NC}")
    subprocess.run(['tail', '-f', str(latest)])


def cmd_watch(config: RalphConfig):
    """Live dashboard."""
    print(f"{Colors.BLUE}Watching ralph progress... (Ctrl+C to stop){Colors.NC}")
    
    # ANSI codes
    CLEAR_LINE = '\033[K'  # Clear from cursor to end of line
    HIDE_CURSOR = '\033[?25l'
    SHOW_CURSOR = '\033[?25h'
    
    def printl(text=''):
        """Print line and clear to end (prevents leftover chars)."""
        print(f"{text}{CLEAR_LINE}")
    
    # Hide cursor and clear screen once at start
    print(HIDE_CURSOR, end='')
    print('\033[2J\033[H', end='')
    
    try:
        while True:
            # Move cursor to home position (no clear)
            print('\033[H', end='')
            
            printl(f"{Colors.BLUE}══════════════════════════════════════════════════════════════{Colors.NC}")
            printl(f"{Colors.BLUE}  RALPH WATCH - {datetime.now().strftime('%H:%M:%S')}{Colors.NC}")
            printl(f"{Colors.BLUE}══════════════════════════════════════════════════════════════{Colors.NC}")
            printl()
            
            # Branch
            printl(f"{Colors.GREEN}Branch:{Colors.NC} {get_current_branch()}")
            printl()
            
            # Running status
            running = count_running_opencode(config.repo_root)
            if running > 0:
                printl(f"{Colors.GREEN}Status:{Colors.NC} Running ({running})")
            else:
                printl(f"{Colors.YELLOW}Status:{Colors.NC} Stopped")
            printl()
            
            # Metrics
            metrics = Metrics.load(config.metrics_file)
            printl(f"{Colors.CYAN}Session:{Colors.NC} ${metrics.total_cost:.4f} | {metrics.total_iterations} iterations ({metrics.successes} ok, {metrics.failures} fail)")
            printl()
            
            # Recent commits
            printl(f"{Colors.GREEN}Recent Commits:{Colors.NC}")
            try:
                result = subprocess.run(
                    ['git', '--no-pager', 'log', '--oneline', '--since=5 minutes ago'],
                    capture_output=True, text=True, cwd=config.repo_root
                )
                commits = result.stdout.strip().split('\n')[:5]
                if commits and commits[0]:
                    for c in commits:
                        printl(f"  {c}")
                else:
                    printl("  (none in last 5 min)")
            except Exception:
                printl("  (error reading commits)")
            printl()
            
            # Current task
            plan = parse_impl_plan(config.impl_plan)
            printl(f"{Colors.GREEN}Next Task:{Colors.NC}")
            if plan['next_task']:
                printl(f"  {plan['next_task']}")
            else:
                printl("  (no pending tasks)")
            printl()
            
            # Progress
            printl(f"{Colors.GREEN}Progress:{Colors.NC} {plan['done']} done, {plan['pending']} pending")
            printl()
            
            # Issues
            total_issues = plan['issues']['open'] + plan['issues']['fixed']
            if total_issues > 0:
                printl(f"{Colors.YELLOW}Discovered Issues:{Colors.NC} ({plan['issues']['open']} open, {plan['issues']['fixed']} fixed)")
                for i, (status, text) in enumerate(plan['issues']['items'][:5]):
                    if status == 'fixed':
                        printl(f"  {Colors.GREEN}FIXED{Colors.NC} {text}")
                    else:
                        printl(f"  {Colors.RED}OPEN{Colors.NC}  {text}")
                if len(plan['issues']['items']) > 5:
                    printl(f"  {Colors.YELLOW}... and {len(plan['issues']['items']) - 5} more{Colors.NC}")
                printl()
            
            # Latest log lines
            printl(f"{Colors.GREEN}Latest Output:{Colors.NC}")
            logs = sorted(config.log_dir.glob('ralph-*.log'), key=lambda p: p.stat().st_mtime, reverse=True)
            if logs and logs[0].exists():
                try:
                    lines = logs[0].read_text().splitlines()[-8:]
                    for line in lines:
                        printl(f"  {line[:80]}")
                except Exception:
                    printl("  (error reading log)")
            else:
                printl("  (no output yet)")
            printl()
            printl(f"{Colors.BLUE}──────────────────────────────────────────────────────────────{Colors.NC}")
            printl("Refreshing every 5s...")
            
            # Clear any remaining lines from previous render (e.g., if issues shrunk)
            print('\033[J', end='', flush=True)
            
            time.sleep(5)
    except KeyboardInterrupt:
        print(SHOW_CURSOR, end='')
        print("\nStopped watching.")
    finally:
        # Always restore cursor visibility
        print('\033[?25h', end='', flush=True)


def cmd_run(config: RalphConfig, mode: str, max_iterations: int, max_cost: float,
            max_failures: int, completion_promise: str):
    """Run the main loop."""
    if not config.ralph_dir.exists():
        print(f"{Colors.RED}Ralph not initialized. Run 'ralph init' first.{Colors.NC}")
        return 1

    prompt_file = config.prompt_plan if mode == 'plan' else config.prompt_build
    if not prompt_file.exists():
        print(f"{Colors.RED}Prompt file not found: {prompt_file}{Colors.NC}")
        return 1

    # Initialize metrics
    metrics = Metrics(started_at=datetime.now().isoformat())
    config.log_dir.mkdir(parents=True, exist_ok=True)
    
    branch = get_current_branch()
    session_id = datetime.now().strftime('%Y%m%d-%H%M%S')
    log_file = config.log_dir / f'ralph-{session_id}.log'
    json_log = config.log_dir / f'ralph-{session_id}.json'
    
    consecutive_failures = 0

    print(f"{Colors.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
    print(f"Mode:   {Colors.GREEN}{mode}{Colors.NC}")
    print(f"Branch: {branch}")
    print(f"Log:    {log_file}")
    if max_iterations > 0:
        print(f"Max iterations: {max_iterations}")
    if max_cost > 0:
        print(f"Max cost:       ${max_cost}")
    print(f"Circuit breaker: {max_failures} consecutive failures")
    if completion_promise:
        print(f"Completion:     \"{completion_promise}\"")
    print(f"{Colors.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")

    iteration = 0
    try:
        while True:
            # Check iteration limit
            if max_iterations > 0 and iteration >= max_iterations:
                print(f"{Colors.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
                print(f"Reached max iterations: {max_iterations}")
                print(f"{Colors.CYAN}Total cost: ${metrics.total_cost:.4f}{Colors.NC}")
                print(f"{Colors.BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
                break

            # Check cost limit
            if max_cost > 0 and metrics.total_cost >= max_cost:
                print(f"{Colors.YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
                print(f"{Colors.YELLOW}COST LIMIT REACHED{Colors.NC}")
                print(f"Spent: ${metrics.total_cost:.4f} / ${max_cost}")
                print(f"{Colors.YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
                break

            # Check circuit breaker
            if consecutive_failures >= max_failures:
                print(f"{Colors.RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
                print(f"{Colors.RED}CIRCUIT BREAKER TRIPPED{Colors.NC}")
                print(f"{consecutive_failures} consecutive failures detected")
                print(f"{Colors.RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
                break

            iteration += 1
            metrics.total_iterations += 1
            start_time = time.time()

            # Cost display
            if max_cost > 0:
                cost_display = f" | Cost: ${metrics.total_cost:.4f}/${max_cost}"
            else:
                cost_display = f" | Cost: ${metrics.total_cost:.4f}"

            print()
            print(f"{Colors.GREEN}╔═══════════════════════════════════════════════════════════════╗{Colors.NC}")
            print(f"{Colors.GREEN}║  ITERATION {iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{cost_display}{Colors.NC}")
            print(f"{Colors.GREEN}╚═══════════════════════════════════════════════════════════════╝{Colors.NC}")
            print()

            # Run opencode
            prompt_content = prompt_file.read_text()
            script_dir = Path(__file__).parent
            ralph_stream = script_dir / 'ralph-stream'

            if ralph_stream.exists() and os.access(ralph_stream, os.X_OK):
                # Write prompt to temp file to avoid shell escaping issues
                prompt_tmp = config.log_dir / f'prompt-{session_id}-{iteration}.txt'
                prompt_tmp.write_text(prompt_content)
                
                # Stream JSON through ralph-stream, only save human-readable log
                cmd = f'opencode run --model anthropic/claude-opus-4-5 --format json "$(cat {prompt_tmp})" 2>&1 | {ralph_stream} | tee -a {log_file}'
                
                process = subprocess.Popen(
                    ['bash', '-c', cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=config.repo_root
                )
                
                # Stream output to terminal
                if process.stdout:
                    for line in iter(process.stdout.readline, b''):
                        sys.stdout.write(line.decode('utf-8', errors='replace'))
                        sys.stdout.flush()
                
                process.wait()
                exit_code = process.returncode
                
                # Cleanup temp prompt file
                prompt_tmp.unlink(missing_ok=True)
            else:
                # Fallback without streaming filter
                result = subprocess.run(
                    ['opencode', 'run', '--model', 'anthropic/claude-opus-4-5', prompt_content],
                    cwd=config.repo_root,
                    capture_output=False
                )
                exit_code = result.returncode

            duration = int(time.time() - start_time)

            # Extract costs from log (ralph-stream outputs cost lines)
            # Sum all cost entries from this session's log
            all_costs = extract_costs_from_log(log_file)
            if all_costs:
                metrics.total_cost = sum(c[0] for c in all_costs)
                metrics.total_tokens_in = sum(c[1] for c in all_costs)
                metrics.total_tokens_out = sum(c[2] for c in all_costs)

            # Track success/failure
            if exit_code == 0:
                consecutive_failures = 0
                metrics.successes += 1
            else:
                consecutive_failures += 1
                metrics.failures += 1

            print()
            print(f"{Colors.BLUE}┌───────────────────────────────────────────────────────────────┐{Colors.NC}")
            print(f"{Colors.BLUE}│  Iteration {iteration}: {duration}s (total: ${metrics.total_cost:.4f}){Colors.NC}")
            print(f"{Colors.BLUE}│  Exit: {exit_code} | Failures: {consecutive_failures}/{max_failures}{Colors.NC}")
            print(f"{Colors.BLUE}└───────────────────────────────────────────────────────────────┘{Colors.NC}")

            # Save metrics
            metrics.save(config.metrics_file)

            # Check completion promise
            if completion_promise and log_file.exists():
                if completion_promise in log_file.read_text():
                    print(f"{Colors.GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
                    print(f"{Colors.GREEN}COMPLETION PROMISE DETECTED{Colors.NC}")
                    print(f"Found: {completion_promise}")
                    print(f"{Colors.GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Colors.NC}")
                    break

            # Push changes
            try:
                subprocess.run(['git', 'push', 'origin', branch], 
                             capture_output=True, cwd=config.repo_root)
            except Exception:
                try:
                    subprocess.run(['git', 'push', '-u', 'origin', branch],
                                 capture_output=True, cwd=config.repo_root)
                except Exception:
                    pass

            # Show recent commits
            print()
            print("Recent commits:")
            try:
                result = subprocess.run(
                    ['git', 'log', '--oneline', '-3'],
                    capture_output=True, text=True, cwd=config.repo_root
                )
                print(result.stdout)
            except Exception:
                pass

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted by user{Colors.NC}")
    finally:
        metrics.save(config.metrics_file)
        print(f"{Colors.CYAN}Session saved: ${metrics.total_cost:.4f} across {metrics.total_iterations} iterations{Colors.NC}")


def main():
    parser = argparse.ArgumentParser(
        description='Ralph Wiggum - Autonomous AI Development Loop',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  ralph init                    Initialize in current repo
  ralph plan                    Generate implementation plan
  ralph                         Build mode, unlimited (Ctrl+C to stop)
  ralph 10                      Build mode, max 10 iterations
  ralph 50 --max-cost 25        Max 50 iterations or $25
  ralph --completion-promise DONE  Stop when DONE appears
  ralph watch                   Live progress dashboard
        '''
    )
    
    parser.add_argument('command', nargs='?', default='build',
                       help='Command: init, plan, build, status, watch, log, metrics, help')
    parser.add_argument('iterations', nargs='?', type=int, default=0,
                       help='Max iterations (0 = unlimited)')
    parser.add_argument('--max-cost', type=float, default=0,
                       help='Stop when cost exceeds $N')
    parser.add_argument('--max-failures', type=int, default=3,
                       help='Circuit breaker: stop after N consecutive failures')
    parser.add_argument('--completion-promise', type=str, default='',
                       help='Stop when output contains this text')

    args = parser.parse_args()

    # Handle numeric first arg (e.g., "ralph 10")
    if args.command and args.command.isdigit():
        args.iterations = int(args.command)
        args.command = 'build'

    # Find repo
    repo_root = find_repo_root()
    if not repo_root:
        print(f"{Colors.RED}Error: Not in a git repository{Colors.NC}")
        sys.exit(1)

    config = RalphConfig.from_repo(repo_root)

    # Dispatch command
    if args.command == 'init':
        cmd_init(config)
    elif args.command == 'status':
        cmd_status(config)
    elif args.command == 'metrics':
        cmd_metrics(config)
    elif args.command == 'log':
        cmd_log(config)
    elif args.command == 'watch':
        cmd_watch(config)
    elif args.command == 'plan':
        cmd_run(config, 'plan', 1, args.max_cost, args.max_failures, args.completion_promise)
    elif args.command in ('build', ''):
        cmd_run(config, 'build', args.iterations, args.max_cost, args.max_failures, args.completion_promise)
    elif args.command == 'help':
        parser.print_help()
    else:
        print(f"{Colors.RED}Unknown command: {args.command}{Colors.NC}")
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
