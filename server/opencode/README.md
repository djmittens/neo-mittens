# OpenCode WebUI Automation

Automated setup for running OpenCode WebUI as a background service, accessible via Tailscale from any device (including your phone).

## Features

- 🚀 **Automatic startup**: OpenCode WebUI starts on boot
- 🌐 **Network access**: Accessible via Tailscale from anywhere
- 📱 **Multi-device**: Use from phone, tablet, or any browser
- 🔒 **Secure**: Password-protected access
- 📂 **Multi-project**: Single server handles multiple projects via sessions
- 🔄 **Auto-restart**: Automatically recovers from crashes

## Quick Start

### 1. Initial Setup

```bash
# Run the setup
./opencode-automation/opencode-manager.sh setup

# Set a secure password (edit the full file)
systemctl --user edit --full opencode-webui
```

In the editor, find this line:
```ini
Environment="OPENCODE_SERVER_PASSWORD=change-me-to-secure-password"
```

And change it to your actual password:
```ini
Environment="OPENCODE_SERVER_PASSWORD=your-secure-password-here"
```

Save and exit (Ctrl+X, then Y in nano, or `:wq` in vim).

### 2. Enable and Start

```bash
# Enable autostart on boot
./opencode-automation/opencode-manager.sh enable

# Start the service now
./opencode-automation/opencode-manager.sh start
```

### 3. Get Access URLs

```bash
./opencode-automation/opencode-manager.sh access
```

This will show you:
- Local URL: `http://localhost:4096`
- Tailscale URL: `http://[your-tailscale-ip]:4096`
- MagicDNS URL: `http://[your-hostname]:4096`

## Usage

### Managing the Service

```bash
# Check if running
./opencode-automation/opencode-manager.sh status

# View logs (live)
./opencode-automation/opencode-manager.sh logs

# Restart service
./opencode-automation/opencode-manager.sh restart

# Stop service
./opencode-automation/opencode-manager.sh stop

# Disable autostart
./opencode-automation/opencode-manager.sh disable
```

### Working with Multiple Projects

OpenCode WebUI has built-in multi-project support through **sessions**:

1. **From Web Interface**: 
   - Open the WebUI in your browser
   - Click "New Session" to start a new project
   - Each session maintains its own context and working directory
   - Use the session selector to switch between projects

2. **Via API**:
   ```bash
   # List all projects
   curl http://localhost:4096/project
   
   # Create new session
   curl -X POST http://localhost:4096/session \
     -H "Content-Type: application/json" \
     -d '{"title": "My Project"}'
   ```

3. **Session Management**:
   - Sessions persist across restarts
   - You can have multiple sessions for different projects
   - Each session can be in a different directory
   - Switch between sessions in the web interface

### Accessing from Your Phone

1. **Ensure Tailscale is running** on your computer and phone
2. **Get the access URL**:
   ```bash
   ./opencode-automation/opencode-manager.sh access
   ```
3. **Open your phone's browser** and navigate to the Tailscale URL
4. **Login** with:
   - Username: `opencode`
   - Password: (the password you set)

### Changing the Port

Edit the service file:
```bash
systemctl --user edit --full opencode-webui
```

Change `--port 4096` to your preferred port, then:
```bash
./opencode-automation/opencode-manager.sh restart
```

### Exposing on Tailscale (Security Note)

The service is configured with `--hostname 0.0.0.0`, which means it listens on all network interfaces. This is safe because:

1. **Password protection**: Requires authentication to access
2. **Tailscale network**: Only accessible to devices on your Tailnet (private network)
3. **No public internet**: Not exposed to the public internet

**Important**: Always use a strong password when binding to `0.0.0.0`.

## Troubleshooting

### Service won't start
```bash
# Check logs for errors
./opencode-automation/opencode-manager.sh logs

# Common issues:
# 1. Port already in use - change the port
# 2. OpenCode not installed - install it first
# 3. Missing password - set OPENCODE_SERVER_PASSWORD
```

### Can't access from phone
```bash
# Verify Tailscale is connected on both devices
tailscale status

# Check the IP address
tailscale ip -4

# Test from phone's browser using IP:
# http://[tailscale-ip]:4096
```

### Service keeps restarting
```bash
# Check what's wrong
journalctl --user -u opencode-webui -n 50

# Common causes:
# 1. Invalid configuration
# 2. Permission issues
# 3. Port conflict
```

### Forgot password
```bash
# Reset password (edit the full file)
systemctl --user edit --full opencode-webui

# Find and update the OPENCODE_SERVER_PASSWORD line, then restart
./opencode-automation/opencode-manager.sh restart
```

## Advanced Configuration

### Custom Configuration File

Create `~/.config/opencode/config.json`:
```json
{
  "server": {
    "port": 4096,
    "hostname": "0.0.0.0",
    "mdns": true
  },
  "providers": {
    "anthropic": {
      "apiKey": "your-key"
    }
  }
}
```

### Environment Variables

Edit the service to add more environment variables:
```bash
systemctl --user edit --full opencode-webui
```

Add additional lines under `[Service]`:
```ini
Environment="ANTHROPIC_API_KEY=your-key"
Environment="OPENAI_API_KEY=your-key"
Environment="OPENCODE_LOG_LEVEL=debug"
```

### Running Multiple Instances

To run multiple OpenCode instances on different ports:

1. Copy the service file:
   ```bash
   cp ~/.config/systemd/user/opencode-webui.service \
      ~/.config/systemd/user/opencode-webui-project2.service
   ```

2. Edit the new service to use a different port:
   ```bash
   systemctl --user edit --full opencode-webui-project2
   # Change port to 4097
   ```

3. Enable and start:
   ```bash
   systemctl --user enable --now opencode-webui-project2
   ```

**However**, this is usually not necessary since a single OpenCode server can handle multiple projects through sessions!

## API Access

OpenCode exposes a full REST API at `http://[tailscale-ip]:4096/`

View the API documentation at: `http://[tailscale-ip]:4096/doc`

Example API usage:
```bash
# List all sessions
curl -u opencode:your-password http://localhost:4096/session

# Create new session
curl -u opencode:your-password \
  -X POST http://localhost:4096/session \
  -H "Content-Type: application/json" \
  -d '{"title": "New Project"}'

# Send a message
curl -u opencode:your-password \
  -X POST http://localhost:4096/session/[session-id]/message \
  -H "Content-Type: application/json" \
  -d '{"parts": [{"type": "text", "text": "Hello OpenCode"}]}'
```

## Uninstall

```bash
# Stop and disable service
./opencode-automation/opencode-manager.sh stop
./opencode-automation/opencode-manager.sh disable

# Remove service file
rm ~/.config/systemd/user/opencode-webui.service

# Reload systemd
systemctl --user daemon-reload
```

## Resources

- [OpenCode Documentation](https://opencode.ai/docs/)
- [OpenCode Web Interface](https://opencode.ai/docs/web/)
- [OpenCode Server API](https://opencode.ai/docs/server/)
- [Tailscale Documentation](https://tailscale.com/kb/)

## License

This automation setup is provided as-is for use with OpenCode.
