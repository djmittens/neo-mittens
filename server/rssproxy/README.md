# rss-proxy

An on-demand full-text RSS proxy for [yarr](../rss/README.md). It solves two problems with
**stock, unpatched** yarr:

1. **Link-aggregator feeds** (Hacker News, Lobsters) carry only a title + link, no body.
2. **Hostile sites**: some block yarr's fetcher (e.g. Fabien Sanglard returns `406`) or
   hotlink-protect images (`403` unless the `Referer` is their own domain).

It fixes both **without modifying yarr**, and **only scrapes the articles you actually open**.

## How it works

```
yarr subscribes to:   https://<host>:7071/feed?url=<original feed>
  /feed   → fetch the original feed, rewrite each item <link> to
            …/article?url=<original item link>   (cheap; no article scraping)

You press "fetch content" on an item in yarr:
  yarr crawls item.link = …/article?url=<orig>
  /article → stealth-fetch the real page (TLS impersonation; browser fallback optional)
           → rewrite every <img> to …/img?url=…&ref=<origin>
           → return the full page (cached)        ← only happens for items you open
  yarr runs its own readability on that page and displays it
  browser loads images from /img (correct Referer) → hotlink protection defeated
```

Key design points:

- **Only-what-you-open**: `/feed` does no scraping; the expensive `/article` render is
  triggered solely by yarr's fetch-content button. Results are cached (bbolt) so re-opening
  is instant and never re-scrapes.
- **No double-extraction**: `/article` returns the *full* page (images proxied) and lets
  **yarr** do the article extraction. Pre-extracting here caused yarr's readability to
  mangle the result, so we don't.
