// ==UserScript==
// @name         yarr Apple News theme
// @namespace    https://github.com/xyzyx/neo-mittens
// @version      1.0.0
// @description  Restyles the stock yarr RSS reader to look like Apple News (San Francisco typography, near-black iOS surfaces, big bold headlines, rounded cards, nicer code blocks) while keeping yarr's dark "night" theme. Pure CSS overlay — yarr stays the stock binary; nothing is patched or rebuilt.
// @author       neo-mittens
// @match        http://localhost:7070/*
// @match        http://127.0.0.1:7070/*
// @match        https://*.ts.net/*
// @match        https://*.ts.net:7070/*
// @run-at       document-start
// @grant        none
// @noframes
// ==/UserScript==

(function () {
  'use strict';

  // -------------------------------------------------------------------------
  // GUARD
  //
  // The ts.net @match is broad (your tailnet may host other services), so only
  // inject on the yarr port. yarr binds 127.0.0.1:7070 and is exposed via
  // `tailscale serve --https=7070`, so port 7070 uniquely identifies it in this
  // deployment. If you ever change yarr's port, update YARR_PORT to match.
  // The app.css link check is a secondary signal (yarr-specific asset path).
  // -------------------------------------------------------------------------
  const YARR_PORT = '7070';

  function looksLikeYarr() {
    if (location.port === YARR_PORT) return true;
    // Fallback: yarr always loads this stylesheet path.
    return !!document.querySelector('link[href*="static/stylesheets/app.css"]');
  }

  if (!looksLikeYarr()) return;

  // -------------------------------------------------------------------------
  // PALETTE (iOS / Apple News dark)
  //   --an-bg        true black app background
  //   --an-surface   elevated surface (sidebars / cards)
  //   --an-surface-2 hover / selected
  //   --an-text      primary near-white
  //   --an-text-2    secondary gray (bylines, counts)
  //   --an-sep       hairline separators
  //   --an-accent    iOS system blue
  // -------------------------------------------------------------------------
  const CSS = `
:root {
  --an-bg: #000000;
  --an-panel: #0a0a0b;
  --an-surface: #1c1c1e;
  --an-surface-2: #2c2c2e;
  --an-text: #f5f5f7;
  --an-text-2: #8e8e93;
  --an-sep: rgba(255,255,255,0.08);
  --an-accent: #0a84ff;
  --an-sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display",
             "Segoe UI", Roboto, Helvetica, Arial, system-ui, sans-serif;
  --an-mono: "SF Mono", SFMono-Regular, ui-monospace, Menlo, Consolas,
             "Liberation Mono", monospace;
}

/* ---- typography: San Francisco everywhere ---- */
html { font-size: 15px !important; }
body,
.toolbar-item, .dropdown-item, .dropdown-header, .selectgroup-label,
.form-control, input, button, textarea, select, .counter, kbd {
  font-family: var(--an-sans) !important;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* ---- base dark surfaces (only when night theme is active) ---- */
body.theme-night {
  background-color: var(--an-bg) !important;
  color: var(--an-text) !important;
}
.theme-night #col-feed-list,
.theme-night #col-item-list {
  background-color: var(--an-panel) !important;
}
.theme-night #col-item {
  background-color: var(--an-bg) !important;
}

/* hairline separators instead of the chunky default borders */
.theme-night .border-right,
.theme-night .border-left,
.theme-night .border-top,
.theme-night .border-bottom,
.theme-night .dropdown-divider,
.theme-night .content hr {
  border-color: var(--an-sep) !important;
}

/* ---- toolbars ---- */
.toolbar-item { border-radius: 8px !important; }
.theme-night .toolbar-item:hover,
.theme-night .toolbar-search:hover,
.theme-night .toolbar-search:focus {
  background-color: var(--an-surface) !important;
}
.theme-night .toolbar-search {
  background-color: var(--an-surface) !important;
  border-radius: 8px !important;
  color: var(--an-text) !important;
}
/* active filter chips -> iOS blue */
.theme-night .toolbar-item.active {
  background-color: var(--an-accent) !important;
  color: #fff !important;
}

/* ---- accent / links ---- */
a, .btn-link:hover { color: var(--an-accent) !important; }
.theme-night .btn-default:focus,
.theme-night .form-control:focus { border-color: var(--an-accent) !important; }

/* ---- sidebar feed list ---- */
.theme-night #feed-list-scroll .selectgroup-label { border-radius: 8px !important; }
.theme-night #feed-list-scroll .selectgroup-label:hover {
  background-color: var(--an-surface) !important;
}
.theme-night #feed-list-scroll .selectgroup input:checked + .selectgroup-label {
  background-color: var(--an-surface) !important;
  color: var(--an-text) !important;
}
.counter { color: var(--an-text-2) !important; opacity: 1 !important; }

/* ---- item list: Apple-News style cards ---- */
.theme-night #item-list-scroll .selectgroup-label {
  border-radius: 10px !important;
  padding: .6rem .7rem !important;
  margin-bottom: .15rem;
}
.theme-night #item-list-scroll .selectgroup-label:hover {
  background-color: var(--an-surface) !important;
}
.theme-night #item-list-scroll .selectgroup input:checked + .selectgroup-label {
  background-color: var(--an-surface-2) !important;
  color: var(--an-text) !important;
}
/* meta row (publication + time) */
.theme-night #item-list-scroll .selectgroup-label small {
  color: var(--an-text-2) !important;
}
/* unread / starred dot in the accent color */
.theme-night #item-list-scroll .selectgroup-label .icon-small { color: var(--an-accent) !important; }
/* headline line */
.theme-night #item-list-scroll .selectgroup-label > div:last-child {
  font-weight: 600 !important;
  font-size: 1.02rem !important;
  line-height: 1.32 !important;
  letter-spacing: -0.01em;
  color: var(--an-text) !important;
  margin-top: .15rem;
}

/* ---- article view ---- */
.content-wrapper { max-width: 44rem !important; }

.content { color: #dcdce1 !important; line-height: 1.7 !important; }
.content h1 {
  font-size: 2.4rem !important;
  font-weight: 800 !important;
  line-height: 1.08 !important;
  letter-spacing: -0.022em !important;
  margin-bottom: .4rem;
}
.content h2 { font-weight: 700 !important; letter-spacing: -0.015em; }
.content h3, .content h4, .content h5, .content h6 { font-weight: 700 !important; }
.content p { margin: 1.1rem 0 !important; }
.theme-night .content .text-muted { color: var(--an-text-2) !important; }
.content time { color: var(--an-text-2) !important; }

.content a { color: var(--an-accent) !important; text-decoration: none !important; }
.content a:hover { text-decoration: underline !important; }

.theme-night .content blockquote {
  border-left: 3px solid var(--an-accent) !important;
  padding-left: 1rem !important;
  color: #b6b6bb !important;
}

/* rounded media like Apple News cards */
.content img, .content video, .content iframe,
.content figure img { border-radius: 12px !important; }
.content figcaption {
  color: var(--an-text-2) !important;
  font-size: .85rem !important;
  margin-top: .4rem;
}

/* ---- code blocks ---- */
.content pre {
  background: var(--an-surface) !important;
  border: 1px solid var(--an-sep) !important;
  border-radius: 10px !important;
  padding: .9rem 1rem !important;
  margin-left: 0 !important;
  margin-right: 0 !important;
  font-family: var(--an-mono) !important;
  font-size: .88rem !important;
  line-height: 1.5 !important;
  color: #e6e6ea !important;
}
.content code {
  font-family: var(--an-mono) !important;
  font-size: .88em !important;
}
/* inline code -> subtle chip */
.theme-night .content :not(pre) > code {
  background: var(--an-surface) !important;
  border-radius: 5px !important;
  padding: .12em .35em !important;
  color: var(--an-text) !important;
}

/* ---- dropdowns / modals ---- */
.theme-night .dropdown-menu,
.theme-night .modal-content {
  background-color: var(--an-surface) !important;
  border: 1px solid var(--an-sep) !important;
  border-radius: 12px !important;
  box-shadow: 0 8px 30px rgba(0,0,0,0.5) !important;
}
.theme-night .dropdown-item:hover,
.theme-night .selectgroup-label:hover {
  background-color: var(--an-surface-2) !important;
}
.theme-night .form-control {
  background-color: var(--an-surface) !important;
  border-color: rgba(255,255,255,0.12) !important;
  color: var(--an-text) !important;
  border-radius: 8px !important;
}

/* ---- scrollbars ---- */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb {
  background: rgba(255,255,255,0.16);
  border-radius: 8px;
  border: 2px solid transparent;
  background-clip: content-box;
}
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.28); background-clip: content-box; }
::-webkit-scrollbar-track { background: transparent; }
`;

  function inject() {
    if (document.getElementById('yarr-apple-news-style')) return;
    const style = document.createElement('style');
    style.id = 'yarr-apple-news-style';
    style.textContent = CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  // Inject ASAP (document-start) to avoid a flash of the default theme.
  inject();
  // Re-assert once the head exists, in case we ran before it was parsed.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject, { once: true });
  }
})();
