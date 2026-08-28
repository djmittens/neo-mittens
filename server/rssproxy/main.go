// rssproxy: an on-demand full-text RSS proxy for yarr.
//
//	/feed?url=<original feed>   -> same feed, but each item <link> rewritten to
//	                               /article?url=<original item link>. Cheap, no scraping.
//	/article?url=<page>         -> on demand: stealth-fetch the page, extract the main
//	                               content, rewrite <img> to /img, return clean HTML.
//	                               yarr's "fetch content" button crawls this, so only the
//	                               articles you actually open are ever scraped.
//	/img?url=<img>&ref=<origin> -> fetch an image server-side with the right Referer to
//	                               defeat hotlink protection, stream it back.
//
// Designed to sit behind `tailscale serve` (tailnet-only HTTPS) so yarr (by hostname,
// passing its SSRF guard) and your browser can both reach it.
package main

import (
	"bytes"
	"flag"
	"log"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/PuerkitoBio/goquery"
	"github.com/gorilla/feeds"
	"github.com/mmcdole/gofeed"
	bolt "go.etcd.io/bbolt"
)

var (
	publicBase      string
	flaresolverrURL string
	cacheDB         *bolt.DB
	cacheTTL        time.Duration
)

// defaultPaywallHosts is the out-of-the-box set of metered/soft-paywalled news sites whose
// article body is server-rendered (for SEO/crawlers) but walled by client-side JS. Rendering
// them with JavaScript disabled returns the full text. Override with RSSPROXY_PAYWALL_HOSTS.
const defaultPaywallHosts = "nytimes.com,wsj.com,washingtonpost.com,economist.com,ft.com,theatlantic.com,wired.com,newyorker.com,bloomberg.com,businessinsider.com,technologyreview.com,theathletic.com,latimes.com,vanityfair.com"

func main() {
	addr := flag.String("addr", env("RSSPROXY_ADDR", "127.0.0.1:7071"), "listen address")
	base := flag.String("public-base", env("RSSPROXY_PUBLIC_BASE", "http://127.0.0.1:7071"), "public base URL used in rewritten links (the tailnet HTTPS URL)")
	cachePath := flag.String("cache", env("RSSPROXY_CACHE", defaultCachePath()), "path to bbolt cache file")
	ttlHours := flag.Int("ttl-hours", envInt("RSSPROXY_TTL_HOURS", 720), "article cache TTL in hours (0 = forever)")
	flag.StringVar(&flaresolverrURL, "flaresolverr", env("RSSPROXY_FLARESOLVERR", ""), "optional FlareSolverr endpoint for the browser fallback tier")
	flag.StringVar(&renderURL, "render-url", env("RSSPROXY_RENDER_URL", ""), "Camoufox sidecar render endpoint (preferred browser tier)")
	flag.StringVar(&chromePath, "chrome", env("RSSPROXY_CHROME", ""), "path to chromium/chrome for JS page rendering (browser tier fallback); empty disables it")
	renderHostsRaw := flag.String("render-hosts", env("RSSPROXY_RENDER_HOSTS", ""), "comma-separated domains to ALWAYS render in the browser (JS-SPA sites)")
	chromedpHostsRaw := flag.String("chromedp-hosts", env("RSSPROXY_CHROMEDP_HOSTS", ""), "comma-separated domains to render via Chromium (chromedp) instead of Camoufox")
	paywallHostsRaw := flag.String("paywall-hosts", env("RSSPROXY_PAYWALL_HOSTS", defaultPaywallHosts), "comma-separated metered/paywalled news domains to render with JavaScript disabled (paywall bypass)")
	flag.StringVar(&paywallUA, "paywall-ua", env("RSSPROXY_PAYWALL_UA", ""), "optional User-Agent for paywall-bypass renders (e.g. a Googlebot string); empty keeps the browser default")
	flag.Parse()

	for _, h := range strings.Split(*renderHostsRaw, ",") {
		if s := strings.TrimSpace(h); s != "" {
			renderHosts = append(renderHosts, s)
		}
	}
	for _, h := range strings.Split(*chromedpHostsRaw, ",") {
		if s := strings.TrimSpace(h); s != "" {
			chromedpHosts = append(chromedpHosts, s)
		}
	}
	for _, h := range strings.Split(*paywallHostsRaw, ",") {
		if s := strings.TrimSpace(h); s != "" {
			paywallHosts = append(paywallHosts, s)
		}
	}

	publicBase = strings.TrimRight(*base, "/")
	cacheTTL = time.Duration(*ttlHours) * time.Hour

	if err := os.MkdirAll(filepath.Dir(*cachePath), 0o755); err != nil {
		log.Fatalf("cache dir: %v", err)
	}
	db, err := openCache(*cachePath)
	if err != nil {
		log.Fatalf("open cache: %v", err)
	}
	defer db.Close()
	cacheDB = db

	mux := http.NewServeMux()
	mux.HandleFunc("/feed", handleFeed)
	mux.HandleFunc("/htmlfeed", handleHTMLFeed)
	mux.HandleFunc("/article", handleArticle)
	mux.HandleFunc("/img", handleImg)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ok")) })

	log.Printf("rssproxy listening on %s (public base %s, cache %s, flaresolverr=%q)",
		*addr, publicBase, *cachePath, flaresolverrURL)
	log.Fatal(http.ListenAndServe(*addr, mux))
}

