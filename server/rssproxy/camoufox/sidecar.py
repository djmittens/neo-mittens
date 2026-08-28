#!/usr/bin/env python3
"""
Camoufox render sidecar for rss-proxy.

A tiny HTTP service that renders a URL in headless Camoufox (anti-fingerprint Firefox)
and returns the fully rendered HTML. The Go proxy calls it as its top "browser" tier
for JS-rendered / bot-hostile sites.

API:
  POST /render   body: {"url": "...", "wait_ms": 2500,
                        "javascript": true, "user_agent": "...", "referer": "..."}
                 -> {"html": "...", "url": "<final>"}
  GET  /healthz  -> "ok"

  javascript=false disables JS for the render. This is the paywall-bypass path: news
  sites server-render the full article (for SEO/Googlebot) and inject the meter/wall with
  client-side JS, so loading with JS off returns the full text and no overlay. user_agent
  and referer let the caller pose as a search crawler / inbound-from-Google visitor.

Hard sites (WSJ=DataDome, Bloomberg=PerimeterX) additionally support:
  - Cookie injection (COOKIES_FILE): a Playwright cookie jar exported from a logged-in
    browser, injected into every context (subscriber session / manual clearance cookie).
  - CapSolver (CAPSOLVER_KEY): auto-solve a DataDome challenge and set the returned cookie.
  - Upstream proxy (CAMOUFOX_PROXY): REQUIRED for DataDome, whose cookie is IP-bound - both
    the CapSolver solve and our page requests must egress the SAME proxy IP.

A single browser is kept alive and a fresh page (fresh context isolation via Camoufox)
is used per request. Requests are served serially (sync Playwright is single-threaded).
"""
import json
import os
import re
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

from camoufox.sync_api import Camoufox

PORT = int(os.environ.get("PORT", "7072"))
NAV_TIMEOUT = int(os.environ.get("NAV_TIMEOUT_MS", "45000"))
DEFAULT_WAIT = int(os.environ.get("RENDER_WAIT_MS", "2500"))

# --- Anti-bot solving / auth ---
# CapSolver API key: when set, DataDome (and similar) challenges are solved automatically.
CAPSOLVER_KEY = os.environ.get("CAPSOLVER_KEY", "").strip()
CAPSOLVER_URL = os.environ.get("CAPSOLVER_URL", "https://api.capsolver.com").rstrip("/")
# Upstream proxy. REQUIRED for DataDome: the solved `datadome` cookie is bound to the IP that
# solved it, so CapSolver must solve THROUGH this proxy and our page requests must EGRESS
# through the same proxy. Format: http://user:pass@host:port  (or socks5://...).
PROXY_URL = os.environ.get("CAMOUFOX_PROXY", "").strip()
# Cookie jar: a Playwright-format JSON array of cookies (export from a logged-in browser via
# the Cookie-Editor extension). Injected into every context so subscriber/clearance cookies
# apply. Reloaded per request so you can update it without restarting. Mounted read-only.
COOKIES_FILE = os.environ.get("COOKIES_FILE", "/cookies/cookies.json")

# Headless mode. Camoufox's anti-detection is weakened by true headless; the recommended
# mode is "virtual" - a real headed Firefox on an internal Xvfb display (xvfb is in the
# image). humanize adds human-like cursor motion. Both default on; override via env.
# (These reduce *fingerprint* detection so a CAPTCHA is less likely to fire - they do NOT
# solve a CAPTCHA that a behavioural anti-bot like DataDome/PerimeterX decides to present.)
_HEADLESS = os.environ.get("CAMOUFOX_HEADLESS", "virtual")
if _HEADLESS in ("1", "true", "True"):
    _HEADLESS = True
elif _HEADLESS in ("0", "false", "False"):
    _HEADLESS = False
_HUMANIZE = os.environ.get("CAMOUFOX_HUMANIZE", "1") not in ("0", "false", "False", "")
# geoip aligns the spoofed timezone/locale/WebRTC with the exit IP. In theory a coherence
# win, but in practice it made NYT's edge serve a JS-required bot stub to the JS-off path
# (breaking the NYT extractor) without unlocking the harder DataDome/PerimeterX sites - the
# warm-up flow is what helps those. So it defaults OFF. Enable per experiment via the env.
_GEOIP = os.environ.get("CAMOUFOX_GEOIP", "0") not in ("0", "false", "False", "")