- **Stock yarr**: we only change feed *data* (the item links). yarr's SSRF guard
  (`isInternalFromURL`) blocks `localhost`/private IPs but allows hostnames, so the proxy is
  addressed by its **Tailscale MagicDNS name** over HTTPS.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /feed?url=<feed>` | Original feed with item links rewritten to `/article`. |
| `GET /htmlfeed?url=<index>&match=<substr>&sel=<css>` | Synthesize a feed from an HTML index page for sites with **no RSS feed**. Scrapes links (default `a[href]`, optionally filtered to those containing `match`) into items. Used for Inigo Quilez (`iquilezles.org/articles/`). |
| `GET /article?url=<page>` | On-demand: stealth-fetch + image-rewrite the page. Cached. |
| `GET /img?url=<img>&ref=<origin>` | Fetch an image server-side with a same-origin `Referer`. |
| `GET /healthz` | Liveness. |

## Fetch tiers

1. **Fast (default)**: Chrome TLS+HTTP2 fingerprint impersonation (via `imroc/req`).
   Defeats most bot/hotlink blocks with no browser overhead. Handles server-rendered sites
   (Guardian, ProPublica, Fabien, IQ, ...).
2. **Browser tier**: real page rendering for JS-SPA sites. Triggered when the host is in
   `RSSPROXY_RENDER_HOSTS`, the fast tier is blocked (403/406/429/503/Cloudflare), or
   readability extracts almost nothing. Two backends:
   - **Camoufox** (preferred, handles all rendering incl. BBC) — anti-fingerprint Firefox in a
     rootless-podman container ([`camoufox/`](camoufox/)). The proxy calls it at
     `RSSPROXY_RENDER_URL`.
   - **chromedp** (headless Chromium via `RSSPROXY_CHROME`) — fallback if the Camoufox sidecar
     is down, plus a per-host escape hatch (`RSSPROXY_CHROMEDP_HOSTS`) for any site that ever
     renders better in Chromium (currently empty).

   > Note: Camoufox pins **Playwright 1.51** (see Containerfile) to match its bundled Firefox
   > 135. Without that pin, pip pulls a newer Playwright whose Node driver crashes on
   > `pageError` events, killing the browser — which looks like "Camoufox can't render this
   > site." Bump both together when upgrading.

   Cold render is ~3–6s; results are cached (one-time cost per article). To make another
   JS site render, add its domain to `RSSPROXY_RENDER_HOSTS`.

3. **Paywall tier**: for metered/paywalled news sites (`RSSPROXY_PAYWALL_HOSTS`), the proxy
   skips the HTTP fetch (usually edge-blocked from datacenter IPs) and renders the page in
   the browser **with JavaScript disabled**, then applies one of two strategies:

   - **Per-site extractor** (best): some sites embed the *complete* article as a JSON blob in
     the page. A registered extractor parses it and rebuilds clean article HTML. **NYT**
     (`nyt.go`, `window.__preloadedData`) uses it to defeat DOM truncation; **BBC** (`bbc.go`,
     `window.__INITIAL_DATA__`) uses it to drop the mountain of nav/consent chrome that
     otherwise swamps readability. Extractors run in both the paywall and normal render paths;
     see `paywallExtractors` to add more.
   - **Generic JS-off DOM**: for sites that server-render the body and only inject the
     meter/overlay with client JS, the JS-off DOM already contains the full text. A generic
     pass strips leftover "subscribe to keep reading" nodes and un-hides the body.

   - **Warm-up render** (last resort): if the above yield no real article (`articleThin`
     counts text inside `<p>`), the page is likely a client-rendered SPA behind a *bot wall*
     (DataDome/PerimeterX) that flags cold deep-links. The sidecar then visits the site
     **origin first in the same context** so the anti-bot JS challenge runs and sets a
     clearance cookie, then loads the article with the origin as referer — what a real
     reader's browser looks like. This gets past PerimeterX (Bloomberg) reliably; DataDome
     (WSJ) is stricter and often still blocks.

   Configure hosts with `RSSPROXY_PAYWALL_HOSTS`; optionally pose as a crawler with
   `RSSPROXY_PAYWALL_UA` (usually counter-productive — sites serve a stub to unverified
   crawler UAs).

   **Camoufox config matters.** The sidecar runs `CAMOUFOX_HEADLESS=virtual` (real headed
   Firefox on Xvfb — true headless leaks detection signals) + `CAMOUFOX_HUMANIZE=1`. This
   makes the *fingerprint* clean (verified: `navigator.webdriver=false`, coherent Windows
   Firefox, passes bot.sannysoft). It does **not** solve a CAPTCHA that a behavioural anti-bot
   chooses to present — camoufox is anti-*fingerprint*, not a CAPTCHA solver. `CAMOUFOX_GEOIP`
   is OFF (it broke NYT's JS-off path without helping the hard sites).

   **What actually works** (sites differ a lot):

   | Site | Anti-bot | Result |
   |---|---|---|
   | **NYT** | — | ✅ Full article via the `__preloadedData` extractor. |
   | **The Economist** | — | ⚠️ Partial — server-renders a teaser; readability keeps the free portion. |
   | **Bloomberg** | PerimeterX | ⚠️ Warm-up passes the bot wall; subscriber paywall still limits the body to the free lede. |
   | **WSJ** | DataDome | ❌ Strictest — often blocks even the homepage. Headline/summary only. |

   For the limited sites the RSS title + description still show in yarr. NYT is the reference
   setup: subscribe the NYT section feeds through `/feed` (see `../rss/feeds.opml`) and
   articles render in full on "fetch content".

### Cracking the hard sites (WSJ / Bloomberg)

Stealth alone can't beat DataDome (WSJ) / PerimeterX (Bloomberg). The sidecar supports three
add-ons (all optional, config in `~/.config/rss-camoufox/`, mounted into the container):

1. **Cookie injection** — `~/.config/rss-camoufox/cookies.json`, a Playwright cookie array
   exported from a logged-in browser (the *Cookie-Editor* extension → Export → JSON). Injected
   into every render context. Use your **subscriber** cookies for full articles, or a manually
   **solved DataDome clearance** cookie to pass the bot wall. Reloaded per request (edit
   without restart).

2. **CapSolver** — set `CAPSOLVER_KEY` in `~/.config/rss-camoufox/env`. When a render hits a
   DataDome challenge, the sidecar extracts the `captcha-delivery.com` challenge, submits a
   `DatadomeSliderTask` to CapSolver, and sets the returned `datadome` cookie before reloading.

3. **Upstream proxy** — `CAMOUFOX_PROXY=http://user:pass@host:port`. **Required for DataDome**:
   the `datadome` cookie is bound to the IP that solved it, so CapSolver must solve *through*
   this proxy and our page requests must egress the *same* proxy. Use a residential proxy.

```
# ~/.config/rss-camoufox/env   (NOT committed)
CAPSOLVER_KEY=CAP-XXXXXXXXXXXX
CAMOUFOX_PROXY=http://user:pass@residential-proxy.example:8000
```
Then `systemctl --user restart camoufox`. Note: even past the bot wall, WSJ/Bloomberg truncate
the body for non-subscribers — full text needs the subscriber cookies from (1). The most
robust setup is (1) subscriber cookies + (3) a stable residential-proxy IP.