// /feed: rewrite each item's link to point at /article. No article scraping here.
func handleFeed(w http.ResponseWriter, r *http.Request) {
	src := r.URL.Query().Get("url")
	if src == "" {
		http.Error(w, "missing url", http.StatusBadRequest)
		return
	}
	res, err := impersonateGet(src, "")
	if err != nil {
		http.Error(w, "fetch feed: "+err.Error(), http.StatusBadGateway)
		return
	}
	parsed, err := gofeed.NewParser().Parse(bytes.NewReader(res.Body))
	if err != nil {
		http.Error(w, "parse feed: "+err.Error(), http.StatusBadGateway)
		return
	}

	out := &feeds.Feed{
		Title:       parsed.Title,
		Link:        &feeds.Link{Href: firstNonEmpty(parsed.Link, src)},
		Description: parsed.Description,
		Created:     time.Now(),
	}
	for _, it := range parsed.Items {
		if it.Link == "" {
			continue
		}
		created := time.Now()
		if it.PublishedParsed != nil {
			created = *it.PublishedParsed
		} else if it.UpdatedParsed != nil {
			created = *it.UpdatedParsed
		}
		id := it.GUID
		if id == "" {
			id = it.Link
		}
		desc := it.Description
		if desc == "" {
			desc = it.Content
		}
		item := &feeds.Item{
			Title:       it.Title,
			Link:        &feeds.Link{Href: publicBase + "/article?url=" + url.QueryEscape(it.Link)},
			Id:          id, // keep ORIGINAL guid so yarr dedupes correctly
			Created:     created,
			Description: desc,
		}
		if it.Author != nil && it.Author.Name != "" {
			item.Author = &feeds.Author{Name: it.Author.Name}
		}
		out.Items = append(out.Items, item)
	}

	rss, err := out.ToRss()
	if err != nil {
		http.Error(w, "build feed: "+err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/rss+xml; charset=utf-8")
	w.Write([]byte(rss))
}

// /htmlfeed: synthesize a feed from an HTML index page for sites with no RSS feed.
// Params: url=<index page>, match=<substring every item URL must contain> (optional),
// sel=<CSS selector for links> (optional, default "a[href]"). Item links are rewritten
// to /article like /feed. Items are undated (no dates on an index), so yarr orders them
// by fetch time; de-dup is by original URL (guid).
func handleHTMLFeed(w http.ResponseWriter, r *http.Request) {
	src := r.URL.Query().Get("url")
	if src == "" {
		http.Error(w, "missing url", http.StatusBadRequest)
		return
	}
	if !allowedURL(src) {
		http.Error(w, "blocked url", http.StatusForbidden)
		return
	}
	match := r.URL.Query().Get("match")
	sel := r.URL.Query().Get("sel")
	if sel == "" {
		sel = "a[href]"
	}
	res, err := impersonateGet(src, "")
	if err != nil {
		http.Error(w, "fetch index: "+err.Error(), http.StatusBadGateway)
		return
	}
	base, _ := url.Parse(src)
	doc, err := goquery.NewDocumentFromReader(bytes.NewReader(res.Body))
	if err != nil {
		http.Error(w, "parse index: "+err.Error(), http.StatusBadGateway)
		return
	}
	title := strings.TrimSpace(doc.Find("title").First().Text())
	if title == "" {
		title = src
	}
	out := &feeds.Feed{Title: title, Link: &feeds.Link{Href: src}, Created: time.Now()}
	seen := map[string]bool{}
	now := time.Now()
	idx := 0
	doc.Find(sel).Each(func(_ int, s *goquery.Selection) {
		href, ok := s.Attr("href")
		if !ok {
			return
		}
		txt := strings.TrimSpace(s.Text())
		if txt == "" {
			return
		}
		abs := resolveURL(base, href)
		if abs == "" {
			return
		}
		if i := strings.Index(abs, "#"); i >= 0 {
			abs = abs[:i]
		}
		if match != "" && !strings.Contains(abs, match) {
			return
		}
		if strings.TrimRight(abs, "/") == strings.TrimRight(src, "/") {
			return // skip self
		}
		if seen[abs] {
			return
		}
		seen[abs] = true
		// Date: stable per-URL first-seen. On the first batch, offset by index position
		// so the index order is preserved (top of index = newest). Articles that appear
		// in the index later get a fresh (newer) first-seen time and surface as new.
		ts := firstSeen(cacheDB, abs, now.Add(-time.Duration(idx)*time.Second))
		idx++
		out.Items = append(out.Items, &feeds.Item{
			Title:       txt,
			Link:        &feeds.Link{Href: publicBase + "/article?url=" + url.QueryEscape(abs)},
			Id:          abs,
			Created:     ts,
			Description: txt,
		})
	})
	rss, err := out.ToRss()
	if err != nil {
		http.Error(w, "build feed: "+err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/rss+xml; charset=utf-8")
	w.Write([]byte(rss))
}

// /article: on-demand render of a single page (only hit when you fetch-content in yarr).
func handleArticle(w http.ResponseWriter, r *http.Request) {
	target := r.URL.Query().Get("url")
	if target == "" {
		http.Error(w, "missing url", http.StatusBadRequest)
		return
	}
	if !allowedURL(target) {
		http.Error(w, "blocked url", http.StatusForbidden)
		return
	}
	// yarr's crawler identifies as "Yarr/<ver>". Anything else is a real browser doing
	// "open original" - send it to the actual source site (so e.g. interactive shaders work),
	// not our reader-rendered copy.
	if !strings.HasPrefix(r.Header.Get("User-Agent"), "Yarr") {
		http.Redirect(w, r, target, http.StatusFound)
		return
	}
	if c, ok := getArticle(cacheDB, target, cacheTTL); ok {
		writeHTML(w, c.HTML)
		return
	}

	u, _ := url.Parse(target)
	isPaywall := browserEnabled() && hostIsPaywalled(u)

	var res *fetchResult
	var err error

	// Paywall tier: skip the HTTP fetch (often bot-blocked or server-truncated) and render
	// in the browser with JavaScript disabled. Two strategies:
	//   1. If a per-site extractor is registered (e.g. NYT), pull the COMPLETE article out of
	//      the page's embedded JSON (__preloadedData) - bypasses the DOM truncation entirely.
	//   2. Otherwise use the JS-off DOM directly: many sites server-render the full body and
	//      only inject the meter/overlay with client JS, so JS-off yields the full text.
	if isPaywall {
		log.Printf("paywall-bypass render (js disabled) %s", target)
		if h, berr := browserRenderOpts(target, paywallRenderOpts()); berr == nil && strings.TrimSpace(h) != "" {
			if ex := extractorFor(u); ex != nil {
				if art, ok := ex(h); ok {
					log.Printf("paywall extractor recovered article %s (%d bytes)", target, len(art))
					res = &fetchResult{Body: []byte(art), FinalURL: target, Status: 200, ContentType: "text/html"}
				} else {
					log.Printf("paywall extractor found no article %s", target)
				}
			}
			if res == nil && !articleThin(h) {
				res = &fetchResult{Body: []byte(h), FinalURL: target, Status: 200, ContentType: "text/html"}
			}
		} else if berr != nil {
			log.Printf("paywall-bypass render failed for %s: %v", target, berr)
		}

		// JS-off/extractor came up empty (client-rendered SPA behind a bot wall, e.g.
		// Bloomberg/PerimeterX). Retry as a real reader: warm up via the site origin to
		// acquire the anti-bot clearance cookie, then load the article (JS on) in the same
		// context with the origin as referer.
		if res == nil {
			log.Printf("paywall-bypass thin for %s, trying warm-up render", target)
			opts := renderOpts{Referer: originOf(u), WaitMs: 6000, Warmup: true}
			if h, berr := browserRenderOpts(target, opts); berr == nil && !articleThin(h) {
				log.Printf("paywall warm-up render succeeded %s", target)
				res = &fetchResult{Body: []byte(h), FinalURL: target, Status: 200, ContentType: "text/html"}
			} else if berr != nil {
				log.Printf("paywall warm-up render failed for %s: %v", target, berr)
			}
		}
	}

	if res == nil {
		res, err = fetchPage(target, originOf(u))
		if err != nil {
			http.Error(w, "fetch: "+err.Error(), http.StatusBadGateway)
			return
		}
		// Browser tier: if the fast result is blocked or has no real article paragraphs
		// (JS-rendered SPA like BBC), re-render the page in the browser.
		if browserEnabled() && (hostNeedsBrowser(u) || isBlocked(res) || needsRender(res.Body, u)) {
			log.Printf("rendering %s in browser", target)
			if h, berr := browserRender(target); berr == nil && strings.TrimSpace(h) != "" {
				// A registered site extractor (e.g. BBC) pulls the clean article out of the
				// rendered page's embedded JSON, dropping all the nav/consent chrome that
				// otherwise swamps yarr's readability.
				if ex := extractorFor(u); ex != nil {
					if art, ok := ex(h); ok {
						log.Printf("site extractor recovered article %s (%d bytes)", target, len(art))
						h = art
					}
				}
				res = &fetchResult{Body: []byte(h), FinalURL: target, Status: 200, ContentType: "text/html"}
			} else if berr != nil {
				log.Printf("browser render failed for %s: %v", target, berr)
			}
		}
	}

	// Resolve relative URLs (images) against the FINAL url after redirects.
	base := u
	if res.FinalURL != "" {
		if fu, e := url.Parse(res.FinalURL); e == nil {
			base = fu
		}
	}

	body := string(res.Body)
	if isPaywall {
		// JS-off usually leaves no overlay, but some sites still server-render a
		// "subscribe to keep reading" node and hide the body via CSS. Strip the common
		// ones generically so yarr's readability sees a clean article.
		body = stripPaywallDoc(body)
	}

	// Return the FULL fetched page with images proxied. We do NOT pre-extract:
	// yarr re-runs its own readability on whatever /page returns, so the proxy's job
	// is to (a) fetch pages yarr can't (anti-bot/406) and (b) rewrite <img> to /img so
	// the kept images aren't hotlink-blocked. yarr handles the article extraction.
	page := rewriteImagesDoc(body, base)

	putArticle(cacheDB, target, &cachedArticle{HTML: page})
	writeHTML(w, page)
}

// /img: fetch an image with a same-origin Referer to bypass hotlink protection.
func handleImg(w http.ResponseWriter, r *http.Request) {
	target := r.URL.Query().Get("url")
	ref := r.URL.Query().Get("ref")
	if target == "" {
		http.Error(w, "missing url", http.StatusBadRequest)
		return
	}
	if !allowedURL(target) {
		http.Error(w, "blocked url", http.StatusForbidden)
		return
	}
	if ref == "" {
		if u, err := url.Parse(target); err == nil {
			ref = originOf(u)
		}
	}
	res, err := impersonateGet(target, ref)
	if err != nil {
		http.Error(w, "img fetch: "+err.Error(), http.StatusBadGateway)
		return
	}
	ct := res.ContentType
	if ct == "" {
		ct = "application/octet-stream"
	}
	w.Header().Set("Content-Type", ct)
	w.Header().Set("Cache-Control", "public, max-age=604800")
	w.WriteHeader(res.Status)
	w.Write(res.Body)
}

// rewriteImagesDoc points every <img> at /img (lazy, browser-loaded, referer-fixed)
// and returns the full HTML document for yarr's readability to extract from.
func rewriteImagesDoc(htmlStr string, base *url.URL) string {
	doc, err := goquery.NewDocumentFromReader(strings.NewReader(htmlStr))
	if err != nil {
		return htmlStr
	}
	ref := originOf(base)
	doc.Find("img").Each(func(_ int, s *goquery.Selection) {
		src, _ := s.Attr("src")
		for _, a := range []string{"data-src", "data-original", "data-lazy-src", "data-actualsrc"} {
			if strings.TrimSpace(src) == "" {
				if v, ok := s.Attr(a); ok && v != "" {
					src = v
				}
			}
		}
		src = strings.TrimSpace(src)
		if src == "" || strings.HasPrefix(src, "data:") {
			return
		}
		abs := resolveURL(base, src)
		if abs == "" {
			return
		}
		prox := publicBase + "/img?url=" + url.QueryEscape(abs) + "&ref=" + url.QueryEscape(ref)
		s.SetAttr("src", prox)
		s.RemoveAttr("srcset")
		s.RemoveAttr("loading")
	})
	// strip <source srcset> in <picture> so the browser can't bypass the proxy
	doc.Find("source").Each(func(_ int, s *goquery.Selection) { s.RemoveAttr("srcset") })

	// Site-specific fixups for whitespace-significant code blocks that use no <pre>.
	// Inigo Quilez marks code as <div class="code"> with literal-space indentation and
	// <br> line breaks; yarr's sanitizer drops the CSS, collapsing it. Convert to <pre>.
	if base != nil && strings.Contains(strings.ToLower(base.Hostname()), "iquilezles.org") {
		doc.Find("div.code").Each(func(_ int, s *goquery.Selection) {
			if inner, err := s.Html(); err == nil {
				inner = strings.ReplaceAll(inner, "<br/>", "\n")
				inner = strings.ReplaceAll(inner, "<br>", "\n")
				s.SetHtml(inner)
			}
			if len(s.Nodes) > 0 {
				s.Nodes[0].Data = "pre" // relabel <div> -> <pre>
			}
		})
	}

	out, err := doc.Html()
	if err != nil {
		return htmlStr
	}
	return out
}

// stripPaywallDoc removes common paywall/subscription overlay nodes that some sites
// server-render even with JS off, and un-hides the document body (sites often set
// overflow:hidden / position:fixed on <html>/<body> to freeze scrolling behind a wall).
// It's deliberately generic - readability discards most non-article nodes anyway; this just
// keeps an overlay from being mistaken for the article and restores a scrollable body.
func stripPaywallDoc(htmlStr string) string {
	doc, err := goquery.NewDocumentFromReader(strings.NewReader(htmlStr))
	if err != nil {
		return htmlStr
	}
	// Substrings matched against id/class/data-testid of removable overlay nodes.
	markers := []string{
		"paywall", "pay-wall", "meter", "metering", "subscribe-wall", "subscription-wall",
		"regiwall", "regwall", "gateway", "piano", "tp-modal", "tp-backdrop", "tp-iframe",
		"gate-container", "bottom-of-article", "expanded-dock", "fc-ab-root",
	}
	sel := make([]string, 0, len(markers)*3)
	for _, m := range markers {
		sel = append(sel, "[id*='"+m+"']", "[class*='"+m+"']", "[data-testid*='"+m+"']")
	}
	doc.Find(strings.Join(sel, ",")).Each(func(_ int, s *goquery.Selection) { s.Remove() })

	// Re-enable scrolling: drop inline overflow/position locks on html/body.
	doc.Find("html,body").Each(func(_ int, s *goquery.Selection) {
		if style, ok := s.Attr("style"); ok && style != "" {
			low := strings.ToLower(style)
			if strings.Contains(low, "overflow") || strings.Contains(low, "position") || strings.Contains(low, "height") {
				s.RemoveAttr("style")
			}
		}
	})
	out, err := doc.Html()
	if err != nil {
		return htmlStr
	}
	return out
}

func writeHTML(w http.ResponseWriter, s string) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write([]byte(s))
}

func resolveURL(base *url.URL, ref string) string {
	r, err := url.Parse(strings.TrimSpace(ref))
	if err != nil {
		return ""
	}
	if base == nil {
		return r.String()
	}
	return base.ResolveReference(r).String()
}

func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func envInt(k string, def int) int {
	if v := os.Getenv(k); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func defaultCachePath() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".local", "share", "rssproxy", "cache.db")
}
