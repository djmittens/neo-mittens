---
name: ralph-config
description: Configure Ralph user-level settings - model selection, profiles, timeouts, context limits
license: MIT
compatibility: opencode
metadata:
  category: configuration
  tool: ralph
---

# Ralph User Configuration

Use this skill when setting up or modifying Ralph's user-level configuration at `~/.config/ralph/config.toml`.

## Config File Location

```
~/.config/ralph/config.toml
```

Create the directory if it doesn't exist:
```bash
mkdir -p ~/.config/ralph
```

## Quick Setup

Minimal config (uses defaults for everything else):

```toml
[default]
model = "anthropic/claude-sonnet-4"
```

## Full Configuration Reference

```toml
# Ralph Wiggum Configuration
# https://ghuntley.com/ralph/

[default]
# Model to use for AI operations
# Options: anthropic/claude-sonnet-4, anthropic/claude-opus-4, 
#          openrouter/anthropic/claude-opus-4, etc.
model = "anthropic/claude-sonnet-4"

# Context window settings (tokens)
context_window = 200000
context_warn_pct = 70      # Warning threshold
context_compact_pct = 85   # Trigger compaction
context_kill_pct = 95      # Kill iteration

# Timeouts (milliseconds)
stage_timeout_ms = 300000      # 5 min per stage
iteration_timeout_ms = 300000  # 5 min per iteration

# Circuit breaker - stop after N consecutive failures
max_failures = 3

# Maximum decomposition depth for stuck tasks
max_decompose_depth = 3

# Git settings
commit_prefix = "ralph:"
recent_commits_display = 3

# UI settings
# art_style: braille (default), braille_full, blocks, minimal, none
art_style = "braille"
dashboard_buffer_lines = 2000

# Directories
ralph_dir = "ralph"
log_dir = "/tmp/ralph-logs"
```

## Configuration Options

### Model Settings

| Option | Default | Description |
|--------|---------|-------------|
| `model` | `anthropic/claude-opus-4-5` | AI model identifier |

Common model values:
- `anthropic/claude-sonnet-4` - Fast, cost-effective
- `anthropic/claude-opus-4` - Most capable
- `openrouter/anthropic/claude-opus-4` - Opus via OpenRouter

### Context Limits

| Option | Default | Description |
|--------|---------|-------------|
| `context_window` | `200000` | Total context window in tokens |
| `context_warn_pct` | `70` | Warning threshold (%) |
| `context_compact_pct` | `85` | Trigger compaction (%) |
| `context_kill_pct` | `95` | Kill iteration (%) |

**Behavior:**
- At `warn_pct`: Warning logged, execution continues
- At `compact_pct`: Attempt to summarize/compact conversation
- At `kill_pct`: Kill current task, trigger DECOMPOSE stage

### Timeouts

| Option | Default | Description |
|--------|---------|-------------|
| `stage_timeout_ms` | `300000` | Max time per stage (5 min) |
| `iteration_timeout_ms` | `300000` | Max time per iteration (5 min) |

### Circuit Breaker

| Option | Default | Description |
|--------|---------|-------------|
| `max_failures` | `3` | Stop after N consecutive failures |
| `max_decompose_depth` | `3` | Max times a task lineage can decompose |

### Git Settings

| Option | Default | Description |
|--------|---------|-------------|
| `commit_prefix` | `"ralph:"` | Prefix for automated commits |
| `recent_commits_display` | `3` | Show N recent commits in status |

### UI Settings

| Option | Default | Description |
|--------|---------|-------------|
| `art_style` | `"braille"` | ASCII art style |
| `dashboard_buffer_lines` | `2000` | Buffer size for watch dashboard |

Art style options:
- `braille` - Compact braille dot art (default)
- `braille_full` - Full-body braille art
- `blocks` - Block characters (░▒▓█)
- `minimal` - Simple text art
- `none` - No art

### Directories

| Option | Default | Description |
|--------|---------|-------------|
| `ralph_dir` | `"ralph"` | Ralph directory in repo |
| `log_dir` | `"/tmp/ralph-logs"` | Log file directory |

## Profiles

Set up different configurations for different environments:

```toml
[default]
model = "anthropic/claude-sonnet-4"

[profiles.work]
model = "anthropic/claude-opus-4"
stage_timeout_ms = 600000  # 10 min for complex work

[profiles.home]
model = "openrouter/anthropic/claude-opus-4"
art_style = "braille_full"

[profiles.fast]
model = "anthropic/claude-sonnet-4"
stage_timeout_ms = 180000  # 3 min
context_warn_pct = 60
```

Activate a profile with environment variable:
```bash
export RALPH_PROFILE=work
ralph construct my-spec
```

Or inline:
```bash
RALPH_PROFILE=fast ralph construct my-spec
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `RALPH_PROFILE` | Select config profile |
| `RALPH_ART_STYLE` | Override art style (legacy) |

## Example Configurations

### Cost-Conscious Development

```toml
[default]
model = "anthropic/claude-sonnet-4"
stage_timeout_ms = 180000  # 3 min - fail fast
max_failures = 2
context_compact_pct = 75   # Compact earlier
```

### Complex Enterprise Work

```toml
[default]
model = "anthropic/claude-opus-4"
stage_timeout_ms = 900000  # 15 min for complex tasks
iteration_timeout_ms = 900000
context_window = 200000
max_decompose_depth = 5    # Allow deeper decomposition
```

### CI/Headless Mode

```toml
[default]
model = "anthropic/claude-sonnet-4"
art_style = "none"
dashboard_buffer_lines = 500
log_dir = "/var/log/ralph"
```

### OpenRouter Setup

```toml
[default]
model = "openrouter/anthropic/claude-opus-4"

[profiles.cheap]
model = "openrouter/anthropic/claude-sonnet-4"
```

Note: OpenRouter requires `OPENROUTER_API_KEY` environment variable.

## Verifying Configuration

Check that config loads correctly:
```bash
python3 -c "
import sys
sys.path.insert(0, 'powerplant')
from ralph import get_global_config
c = get_global_config()
print(f'Model: {c.model}')
print(f'Profile: {c._profile_name}')
print(f'Stage timeout: {c.stage_timeout_ms}ms')
"
```

Or just run ralph and check the header output shows expected settings.

## Troubleshooting

### Config Not Loading

1. Check file exists: `ls -la ~/.config/ralph/config.toml`
2. Check TOML syntax: `python3 -c "import tomllib; print(tomllib.load(open('$HOME/.config/ralph/config.toml', 'rb')))"`
3. For Python < 3.11, install tomli: `pip install tomli`

### Profile Not Activating

1. Check `RALPH_PROFILE` is exported: `echo $RALPH_PROFILE`
2. Check profile name matches exactly (case-sensitive)
3. Verify profile exists in config file under `[profiles.NAME]`

### Context Issues

If hitting context limits frequently:
- Lower `context_compact_pct` to compact earlier
- Use `max_decompose_depth` to allow more breakdown
- Consider breaking specs into smaller units

## Migration from Legacy

If using environment variables:
- `RALPH_ART_STYLE` still works (backward compatible)
- Move other env-based config to `config.toml` for consistency