## Install

```bash
./server/rssproxy/install.sh
```

Builds the Go binary to `~/.local/bin/rss-proxy`, installs a systemd **user** unit, sets
`RSSPROXY_PUBLIC_BASE` to this host's Tailscale name, and runs `tailscale serve` to expose
`https://<host>:7071` (tailnet-only). Requires `go`, `gcc`, `git`, `tailscale`.

## Subscribing a feed in yarr

Subscribe yarr to:
```
https://<host>.<tailnet>.ts.net:7071/feed?url=<URL-ENCODED original feed>
```
Keep the original GUIDs (the proxy preserves them), so yarr de-dupes correctly. Currently
routed: Hacker News, Hacker News (200+), Lobsters, Fabien Sanglard. Full-content blog feeds
are left subscribed directly (no proxy needed).

**Feedless sites** (no RSS at all) can be subscribed via `/htmlfeed`. Inigo Quilez is set up
this way:
```
https://<host>:7071/htmlfeed?url=https%3A%2F%2Fiquilezles.org%2Farticles%2F&match=iquilezles.org%2Farticles%2F
```
Dating: an HTML index has no per-article dates, so the proxy assigns a **stable per-URL
first-seen** timestamp (persisted in the `seen` bucket). The initial back-catalog is stamped
in index order (top of index = newest); any article that appears in the index *later* gets a
fresh, newer timestamp and surfaces as new. So "new article" detection works going forward;
only the one-time initial import lacks true chronology.

Media: article text + images load (images are proxied and resolved against the post-redirect
URL). Interactive embeds (e.g. Shadertoy `<iframe>`s) are stripped by yarr's sanitizer and
won't run in the reader pane — use "Read original" for the live shader.

## Configuration (env / unit)

| Var | Default | Meaning |
|---|---|---|
| `RSSPROXY_ADDR` | `127.0.0.1:7071` | Listen address (loopback; tailnet via `tailscale serve`). |
| `RSSPROXY_PUBLIC_BASE` | (set by install.sh) | Tailnet HTTPS base used in rewritten links. |
| `RSSPROXY_CACHE` | `~/.local/share/rssproxy/cache.db` | bbolt cache (article HTML). |
| `RSSPROXY_TTL_HOURS` | `720` | Article cache TTL (0 = forever). |
| `RSSPROXY_RENDER_URL` | `http://127.0.0.1:7072/render` | Camoufox sidecar endpoint (preferred browser backend). |
| `RSSPROXY_CHROME` | `/usr/bin/chromium` | Chromium binary for chromedp (fallback / chromedp-hosts). |
| `RSSPROXY_RENDER_HOSTS` | `bbc.co.uk,bbc.com` | Domains to always render in a browser. |
| `RSSPROXY_CHROMEDP_HOSTS` | `bbc.co.uk,bbc.com` | Domains to render via Chromium instead of Camoufox. |
| `RSSPROXY_PAYWALL_HOSTS` | NYT, WSJ, WaPo, Economist, FT, … (built-in) | Metered news domains rendered with JS disabled (paywall bypass). Empty = built-in list. |
| `RSSPROXY_PAYWALL_UA` | (empty) | Optional UA for paywall renders (e.g. a Googlebot string). Empty keeps the browser default. |
| `RSSPROXY_FLARESOLVERR` | (empty) | Optional alternative browser tier (FlareSolverr HTTP API). |

## Manage

```bash
systemctl --user status rss-proxy
journalctl --user -u rss-proxy -f
systemctl --user restart rss-proxy
curl -s https://<host>:7071/healthz
```

After editing source, rebuild: `cd server/rssproxy && go build -o ~/.local/bin/rss-proxy . && systemctl --user restart rss-proxy`.

## Data / backups

- Cache: `~/.local/share/rssproxy/cache.db` (regenerable; safe to delete to force re-render).
- On obelisk that path is on the 1.7TB `/data` partition via the `/home` bind mount.

## Uninstall

```bash
systemctl --user disable --now rss-proxy
tailscale serve --https=7071 off
rm ~/.config/systemd/user/rss-proxy.service ~/.local/bin/rss-proxy
rm -rf ~/.local/share/rssproxy
systemctl --user daemon-reload
# then re-point the affected feeds in yarr back to their original URLs
```