# Persistent browser (entered once; reused across requests).
try:
    _cm = Camoufox(headless=_HEADLESS, humanize=_HUMANIZE, geoip=_GEOIP)
    browser = _cm.__enter__()
except Exception as _e:  # noqa: BLE001 - geoip extra/db missing, etc.
    print(f"camoufox launch with geoip failed ({_e}); retrying without geoip", flush=True)
    _cm = Camoufox(headless=_HEADLESS, humanize=_HUMANIZE)
    browser = _cm.__enter__()


def proxy_dict():
    """Parse CAMOUFOX_PROXY into a Playwright proxy dict, or None."""
    if not PROXY_URL:
        return None
    p = urlsplit(PROXY_URL)
    d = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
    if p.username:
        d["username"] = p.username
    if p.password:
        d["password"] = p.password
    return d


def capsolver_proxy():
    """CapSolver wants proxy as scheme:host:port:user:pass (or without creds)."""
    if not PROXY_URL:
        return None
    p = urlsplit(PROXY_URL)
    parts = [p.scheme, p.hostname, str(p.port)]
    if p.username:
        parts += [p.username, p.password or ""]
    return ":".join(parts)


def load_cookies():
    """Load + sanitise the Playwright cookie array from COOKIES_FILE (best-effort)."""
    try:
        with open(COOKIES_FILE) as f:
            raw = json.load(f)
    except Exception:  # noqa: BLE001 - missing/invalid file is fine
        return []
    if isinstance(raw, dict):  # storage_state shape
        raw = raw.get("cookies", [])
    out = []
    for c in raw or []:
        if not c.get("name") or "value" not in c:
            continue
        ck = {k: c[k] for k in ("name", "value", "domain", "path", "expires", "httpOnly", "secure") if k in c}
        ss = c.get("sameSite")
        if ss in ("Strict", "Lax", "None"):
            ck["sameSite"] = ss
        if "domain" not in ck and c.get("url"):
            ck["url"] = c["url"]
        out.append(ck)
    return out


