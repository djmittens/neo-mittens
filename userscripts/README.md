# neo-mittens userscripts

Tampermonkey/Greasemonkey scripts that bridge browser-based UIs into
local tooling.

Currently:

- **`bnetswitch-lfg.user.js`** — bridges Overwatch Discord's LFG channel
  to the bnetswitch TUI.
- **`yarr-apple-news.user.js`** — restyles the stock yarr RSS reader
  (`server/rss/`) to look like Apple News: San Francisco typography,
  near-black iOS surfaces, big bold headlines, rounded cards, and nicer
  code blocks. Pure CSS overlay on yarr's `night` theme — yarr stays the
  stock binary (nothing patched or rebuilt). See "yarr Apple News theme"
  below.

## yarr Apple News theme

A cosmetic-only CSS overlay for [yarr](../server/rss/README.md). It targets
yarr's existing CSS classes (`.theme-night`, `#col-item-list`, `.content`,
`.selectgroup`, …), so the only thing to maintain is this one file; yarr
itself upgrades exactly as before.

- **Install:** open
  `file:///home/xyzyx/src/neo-mittens/userscripts/yarr-apple-news.user.js`
  in your browser, accept the Tampermonkey prompt.
- **Match:** `localhost:7070`, `127.0.0.1:7070`, and `*.ts.net` (your
  `tailscale serve` URL). It only activates on port **7070**; if you move
  yarr, edit `YARR_PORT` at the top of the script.
- **Requires** yarr's theme set to **night** (Settings → theme → night).
- **iPhone/Safari:** Tampermonkey isn't available on iOS — to get the look
  on the phone you'd need the App Store "Userscripts" app, or it simply
  shows yarr's stock night theme there. Desktop browsers work out of the box.
- **Tweak:** colors live in the `:root { --an-* }` block near the top of the
  script (e.g. change `--an-accent` from iOS blue to Apple News red `#f0285a`).

## Why userscripts

Some integrations (Discord LFG) need to act inside an authenticated
browser session. Native tooling either can't (no bot access to that
server) or shouldn't (TOS-violating selfbot, plus selfbots can't share
voice with your real Discord client).

Userscripts let us drive DOM clicks the same way a human would, so:
- Auth stays in the browser, never copied to disk.
- Voice routing happens through your real Discord client's audio path.
- Detection signal looks identical to manual clicks.

Still TOS-questionable; see the bnetswitch LFG module's docstring for
the longer discussion.

## Install

1. Install [Tampermonkey](https://www.tampermonkey.net/) for your
   browser (Firefox / Chromium / Brave / etc.).
2. Open the script source in your browser:
   ```
   file:///home/xyzyx/src/neo-mittens/userscripts/bnetswitch-lfg.user.js
   ```
3. Tampermonkey detects the `// ==UserScript==` header and prompts to
   install. Click "Install".
4. To enable auto-update from a local symlink, add the file to
   Tampermonkey via Settings → Editor → Import file.

## Configure

Open the Tampermonkey dashboard → bnetswitch LFG bridge → Edit.

In the `Config` section near the top:

- **`WATCHED_CHANNEL_IDS`** — leave empty to monitor all channels (less
  efficient), or paste channel IDs to restrict. To get a channel ID:
  enable Discord Developer Mode (Settings → Advanced), right-click the
  channel name → "Copy Channel ID".

- **`BNETSWITCH_HOST`** — defaults to `http://127.0.0.1:7172`. Don't
  change unless you've moved bnetswitch's HTTP server.

- **`BNETSWITCH_TOKEN`** — must match the constant in
  `bnetswitch/src/lfg.rs` (`LFG_AUTH_TOKEN`). Default is shipped
  pre-configured for both sides.

## Verify it's working

1. Run `bnetswitch` (the TUI).
2. Open Discord web client, navigate to OW Discord → `#lfg-pc-na-ranked`.
3. In Tampermonkey dashboard → bnetswitch LFG bridge → "Show editor",
   open the script's logs (or browser console). You should see:
   ```
   [bnetswitch-lfg] bnetswitch LFG bridge starting (v0.1.0)
   [bnetswitch-lfg] server: http://127.0.0.1:7172
   [bnetswitch-lfg] bnetswitch reachable
   [bnetswitch-lfg] MutationObserver attached to <div...>
   ```
4. As LFG embeds are posted, you'll see them in the bnetswitch TUI's
   LFG panel (Phase 4 — coming next).

## Debug

Enable debug-level logging:
```javascript
// In the browser console:
GM_setValue("debug", true);
```

Disable:
```javascript
GM_setValue("debug", false);
```

## Resilience (suspend / dropped sockets)

The bridge keeps itself connected across system suspends and network drops:

- The server sends a `ping` event every ~15s. The userscript treats a >45s
  silence as a dead (half-open) connection and force-reconnects — half-open
  sockets after a suspend often never fire `onerror`, so this is the signal
  that recovers them.
- SSE reconnects with capped exponential backoff and **never permanently
  downgrades** to HTTP polling; polling only bridges the gap until SSE is
  back.
- A wall-clock-gap detector notices when timers were frozen (suspend) and
  rebuilds the connection plus re-backfills the LFG list on resume.
- `visibilitychange` (tab focus) and the `online` event also trigger a
  reconnect + session re-register.

No manual Discord-tab reload should be needed after a suspend or Wi-Fi blip.

## Privacy

The script:
- Only POSTs message data from `LFG Tool` bot embeds (filters by author).
- Sends only what's visible in the LFG channel (no DM scraping, no
  private channel reads).
- Communicates exclusively with `127.0.0.1` — nothing leaves the box.
- Uses `GM_xmlhttpRequest` (Tampermonkey's CORS-bypassing fetch) since
  the localhost server has different origin than `discord.com`.
