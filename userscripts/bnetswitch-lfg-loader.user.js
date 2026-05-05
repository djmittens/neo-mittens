// ==UserScript==
// @name         bnetswitch LFG bridge
// @namespace    https://github.com/xyzyx/neo-mittens
// @version      1.0.0
// @description  [loader] Auto-fetches the live bnetswitch userscript from http://127.0.0.1:7172 and caches it via GM_setValue. Reloads only when not in voice. Install once via http://127.0.0.1:7172/bnetswitch-lfg-loader.user.js -- never touch again.
// @match        https://discord.com/*
// @match        https://canary.discord.com/*
// @match        https://ptb.discord.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_log
// @grant        GM_addElement
// @grant        unsafeWindow
// @run-at       document-start
// @connect      127.0.0.1
// @connect      localhost
// @require      https://cdn.jsdelivr.net/npm/pako@2.1.0/dist/pako.min.js
// @updateURL    http://127.0.0.1:7172/bnetswitch-lfg-loader.user.js
// @downloadURL  http://127.0.0.1:7172/bnetswitch-lfg-loader.user.js
// ==/UserScript==
//
// =============================================================================
// HOW THIS WORKS
// =============================================================================
//
// This loader is designed to be installed in Tampermonkey ONCE. It rarely
// changes. The actual bnetswitch userscript code is served by bnetswitch at
//   http://127.0.0.1:7172/bnetswitch-lfg.user.js
// and fetched + cached by this loader on every page load.
//
// Boot sequence:
//   1. (synchronous) GM_getValue('bnetswitch_lfg_code_v1') -> last cached code
//   2. (synchronous) eval(cached) at document-start, BEFORE Discord
//      caches its WebSocket reference. This is critical -- the gateway tap
//      relies on prototype-level WebSocket monkey-patching that has to be
//      installed before Discord's bundle constructs its WS.
//   3. (async) GM_xmlhttpRequest GET /bnetswitch-lfg.user.js to fetch latest;
//      compare against cached; if different, GM_setValue + queue a reload.
//   4. (poll) repeat the fetch every 60s.
//
// Reload-when-safe:
//   - The main userscript exposes window.__bnet_self_in_voice (boolean).
//   - On new version, if user is NOT in voice -> auto-reload after 3s grace.
//   - If user IS in voice -> show banner, set updatePending=true. The main
//     userscript calls window.__bnet_loader_notify_voice_left() when self
//     leaves voice, which triggers the deferred reload.
//
// Result: zero clicks, zero dropped voice calls. Updates apply within ~minute
// of you next leaving voice (or naturally reloading the tab).
//
// =============================================================================

