package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/imroc/req/v3"
)

// fast tier: a single Chrome-impersonating client (forged TLS + HTTP2 fingerprint).
// Default redirect handling follows up to 10 hops (needed for http->https, trailing-slash, etc.).
var impersonator = req.C().
	ImpersonateChrome().
	SetTimeout(30 * time.Second).
	SetRedirectPolicy(req.MaxRedirectPolicy(10))

type fetchResult struct {
	Body        []byte
	FinalURL    string
	Status      int
	ContentType string
}

// impersonateGet performs the fast-tier fetch.
func impersonateGet(rawurl, referer string) (*fetchResult, error) {
	r := impersonator.R()
	if referer != "" {
		r.SetHeader("Referer", referer)
	}
	resp, err := r.Get(rawurl)
	if err != nil {
		return nil, err
	}
	// Capture the URL after redirects so relative links (e.g. images) resolve correctly.
	// e.g. /articles/foo -> /articles/foo/ changes how "img.png" resolves.
	final := rawurl
	if resp.Response != nil && resp.Response.Request != nil && resp.Response.Request.URL != nil {
		final = resp.Response.Request.URL.String()
	}
	return &fetchResult{
		Body:        resp.Bytes(),
		FinalURL:    final,
		Status:      resp.StatusCode,
		ContentType: resp.GetHeader("Content-Type"),
	}, nil
}

// isBlocked decides whether the fast tier likely hit an anti-bot wall.
func isBlocked(r *fetchResult) bool {
	if r == nil {
		return true
	}
	switch r.Status {
	case 403, 406, 429, 451, 503:
		return true
	}
	low := strings.ToLower(string(r.Body))
	for _, marker := range []string{
		"just a moment", "cf-browser-verification", "attention required",
		"checking your browser", "enable javascript and cookies",
	} {
		if strings.Contains(low, marker) {
			return true
		}
	}
	return false
}

// flaresolverrGet is the optional browser-fallback tier (a stealth headless
// browser behind an HTTP API). Enabled only when RSSPROXY_FLARESOLVERR is set.
func flaresolverrGet(endpoint, rawurl string) (*fetchResult, error) {
	payload, _ := json.Marshal(map[string]any{
		"cmd":        "request.get",
		"url":        rawurl,
		"maxTimeout": 60000,
	})
	resp, err := http.Post(endpoint, "application/json", bytes.NewReader(payload))
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	var out struct {
		Status   string `json:"status"`
		Message  string `json:"message"`
		Solution struct {
			URL      string `json:"url"`
			Status   int    `json:"status"`
			Response string `json:"response"`
		} `json:"solution"`
	}
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, err
	}
	if out.Status != "ok" {
		return nil, fmt.Errorf("flaresolverr: %s", out.Message)
	}
	return &fetchResult{
		Body:        []byte(out.Solution.Response),
		FinalURL:    out.Solution.URL,
		Status:      out.Solution.Status,
		ContentType: "text/html",
	}, nil
}

// fetchPage runs the tiered fetch: fast impersonation first, browser fallback
// only if the fast tier is blocked and a fallback is configured.
func fetchPage(rawurl, referer string) (*fetchResult, error) {
	r, err := impersonateGet(rawurl, referer)
	if err == nil && !isBlocked(r) {
		return r, nil
	}
	if flaresolverrURL != "" {
		if r2, err2 := flaresolverrGet(flaresolverrURL, rawurl); err2 == nil {
			return r2, nil
		}
	}
	if r != nil {
		return r, nil // return whatever we got (may still be usable)
	}
	return nil, err
}

// allowedURL guards our own fetchers against SSRF to internal hosts.
func allowedURL(rawurl string) bool {
	u, err := url.Parse(rawurl)
	if err != nil {
		return false
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return false
	}
	host := u.Hostname()
	if host == "" || strings.EqualFold(host, "localhost") {
		return false
	}
	if ip := net.ParseIP(host); ip != nil {
		if ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast() || ip.IsLinkLocalMulticast() || ip.IsUnspecified() {
			return false
		}
		// block cloud metadata endpoint explicitly
		if host == "169.254.169.254" {
			return false
		}
	}
	return true
}

func originOf(u *url.URL) string {
	if u == nil {
		return ""
	}
	return u.Scheme + "://" + u.Host + "/"
}
