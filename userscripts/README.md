# neo-mittens userscripts

Tampermonkey/Greasemonkey scripts that bridge browser-based UIs into
local tooling.

Currently:

- **`bnetswitch-lfg.user.js`** — bridges Overwatch Discord's LFG channel
  to the bnetswitch TUI. Also hides Discord's sponsored Quest bar (see
  "No ads in the voice client" below).
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

## No ads in the voice client

Discord seeds paid surfaces throughout the client: a sponsored Quest bar
(a brand ad with a *Get Reward!* button) above the account panel, Nitro
and Shop tabs in the home sidebar, gift buttons in the chat box, and
Nitro upsells wedged into the emoji picker and profile editor. The LFG
bridge injects a stylesheet at `document-start` that hides all of it, so
none of it even flashes.

Groups are listed in `PROMO_BLOCK_GROUPS` near the top of the promo
section; delete a name to stop hiding that surface.

| Group | Hides |
| --- | --- |
| `questPanel` | The Quest ad bar above the account panel (bottom-left) |
| `questsMisc` | Quest icons on member rows, quest badges on profiles, promoted quests in *Active Now*, quests in the gift inventory |
| `homeTabs` | **Nitro**, **Shop**, and **Quests** rows in the home sidebar |
| `gifts` | *Send a gift* in the chat box, *Gift Nitro* in profiles/DMs |
| `settingsTabs` | User Settings → Nitro, Server Boost, Subscriptions, Gift Inventory |
| `upsells` | Nitro nags in the emoji picker, soundboard, character counter, profile editor, "sneak peek" banners |

Notes:

- **Billing is deliberately still visible.** Hiding the page where you
  cancel a subscription is how you end up paying for one you forgot about.
  Add `billing_panel` to the `settingsTabs` group if you disagree.
- **Only upsell chrome is removed**, not the feature around it — the emoji
  picker, soundboard and profile editor all still work.
- **Why CSS, not a DOM sweep:** Discord re-mounts these subtrees on
  navigation, quest rotation and popout open/close. A stylesheet applies to
  whatever exists at paint time; a JS sweep would need a `MutationObserver`
  running forever (which v0.8 deliberately removed).
- **Selector durability**, most robust first: `data-*` hooks
  (`li[data-settings-sidebar-item="nitro_panel"]`), route hrefs
  (`a[href="/quest-home"]`), `aria-label` text, and finally class
  substrings — Discord ships hashed CSS-module names like
  `questRewardTile_a1b2c3`, so those match on the readable prefix and are
  the ones that rot.
- **If an ad comes back,** run `bnetswitchQuestProbe()` in the console. It
  reports per-group match counts plus any selector the browser refused to
  parse, so you can tell a renamed class from a broken rule. Selectors are
  cross-checked against [Disblock Origin](https://codeberg.org/AllPurposeMat/Disblock-Origin),
  which tracks Discord's markup churn closely — diff against it first.

## Why userscripts

Some integrations (Discord LFG) need to act inside an authenticated
browser session. Native tooling either can't (no bot access to that
server) or shouldn't (TOS-violating selfbot, plus selfbots can't share
voice with your real Discord client).

Userscripts let us drive DOM clicks the same way a human would, so:
- Auth stays in the browser, never copied to disk.
- Voice routing happens through your real Discord client's audio path.
- Detection signal looks identical to manual clicks.

One exception: **nickname sync** issues
`PATCH /api/v9/guilds/<id>/members/@me` directly, reusing the session
token the bridge already captures for history backfill. The DOM path for
this broke silently whenever Discord reshuffled the guild-header popout,
and it could only rename you in the guild the tab happened to be viewing.
The DOM walk is still there as a fallback if the request is rejected.

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
- Action delivery falls back through three tiers, in order:
  1. native `EventSource`,
  2. one long-lived streaming `GM_xmlhttpRequest` reading the same
     `/events` stream,
  3. long-polling `/actions/long` (one request per 25s).

  Firefox 153+ enforces Local Network Access permission, so tier 1 is
  normally refused for `http://127.0.0.1` from `https://discord.com` and
  tier 2 carries traffic. Tier 1 is re-probed every 10 minutes in case the
  permission is granted.

- A wall-clock-gap detector notices when timers were frozen (suspend) and
  rebuilds the connection plus re-backfills the LFG list on resume.
- `visibilitychange` (tab focus) and the `online` event also trigger a
  reconnect + session re-register.

No manual Discord-tab reload should be needed after a suspend or Wi-Fi blip.

## Why the transport avoids short polling

Tampermonkey keeps a record per `GM_xmlhttpRequest` in its background page
and does not reliably release completed ones, so memory cost scales with
the **number of requests**, not their size. All extensions share one
Firefox WebExtensions process, so this shows up as a single enormous
process rather than as "Tampermonkey using memory".

An earlier version short-polled `/actions` every 2s. That was ~43k
requests/day and grew the shared extension process to 8 GB in three days.
Anything added to this bridge should keep total request volume low — prefer
one long-lived request over many short ones, and never add a fast retry
loop for the "bnetswitch is down" case.

Run the SSE frame-parser tests with:

```sh
node userscripts/sse-parser.test.mjs
```

## Privacy

The script:
- Only POSTs message data from `LFG Tool` bot embeds (filters by author).
- Sends only what's visible in the LFG channel (no DM scraping, no
  private channel reads).
- Communicates exclusively with `127.0.0.1` — nothing leaves the box.
- Uses `GM_xmlhttpRequest` (Tampermonkey's CORS-bypassing fetch) since
  the localhost server has different origin than `discord.com`.
