# neo-mittens userscripts

Tampermonkey/Greasemonkey scripts that bridge browser-based UIs into
local tooling.

Currently:

- **`bnetswitch-lfg.user.js`** — bridges Overwatch Discord's LFG channel
  to the bnetswitch TUI.

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

## Privacy

The script:
- Only POSTs message data from `LFG Tool` bot embeds (filters by author).
- Sends only what's visible in the LFG channel (no DM scraping, no
  private channel reads).
- Communicates exclusively with `127.0.0.1` — nothing leaves the box.
- Uses `GM_xmlhttpRequest` (Tampermonkey's CORS-bypassing fetch) since
  the localhost server has different origin than `discord.com`.
