package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/chromedp/chromedp"
	readability "github.com/go-shiori/go-readability"
)

// chromePath is a chromium/chrome binary for the chromedp render path.
// renderURL is a Camoufox sidecar endpoint (preferred for most sites).
// Empty (both) disables the browser tier.
var (
	chromePath string
	renderURL  string
)

// renderHosts: domains that must ALWAYS be rendered in a browser (JS-SPA sites whose
// static HTML has no article body). chromedpHosts: domains that render correctly only in
// Chromium (e.g. BBC, which comes back thin in Camoufox/Firefox) - sent straight to chromedp.
// paywallHosts: metered/paywalled news sites - rendered with JavaScript DISABLED so the
// server-rendered article body is returned without the JS-injected meter/overlay (the
// removepaywalls.com approach, generalised). paywallUA optionally overrides the UA for those
// renders (e.g. a Googlebot string); empty keeps Camoufox's default identity.
var (
	renderHosts   []string
	chromedpHosts []string
	paywallHosts  []string
	paywallUA     string
)

func hostIsPaywalled(u *url.URL) bool { return hostInList(u, paywallHosts) }

// renderOpts tunes a single browser render. The zero value is a normal JS-on render.
type renderOpts struct {
	JavaScript *bool  // nil/true = run JS; false = JS disabled (paywall-bypass)
	UserAgent  string // override UA (empty = backend default)
	Referer    string // Referer header for the navigation (empty = none)
	WaitMs     int    // post-load settle; -1 = use the backend default
	Warmup     bool   // visit the site origin first (acquire anti-bot clearance cookie)
}

// paywallRenderOpts is the bypass profile for paywalled news hosts.
func paywallRenderOpts() renderOpts {
	no := false
	return renderOpts{JavaScript: &no, UserAgent: paywallUA, Referer: "https://www.google.com/", WaitMs: 0}
}

func browserEnabled() bool { return renderURL != "" || chromePath != "" }

func hostInList(u *url.URL, list []string) bool {
	if u == nil {
		return false
	}
	h := strings.ToLower(u.Hostname())
	for _, d := range list {
		d = strings.TrimSpace(strings.ToLower(d))
		if d != "" && (h == d || strings.HasSuffix(h, "."+d)) {
			return true
		}
	}
	return false
}

func hostNeedsBrowser(u *url.URL) bool { return hostInList(u, renderHosts) }

// browserRender renders a page with the default (JS-on) profile.
func browserRender(rawurl string) (string, error) {
	return browserRenderOpts(rawurl, renderOpts{})
}

// browserRenderOpts renders a page with the given profile. Camoufox (anti-fingerprint) is
// preferred, except for hosts in chromedpHosts which only render properly in Chromium and go
// straight there.
func browserRenderOpts(rawurl string, opts renderOpts) (string, error) {
	u, _ := url.Parse(rawurl)

	if chromePath != "" && hostInList(u, chromedpHosts) {
		log.Printf("rendered via chromedp (host override): %s", rawurl)
		return renderViaChromedp(rawurl, opts)
	}
	if renderURL != "" {
		h, err := renderViaSidecar(rawurl, opts)
		if err == nil && strings.TrimSpace(h) != "" {
			log.Printf("rendered via camoufox sidecar: %s (%d bytes)", rawurl, len(h))
			return h, nil
		}
		log.Printf("camoufox sidecar failed for %s: %v", rawurl, err)
		if chromePath == "" {
			return "", err
		}
		// fall through to chromedp on sidecar error
	}
	if chromePath != "" {
		log.Printf("rendered via chromedp: %s", rawurl)
		return renderViaChromedp(rawurl, opts)
	}
	return "", fmt.Errorf("no browser tier configured")
}

// renderViaSidecar calls the Camoufox HTTP sidecar.
func renderViaSidecar(rawurl string, opts renderOpts) (string, error) {
	body := map[string]any{"url": rawurl}
	if opts.JavaScript != nil {
		body["javascript"] = *opts.JavaScript
	}
	if opts.UserAgent != "" {
		body["user_agent"] = opts.UserAgent
	}
	if opts.Referer != "" {
		body["referer"] = opts.Referer
	}
	if opts.WaitMs >= 0 {
		body["wait_ms"] = opts.WaitMs
	}
	if opts.Warmup {
		body["warmup"] = true
	}
	payload, _ := json.Marshal(body)
	client := &http.Client{Timeout: 70 * time.Second}
	resp, err := client.Post(renderURL, "application/json", bytes.NewReader(payload))
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	respBody, _ := io.ReadAll(resp.Body)
	var out struct {
		HTML  string `json:"html"`
		URL   string `json:"url"`
		Error string `json:"error"`
	}
	if err := json.Unmarshal(respBody, &out); err != nil {
		return "", fmt.Errorf("sidecar bad response: %v", err)
	}
	if out.Error != "" {
		return "", fmt.Errorf("sidecar: %s", out.Error)
	}
	return out.HTML, nil
}

// renderViaChromedp loads a URL in headless Chromium and returns the rendered DOM. With
// opts.JavaScript=false it disables scripting (the paywall-bypass path); opts.UserAgent
// overrides the UA when set.
func renderViaChromedp(rawurl string, opts renderOpts) (string, error) {
	ua := "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
	if opts.UserAgent != "" {
		ua = opts.UserAgent
	}
	jsOff := opts.JavaScript != nil && !*opts.JavaScript
	allocOpts := append(chromedp.DefaultExecAllocatorOptions[:],
		chromedp.ExecPath(chromePath),
		chromedp.Flag("headless", true),
		chromedp.Flag("disable-gpu", true),
		chromedp.Flag("no-sandbox", true),
		chromedp.Flag("disable-dev-shm-usage", true),
		chromedp.WindowSize(1280, 2400),
		chromedp.UserAgent(ua),
	)
	if jsOff {
		allocOpts = append(allocOpts, chromedp.Flag("blink-settings", "scriptEnabled=false"))
	}
	actx, acancel := chromedp.NewExecAllocator(context.Background(), allocOpts...)
	defer acancel()
	ctx, cancel := chromedp.NewContext(actx)
	defer cancel()
	ctx, tcancel := context.WithTimeout(ctx, 45*time.Second)
	defer tcancel()

	// No JS to run when disabled - grab the DOM immediately instead of waiting to settle.
	settle := 2500 * time.Millisecond
	if jsOff {
		settle = 0
	}
	var html string
	err := chromedp.Run(ctx,
		chromedp.Navigate(rawurl),
		chromedp.Sleep(settle),
		chromedp.OuterHTML("html", &html, chromedp.ByQuery),
	)
	return html, err
}

// needsRender probes static HTML with a readability extractor: if it can't pull a
// reasonable amount of article text, the page is likely JS-rendered and needs a browser.
func needsRender(body []byte, u *url.URL) bool {
	art, err := readability.FromReader(bytes.NewReader(body), u)
	if err != nil {
		return true
	}
	return len(strings.TrimSpace(art.TextContent)) < 800
}
