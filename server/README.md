# Server Configuration

Reproducible server setup for my personal development/AI/backup server (obelisk).

## Server Purpose

This machine serves as:
- **Test server** - Development and testing environment
- **Backup server** - Image and file backups
- **Coding server** - Remote coding via OpenCode WebUI (accessible on Tailscale)
- **CI system** - GitHub Actions runner for personal repos
- **AI server** - Local LLM inference (3080 Ti)
- **ClawdBot** - Discord/chat bot hosting

## Hardware

- GPU: 3080 Ti (for local LLM)
- Network: Tailscale for secure remote access

## Quick Start

Bootstrap a fresh server with all services:

```bash
./server/bootstrap.sh
```

Or install services individually:

```bash
./server/opencode/install.sh
./server/ci/install.sh
# etc...
```

## Services

### OpenCode WebUI
- **Path**: `server/opencode/`
- **Port**: 4096
- **Access**: http://localhost:4096 or http://[tailscale-ip]:4096
- **Docs**: [server/opencode/README.md](opencode/README.md)

### Backup Server
- **Path**: `server/backup/`
- **Status**: TODO
- **Docs**: [server/backup/README.md](backup/README.md)

### CI Server
- **Path**: `server/ci/`
- **Status**: TODO
- **Docs**: [server/ci/README.md](ci/README.md)

### AI/LLM
- **Path**: `server/ai-llm/`
- **Status**: TODO
- **Docs**: [server/ai-llm/README.md](ai-llm/README.md)

### ClawdBot
- **Path**: `server/clawdbot/`
- **Status**: TODO
- **Docs**: [server/clawdbot/README.md](clawdbot/README.md)

## Configuration Management

### Secrets
Secrets (passwords, API keys) are NOT stored in this repo. Instead:
- Set them during installation via prompts
- Or use environment variables
- Or use a separate secrets file (gitignored)

Example: `server/.secrets.env` (gitignored)
```bash
OPENCODE_PASSWORD="your-password"
ANTHROPIC_API_KEY="sk-..."
GITHUB_TOKEN="ghp_..."
```

### Tailscale
All services are configured to be accessible via Tailscale for secure remote access.

Get your Tailscale IP:
```bash
tailscale ip -4
```

## Reproduction Steps

To reproduce this setup on a new machine:

1. **Clone this repo**:
   ```bash
   git clone <repo-url>
   cd neo-mittens
   ```

2. **Install Tailscale**:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   tailscale up
   ```

3. **Run bootstrap script**:
   ```bash
   ./server/bootstrap.sh
   ```

4. **Configure secrets**:
   - Edit service files or create `.secrets.env`
   - Follow prompts during installation

## Management

### All Services
```bash
# Status of all services
./server/status.sh

# Restart all services
./server/restart-all.sh
```

### Individual Services
```bash
# OpenCode
systemctl --user status opencode-webui
systemctl --user restart opencode-webui
journalctl --user -u opencode-webui -f

# Add more as you create them...
```

## Backup

Key files to backup:
- This repo (server configs)
- `~/.config/systemd/user/*.service` (if modified outside repo)
- Service-specific data directories
- Secrets file (if using one)

## TODO

- [ ] Set up backup server (restic? borg?)
- [ ] Configure GitHub Actions runner
- [ ] Install local LLM (ollama? vllm?)
- [ ] Deploy ClawdBot
- [ ] Create monitoring dashboard
- [ ] Set up automated backups of this config