def capsolver(task):
    """Create a CapSolver task and poll for the result. Returns the solution dict or None."""
    if not CAPSOLVER_KEY:
        return None

    def post(path, payload):
        req = urllib.request.Request(
            CAPSOLVER_URL + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        return json.loads(urllib.request.urlopen(req, timeout=30).read())

    try:
        created = post("/createTask", {"clientKey": CAPSOLVER_KEY, "task": task})
        if created.get("errorId"):
            print(f"capsolver createTask error: {created.get('errorDescription')}", flush=True)
            return None
        tid = created.get("taskId")
        for _ in range(60):  # up to ~120s
            time.sleep(2)
            res = post("/getTaskResult", {"clientKey": CAPSOLVER_KEY, "taskId": tid})
            if res.get("errorId"):
                print(f"capsolver task error: {res.get('errorDescription')}", flush=True)
                return None
            if res.get("status") == "ready":
                return res.get("solution")
    except Exception as e:  # noqa: BLE001
        print(f"capsolver exception: {e}", flush=True)
    return None


def datadome_challenge_url(html):
    """Extract the geo.captcha-delivery.com captcha URL from a DataDome block page."""
    m = re.search(r'src="(https://geo\.captcha-delivery\.com/captcha/[^"]+)"', html)
    if m:
        return m.group(1).replace("&amp;", "&")
    # Fallback: build from the `dd` config object DataDome injects.
    dd = re.search(r"var dd=\{([^}]+)\}", html)
    if dd:
        kv = dict(re.findall(r"'(\w+)':'([^']*)'", "{" + dd.group(1) + "}"))
        if kv.get("cid") and kv.get("hsh"):
            t = kv.get("t", "fe")
            return (f"https://geo.captcha-delivery.com/captcha/?initialCid={kv.get('cid')}"
                    f"&hash={kv['hsh']}&cid={kv.get('cid')}&t={t}")
    return None


def solve_datadome(page, ctx, page_url, user_agent):
    """If the page is a DataDome block, solve it via CapSolver, set the cookie, reload.
    Returns True if a solve was applied."""
    if not CAPSOLVER_KEY:
        return False
    html = page.content()
    if "captcha-delivery.com" not in html and "geo.captcha-delivery" not in html:
        return False
    cap_url = datadome_challenge_url(html)
    if not cap_url:
        return False
    print(f"datadome challenge detected, solving via capsolver: {page_url}", flush=True)
    sol = capsolver({
        "type": "DatadomeSliderTask",
        "websiteURL": page_url,
        "captchaUrl": cap_url,
        "userAgent": user_agent or "",
        "proxy": capsolver_proxy() or "",
    })
    if not sol or not sol.get("cookie"):
        print("datadome solve failed", flush=True)
        return False
    # solution cookie looks like "datadome=XXXX; Path=/; ... Domain=.wsj.com"
    raw = sol["cookie"]
    val = raw.split(";", 1)[0].split("=", 1)
    if len(val) != 2:
        return False
    host = urlsplit(page_url).hostname or ""
    domain = "." + ".".join(host.split(".")[-2:]) if host else ""
    ctx.add_cookies([{"name": val[0], "value": val[1], "domain": domain, "path": "/"}])
    return True


def render(url, wait_ms, javascript=True, user_agent=None, referer=None, warmup=False):
    # Fresh context per request: clean cookies so we don't get stuck on a consent/state
    # flow from a previous page. no_viewport avoids a Playwright/Camoufox protocol mismatch.
    # java_script_enabled=False is the paywall-bypass path (see module docstring).
    ctx_kwargs: dict = {"no_viewport": True}
    if not javascript:
        ctx_kwargs["java_script_enabled"] = False
    if user_agent:
        ctx_kwargs["user_agent"] = user_agent
    prox = proxy_dict()
    if prox:
        ctx_kwargs["proxy"] = prox
    ctx = browser.new_context(**ctx_kwargs)
    cookies = load_cookies()
    if cookies:
        try:
            ctx.add_cookies(cookies)
        except Exception as e:  # noqa: BLE001
            print(f"cookie injection failed: {e}", flush=True)
    page = ctx.new_page()
    try:
        if referer:
            try:
                page.set_extra_http_headers({"Referer": referer})
            except Exception:  # noqa: BLE001
                pass
        if warmup:
            # Anti-bots (DataDome/PerimeterX) flag a cold deep-link to an article with no
            # clearance cookie. Visit the site origin first IN THE SAME CONTEXT so the JS
            # challenge runs and sets the clearance cookie, then load the article with the
            # origin as referer - exactly what a real reader's browser looks like.
            try:
                parts = urlsplit(url)
                origin = f"{parts.scheme}://{parts.netloc}/"
                page.goto(origin, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
                page.wait_for_timeout(4000)
                solve_datadome(page, ctx, origin, user_agent)
                referer = origin
            except Exception:  # noqa: BLE001
                pass
        # domcontentloaded fires early and reliably; chatty sites (ads/telemetry) never
        # reach "load"/networkidle, so waiting for those can hang. Grab the DOM after a
        # bounded settle instead (same approach as the chromedp path). With JS off there's
        # nothing to settle, so callers pass wait_ms=0.
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT, referer=referer or None)
        except Exception:  # noqa: BLE001
            pass
        if wait_ms:
            page.wait_for_timeout(wait_ms)
        # If DataDome challenged the article itself, solve it and reload once.
        if solve_datadome(page, ctx, url, user_agent):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT, referer=referer or None)
                page.wait_for_timeout(wait_ms or DEFAULT_WAIT)
            except Exception:  # noqa: BLE001
                pass
        return page.content(), page.url
    finally:
        ctx.close()


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            url = body.get("url")
            if not url:
                return self._json(400, {"error": "missing url"})
            javascript = bool(body.get("javascript", True))
            # JS-off renders are static, so default their settle wait to 0.
            default_wait = DEFAULT_WAIT if javascript else 0
            wait_ms = int(body.get("wait_ms", default_wait))
            user_agent = body.get("user_agent") or None
            referer = body.get("referer") or None
            warmup = bool(body.get("warmup", False))
            html, final = render(url, wait_ms, javascript, user_agent, referer, warmup)
            self._json(200, {"html": html, "url": final})
        except Exception as e:  # noqa: BLE001
            self._json(502, {"error": str(e)})

    def log_message(self, *a):  # quiet
        pass


if __name__ == "__main__":
    print(f"camoufox sidecar listening on :{PORT}", flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