(function () {
  "use strict";

  const REMOTE_URL = "http://127.0.0.1:7172/bnetswitch-lfg.user.js";
  const CACHE_KEY = "bnetswitch_lfg_code_v1";
  const HASH_KEY = "bnetswitch_lfg_code_hash_v1";
  const POLL_INTERVAL_MS = 60_000;
  const RELOAD_GRACE_MS = 3000;
  const VOICE_RECHECK_MS = 5000;

  // djb2 hash for change detection. Avoids storing two copies of the
  // code in GM storage just to compare.
  function hashCode(s) {
    let h = 5381;
    for (let i = 0; i < s.length; i++) {
      h = ((h << 5) + h) ^ s.charCodeAt(i);
    }
    return (h >>> 0).toString(16);
  }

  // -------------------------------------------------------------------------
  // 1) Synchronous boot from cache
  // -------------------------------------------------------------------------
  const cached = GM_getValue(CACHE_KEY, "");
  const cachedHash = cached ? hashCode(cached) : "";

  if (cached) {
    try {
      // Direct eval (not (0, eval)) so the eval'd code shares the
      // loader's lexical scope and can see the @require'd pako binding,
      // GM_* function references, and unsafeWindow. In strict mode
      // direct eval creates a nested scope, but parent-scope reads
      // still resolve, which is what we need.
      // eslint-disable-next-line no-eval
      eval(cached);
      console.log(
        "[bnetswitch-loader] booted from cache (" +
          cachedHash +
          ", " +
          cached.length +
          " bytes)"
      );
    } catch (e) {
      console.error("[bnetswitch-loader] cached eval failed, will fetch fresh:", e);
      // Cached code is broken -- clear it so next boot starts clean.
      try { GM_setValue(CACHE_KEY, ""); } catch (_) {}
    }
  } else {
    console.log(
      "[bnetswitch-loader] no cached code yet -- fetching from bnetswitch..."
    );
  }

  // -------------------------------------------------------------------------
  // 2) Async fetch + cache
  // -------------------------------------------------------------------------
  let updatePending = false;
  let voicePollHandle = null;
  let bannerEl = null;

  function fetchAndCache(isFirstFetch) {
    GM_xmlhttpRequest({
      method: "GET",
      url: REMOTE_URL,
      timeout: 5000,
      headers: { "Cache-Control": "no-cache" },
      onload: (resp) => {
        if (resp.status !== 200) {
          if (isFirstFetch) {
            console.warn(
              "[bnetswitch-loader] fetch returned " +
                resp.status +
                " -- is bnetswitch running on " +
                REMOTE_URL +
                "?"
            );
          }
          return;
        }
        const code = resp.responseText || "";
        // Sanity check: real userscript is ~50KB+; anything tiny is
        // likely a stub or error page we don't want to cache.
        if (code.length < 5000) {
          console.warn(
            "[bnetswitch-loader] fetched code suspiciously short (" +
              code.length +
              " bytes), skipping cache"
          );
          return;
        }
        const newHash = hashCode(code);
        if (newHash === cachedHash) {
          // No change.
          return;
        }
        try {
          GM_setValue(CACHE_KEY, code);
          GM_setValue(HASH_KEY, newHash);
        } catch (e) {
          console.error("[bnetswitch-loader] GM_setValue failed:", e);
          return;
        }
        if (!cached) {
          // First-ever load with no prior cache. Old code never ran, so
          // we can apply immediately.
          console.log(
            "[bnetswitch-loader] first-time install cached (" +
              newHash +
              "), reloading in " +
              (RELOAD_GRACE_MS / 1000) +
              "s..."
          );
          scheduleReload();
        } else {
          console.log(
            "[bnetswitch-loader] new version cached: " +
              cachedHash +
              " -> " +
              newHash +
              " (" +
              code.length +
              " bytes)"
          );
          updatePending = true;
          tryApplyUpdate();
        }
      },
      onerror: () => {
        if (isFirstFetch) {
          console.warn(
            "[bnetswitch-loader] fetch failed -- bnetswitch not running?"
          );
        }
      },
      ontimeout: () => {
        if (isFirstFetch) {
          console.warn("[bnetswitch-loader] fetch timed out");
        }
      },
    });
  }

  // -------------------------------------------------------------------------
  // 3) Reload-when-safe
  // -------------------------------------------------------------------------
  function isInVoice() {
    // Main userscript sets __bnet_self_in_voice on every VOICE_STATE_UPDATE
    // for self, and explicitly sets it to false at end of READY processing
    // if no voice state was found. Default to TRUE (safest) if undefined.
    try {
      const v = unsafeWindow.__bnet_self_in_voice;
      if (v === false) return false;
      if (v === true) return true;
    } catch (_) {}
    return true;
  }

  function scheduleReload() {
    if (voicePollHandle) {
      clearTimeout(voicePollHandle);
      voicePollHandle = null;
    }
    setTimeout(() => {
      console.log("[bnetswitch-loader] reloading now");
      try { unsafeWindow.location.reload(); }
      catch (_) { window.location.reload(); }
    }, RELOAD_GRACE_MS);
  }

  function tryApplyUpdate() {
    if (!updatePending) return;
    if (isInVoice()) {
      showBanner();
      // Re-check periodically as a fallback in case the main code
      // doesn't call us via __bnet_loader_notify_voice_left.
      if (voicePollHandle) clearTimeout(voicePollHandle);
      voicePollHandle = setTimeout(tryApplyUpdate, VOICE_RECHECK_MS);
      return;
    }
    hideBanner();
    updatePending = false;
    scheduleReload();
  }

  // Allow main userscript to notify us synchronously when self leaves voice.
  // Wrap in try/catch since we install before main code runs.
  try {
    unsafeWindow.__bnet_loader_notify_voice_left = function () {
      if (updatePending) {
        console.log(
          "[bnetswitch-loader] notified of voice-left, applying update"
        );
        tryApplyUpdate();
      }
    };
  } catch (e) {
    console.error("[bnetswitch-loader] failed to expose voice-left hook:", e);
  }

  // -------------------------------------------------------------------------
  // 4) Banner
  // -------------------------------------------------------------------------
  function showBanner() {
    if (bannerEl && document.body && document.body.contains(bannerEl)) return;
    if (!document.body) {
      // body not ready yet; try again shortly
      setTimeout(showBanner, 500);
      return;
    }
    bannerEl = document.createElement("div");
    bannerEl.id = "__bnet_loader_banner";
    bannerEl.style.cssText = [
      "position:fixed",
      "bottom:12px",
      "right:12px",
      "z-index:99999",
      "background:#1e2030",
      "color:#cad3f5",
      "padding:8px 14px",
      "border-radius:6px",
      "font:12px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif",
      "border:1px solid #494d64",
      "box-shadow:0 2px 12px rgba(0,0,0,0.4)",
      "cursor:default",
      "user-select:none",
    ].join(";");
    bannerEl.textContent =
      "bnetswitch userscript update queued — applies when you leave voice";
    document.body.appendChild(bannerEl);
  }

  function hideBanner() {
    if (bannerEl) {
      try { bannerEl.remove(); } catch (_) {}
      bannerEl = null;
    }
  }

  // -------------------------------------------------------------------------
  // 5) Boot polling
  // -------------------------------------------------------------------------
  // Initial fetch deferred slightly so the cached code (if any) has a moment
  // to install its WebSocket hooks before we kick off network activity.
  setTimeout(() => fetchAndCache(true), 500);
  setInterval(() => fetchAndCache(false), POLL_INTERVAL_MS);

  // Diagnostic hook: GM-injected globals are visible to userscript world only.
  // Mirror onto unsafeWindow so dev tools console can see "loader status".
  try {
    unsafeWindow.__bnet_loader_status = function () {
      return {
        cached_hash: cachedHash,
        cached_bytes: cached.length,
        update_pending: updatePending,
        in_voice: isInVoice(),
        remote_url: REMOTE_URL,
      };
    };
  } catch (_) {}

  console.log(
    "[bnetswitch-loader] v1.0.0 active, will fetch from " + REMOTE_URL
  );
})();
