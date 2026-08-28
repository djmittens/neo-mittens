# yarr RSS Reader

Self-hosted RSS aggregator running as a background service, accessible via Tailscale
from any device (dev machine, work machine, phone). Replaces doom-scrolling YouTube
for tech news, programming articles, hands-on projects, math, and graphics programming.

[yarr](https://github.com/nkanaev/yarr) is a single Go binary with an embedded SQLite
database — no separate database server to operate. It exposes a **Fever API** so native
phone apps can sync read state, and a responsive web UI you can use from any browser.

## Full text + images for aggregators (rss-proxy)

yarr is **stock / unpatched**. Aggregator feeds (Hacker News, Lobsters) carry only a link,
and some sites (e.g. Fabien Sanglard) block yarr's fetcher or hotlink-protect images. Those
problems are solved by a **separate service**, [`server/rssproxy/`](../rssproxy/README.md),
not by modifying yarr.

Selected feeds are subscribed via the proxy (`…/feed?url=<original>`), which rewrites each
item's link to `…/article?url=<original>`. When you hit yarr's **fetch content** button on
an item, yarr crawls that proxy URL; the proxy fetches the real page on demand (stealth
TLS-impersonation) and rewrites images to a referer-fixing endpoint. Net: full text and
working images, and the proxy only scrapes the articles you actually open.

Currently routed through the proxy: Hacker News, Hacker News (200+), Lobsters, Fabien
Sanglard. See the rss-proxy README for details.

## Why yarr (vs Miniflux / FreshRSS)

- **No database to run** — embedded SQLite, one file at `~/.local/share/yarr/storage.db`
  (physically on the 1.7TB `/data` partition via the `/home` bind mount).
- **Single binary, loopback bind + `tailscale serve`** — matches the obelisk pattern
  (the other services on this host are exposed the same way); no reverse proxy needed.
- **Multi-device sync** — Fever API for native apps, or just open the web UI in a browser.
- **Trivial backups** — back up one SQLite file.

## Exposure model

```
wifi / LAN ─X─ (blocked: yarr binds 127.0.0.1 only, nothing on the LAN)

tailnet device ──HTTPS──► tailscale serve (obelisk:7070, tailnet-only) ──► 127.0.0.1:7070 (yarr)
```

yarr listens on **loopback only**. The single network entry point is `tailscale serve`,
which provides a **tailnet-only HTTPS** endpoint. This is why running without auth is safe
here: the home wifi/LAN cannot reach a loopback socket, and the tailnet itself is the auth
boundary.

If you later want push notifications / auto-read rules / multi-user, CommaFeed (embedded
H2 DB, also Fever) is the drop-in upgrade; export OPML from yarr and import there.

## Features

- 🗞️ **Aggregates RSS/Atom feeds** with a clean reading UI
- 🌐 **Network access**: tailnet-only HTTPS via `tailscale serve`
- 📱 **Multi-device**: web UI on any browser + Fever API for native phone apps
- 🔒 **Loopback-bound**: not reachable from the wifi/LAN; tailnet is the auth boundary
- 💾 **Embedded SQLite**: no database server, single-file data
- 🔄 **Auto-restart**: recovers from crashes via systemd

## Quick Start

### 1. Install

```bash
# Downloads the yarr binary to ~/.local/bin and installs the systemd user unit
./server/rss/install.sh
```

The installer will:
1. Download the latest `yarr` linux binary for this architecture (needs `curl` + `unzip`)
2. Create the data dir `~/.local/share/yarr` (user-owned, no sudo)
3. Install + reload the systemd user unit
4. Enable + start the service (binds `127.0.0.1:7070`)
5. Configure `tailscale serve` to expose `https://<host>:7070` (tailnet-only)

### 2. Authentication (none, by design)

This deployment runs **without authentication** (`YARR_AUTH` is unset). This is safe here
because yarr binds **loopback only** and is reachable solely through the tailnet-only
`tailscale serve` HTTPS proxy — the home wifi/LAN cannot reach it. To enable a login anyway:

```bash
systemctl --user edit --full yarr
# add under [Service]:
#   Environment="YARR_AUTH=username:password"
./server/rss/yarr-manager.sh restart
```

### 3. Get access URLs

```bash
./server/rss/yarr-manager.sh access
```

- Local (this host only): `http://localhost:7070`
- Tailnet (HTTPS): `https://obelisk.<your-tailnet>.ts.net:7070`

### 4. Import feeds

A curated starter feed list lives at `server/rss/feeds.opml` (tech news, programming,
hands-on/hardware, math, games/graphics). In the web UI: **Settings → Import** and select
that file.

## Using from your phone

Two options:

**A. Web UI (simplest)** — open `https://obelisk.<tailnet>.ts.net:7070` in your phone
browser over Tailscale. Read state is centralized on the server, so it's already "synced".

**B. Native Fever app** — install a Fever-compatible reader and point it at the Fever
endpoint. Tested apps (from yarr docs): Reeder, ReadKit, Fluent Reader, Unread, Fiery Feeds.

- Server URL: `https://obelisk.<tailnet>.ts.net:7070/fever` (some apps want a trailing `/` —
  try both if the first fails)
- Username / password: none configured. If an app requires non-empty fields, enable
  `YARR_AUTH` first (see "Authentication" above) and use those values.

## Managing the Service

```bash
./server/rss/yarr-manager.sh status     # is it running?
./server/rss/yarr-manager.sh logs       # live logs
./server/rss/yarr-manager.sh restart
./server/rss/yarr-manager.sh stop
./server/rss/yarr-manager.sh disable    # stop autostart
```

Or directly:
```bash
systemctl --user status yarr
journalctl --user -u yarr -f
```

## Configuration

The service is configured via flags + env in the unit (`systemctl --user edit --full yarr`):

| Setting | Where | Default |
|---|---|---|
| Bind address | `-addr` flag | `127.0.0.1:7070` (loopback) |
| Tailnet exposure | `tailscale serve` | `https://<host>:7070` (tailnet-only) |
| Database file | `-db` flag | `~/.local/share/yarr/storage.db` |
| Credentials | `YARR_AUTH` env | unset (no auth) |

To change the port: edit `-addr 127.0.0.1:7070` in the unit, update the serve proxy
(`tailscale serve --https=7070 off` then re-add on the new port), and `restart`.

### Security note

yarr binds **loopback only** (`127.0.0.1`), so it is **not reachable from the wifi/LAN**.
The only network entry point is the `tailscale serve` HTTPS proxy, which is **tailnet-only**.
Running without auth is therefore safe: only your tailnet devices can reach it, over HTTPS.

Do **not** turn this into a public service with `tailscale funnel` (which would expose it to
the internet) without first enabling `YARR_AUTH`.

The serve config is set up by `install.sh`; to manage it manually:
```bash
tailscale serve status                                     # show current proxies
tailscale serve --bg --https=7070 http://127.0.0.1:7070    # (re)create
tailscale serve --https=7070 off                           # remove
```

## Backups

All state (feeds + read/unread) is a single SQLite file: `~/.local/share/yarr/storage.db`
(on the 1.7TB `/data` partition via the `/home` bind mount). Once the `server/backup/`
job exists, point it at that file. A safe ad-hoc snapshot:

```bash
sqlite3 ~/.local/share/yarr/storage.db ".backup ~/yarr-backup-$(date +%F).db"
```

The feed list itself is also version-controlled here as `feeds.opml` (re-importable any time),
so the reader is effectively disposable — switching readers is an OPML export/import.

## Troubleshooting

### Service won't start
```bash
journalctl --user -u yarr -n 50
# Common issues:
# 1. Port 7070 already in use  -> change -addr
# 2. data dir not writable     -> mkdir -p ~/.local/share/yarr
# 3. yarr binary missing       -> re-run ./install.sh
```

### Can't access from phone
```bash
tailscale status            # both devices connected?
tailscale serve status      # is the :7070 proxy present?
# If the proxy is missing, recreate it:
tailscale serve --bg --https=7070 http://127.0.0.1:7070
# Then browse https://<host>.<tailnet>.ts.net:7070
```

### Fever app won't connect
- Confirm the URL includes `/fever` (and try with/without trailing `/`)
- If the app demands a username/password, enable `YARR_AUTH` (see "Authentication") and
  use those values — some Fever clients reject empty credentials
- Check logs: `journalctl --user -u yarr -f` while the app retries

## Uninstall

```bash
./server/rss/yarr-manager.sh stop
./server/rss/yarr-manager.sh disable
tailscale serve --https=7070 off          # remove the tailnet proxy
rm ~/.config/systemd/user/yarr.service
systemctl --user daemon-reload
# Optional: remove binary and data
rm ~/.local/bin/yarr
rm -rf ~/.local/share/yarr
```

## Resources

- [yarr (GitHub)](https://github.com/nkanaev/yarr)
- [yarr Fever API support](https://github.com/nkanaev/yarr/blob/master/doc/fever.md)
- [Tailscale Documentation](https://tailscale.com/kb/)
