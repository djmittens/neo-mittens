package main

// NYT paywall extraction.
//
// nytimes.com is a client-rendered React app: the rendered DOM truncates the article after a
// few paragraphs ("Subscribe to The Times to read..."), but the COMPLETE article (headline,
// byline, summary, every paragraph with its links, and images) is embedded verbatim in a
// `window.__preloadedData = {...}` JSON blob in the server HTML. We render the page in
// Camoufox with JS disabled (fast, and the blob is never truncated), then reconstruct clean
// article HTML straight from that JSON - no paywall, no IP/cookie tricks.

import (
	"encoding/json"
	"html"
	"net/url"
	"strings"

	"github.com/PuerkitoBio/goquery"
)

// paywallExtractor reconstructs full article HTML from a rendered page's embedded data.
// Registered per site because each platform embeds its content differently.
type paywallExtractor func(pageHTML string) (string, bool)

var paywallExtractors = map[string]paywallExtractor{
	"nytimes.com": extractNYTArticle,
	"bbc.com":     extractBBCArticle,
	"bbc.co.uk":   extractBBCArticle,
}

// extractorFor returns the registered extractor for a host (matching the domain or any
// subdomain), or nil.
func extractorFor(u *url.URL) paywallExtractor {
	if u == nil {
		return nil
	}
	h := strings.ToLower(u.Hostname())
	for d, ex := range paywallExtractors {
		if h == d || strings.HasSuffix(h, "."+d) {
			return ex
		}
	}
	return nil
}

// articleThin reports whether rendered HTML lacks a real article body. Unlike needsRender
// (which trusts readability and is fooled by JSON/script text on client-rendered SPAs), this
// counts only substantial text inside <p> tags.
func articleThin(pageHTML string) bool {
	doc, err := goquery.NewDocumentFromReader(strings.NewReader(pageHTML))
	if err != nil {
		return true
	}
	doc.Find("script,style,nav,header,footer").Remove()
	total := 0
	doc.Find("p").Each(func(_ int, s *goquery.Selection) {
		if t := strings.TrimSpace(s.Text()); len(t) > 40 {
			total += len(t)
		}
	})
	return total < 600
}

// extractNYTArticle pulls window.__preloadedData out of an NYT page and rebuilds the article
// as clean HTML. Returns (html, true) on success.
func extractNYTArticle(pageHTML string) (string, bool) {
	raw, ok := extractJSONAssignment(pageHTML, "window.__preloadedData")
	if !ok {
		return "", false
	}
	var data map[string]any
	if err := json.Unmarshal([]byte(sanitizeJSAssignment(raw)), &data); err != nil {
		return "", false
	}
	art, ok := dig(data, "initialData", "data", "article").(map[string]any)
	if !ok {
		return "", false
	}

	body, _ := art["sprinkledBody"].(map[string]any)
	if body == nil {
		body, _ = art["body"].(map[string]any)
	}
	content, _ := body["content"].([]any)
	if len(content) == 0 {
		return "", false
	}

	var b strings.Builder
	b.WriteString("<article>")
	if hl := str(dig(art, "headline", "default")); hl != "" {
		b.WriteString("<h1>" + html.EscapeString(hl) + "</h1>")
	}
	if by := nytByline(art); by != "" {
		b.WriteString("<p><em>" + html.EscapeString(by) + "</em></p>")
	}
	if sm := str(art["summary"]); sm != "" {
		b.WriteString("<p><strong>" + html.EscapeString(sm) + "</strong></p>")
	}

	paras := nytRenderBlocks(content, &b)
	b.WriteString("</article>")

	// Require a real article body so we don't emit an empty shell (then the caller falls
	// back to the generic render path).
	if paras < 2 {
		return "", false
	}
	return b.String(), true
}

// nytRenderBlocks walks an ordered block list and appends HTML. Returns the number of
// paragraph-like blocks emitted (a body-completeness signal).
func nytRenderBlocks(blocks []any, b *strings.Builder) int {
	paras := 0
	for _, raw := range blocks {
		blk, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		switch str(blk["__typename"]) {
		case "ParagraphBlock":
			if s := nytInline(blk["content"]); strings.TrimSpace(stripTags(s)) != "" {
				b.WriteString("<p>" + s + "</p>")
				paras++
			}
		case "Heading1Block", "Heading2Block", "Heading3Block", "HeaderBasicBlock":
			if s := nytInline(blk["content"]); strings.TrimSpace(stripTags(s)) != "" {
				b.WriteString("<h2>" + s + "</h2>")
			}
		case "BlockquoteBlock", "PullquoteBlock":
			if s := nytInline(blk["content"]); strings.TrimSpace(stripTags(s)) != "" {
				b.WriteString("<blockquote>" + s + "</blockquote>")
				paras++
			} else if inner, ok := blk["content"].([]any); ok {
				b.WriteString("<blockquote>")
				paras += nytRenderBlocks(inner, b)
				b.WriteString("</blockquote>")
			}
		case "DetailBlock":
			if inner, ok := blk["content"].([]any); ok {
				paras += nytRenderBlocks(inner, b)
			}
		case "ListBlock":
			tag := "ul"
			if strings.EqualFold(str(blk["style"]), "ORDERED") {
				tag = "ol"
			}
			b.WriteString("<" + tag + ">")
			if items, ok := blk["content"].([]any); ok {
				for _, it := range items {
					if im, ok := it.(map[string]any); ok {
						b.WriteString("<li>" + nytInline(im["content"]) + "</li>")
					}
				}
			}
			b.WriteString("</" + tag + ">")
		case "ImageBlock":
			b.WriteString(nytImage(blk))
		case "HeaderFullBleedHorizontalBlock", "HeaderFullBleedVerticalBlock", "HeaderLegacyBlock":
			if lede, ok := blk["ledeMedia"].(map[string]any); ok {
				b.WriteString(nytImage(lede))
			}
		}
	}
	return paras
}

// nytInline renders an array of TextInline nodes into HTML, applying link/bold/italic formats.
func nytInline(raw any) string {
	arr, ok := raw.([]any)
	if !ok {
		return ""
	}
	var sb strings.Builder
	for _, n := range arr {
		node, ok := n.(map[string]any)
		if !ok {
			continue
		}
		// Some inline nodes nest further content (e.g. LineBreakInline); recurse if no text.
		txt := str(node["text"])
		if txt == "" {
			if inner, ok := node["content"].([]any); ok {
				sb.WriteString(nytInline(inner))
			}
			continue
		}
		piece := html.EscapeString(txt)
		var pre, post string
		if formats, ok := node["formats"].([]any); ok {
			for _, f := range formats {
				fm, ok := f.(map[string]any)
				if !ok {
					continue
				}
				switch str(fm["__typename"]) {
				case "LinkFormat":
					if u := str(fm["url"]); u != "" {
						pre = `<a href="` + html.EscapeString(u) + `">` + pre
						post = post + "</a>"
					}
				case "BoldFormat", "Bold":
					pre, post = "<strong>"+pre, post+"</strong>"
				case "ItalicFormat", "Italic", "EmphasisFormat":
					pre, post = "<em>"+pre, post+"</em>"
				}
			}
		}
		sb.WriteString(pre + piece + post)
	}
	return sb.String()
}

// nytImage builds a <figure> from an ImageBlock, choosing a reasonably sized rendition.
func nytImage(blk map[string]any) string {
	media, ok := blk["media"].(map[string]any)
	if !ok {
		return ""
	}
	url := bestNYTRendition(media)
	if url == "" {
		return ""
	}
	out := `<figure><img src="` + html.EscapeString(url) + `"/>`
	cap := str(dig(media, "caption", "text"))
	credit := str(media["credit"])
	if cap != "" || credit != "" {
		out += "<figcaption>" + html.EscapeString(strings.TrimSpace(cap+" "+credit)) + "</figcaption>"
	}
	out += "</figure>"
	return out
}

// bestNYTRendition picks the widest crop rendition no wider than 1600px (else the widest).
func bestNYTRendition(media map[string]any) string {
	crops, _ := media["crops"].([]any)
	bestURL, bestW := "", -1
	fallbackURL, fallbackW := "", 1<<30
	for _, c := range crops {
		crop, ok := c.(map[string]any)
		if !ok {
			continue
		}
		rends, _ := crop["renditions"].([]any)
		for _, r := range rends {
			rend, ok := r.(map[string]any)
			if !ok {
				continue
			}
			u := str(rend["url"])
			if u == "" {
				continue
			}
			w := intval(rend["width"])
			if w <= 1600 && w > bestW {
				bestURL, bestW = u, w
			}
			if w < fallbackW {
				fallbackURL, fallbackW = u, w
			}
		}
	}
	if bestURL != "" {
		return bestURL
	}
	return fallbackURL
}

func nytByline(art map[string]any) string {
	if bls, ok := art["bylines"].([]any); ok {
		for _, bl := range bls {
			if m, ok := bl.(map[string]any); ok {
				if r := str(m["renderedRepresentation"]); r != "" {
					return r
				}
			}
		}
	}
	return ""
}

// --- small helpers ---

// dig walks nested map[string]any by keys, returning nil if any step is missing.
func dig(m any, keys ...string) any {
	cur := m
	for _, k := range keys {
		mm, ok := cur.(map[string]any)
		if !ok {
			return nil
		}
		cur = mm[k]
	}
	return cur
}

func str(v any) string {
	s, _ := v.(string)
	return s
}

func intval(v any) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	}
	return 0
}

func stripTags(s string) string {
	for {
		i := strings.IndexByte(s, '<')
		if i < 0 {
			break
		}
		j := strings.IndexByte(s[i:], '>')
		if j < 0 {
			break
		}
		s = s[:i] + s[i+j+1:]
	}
	return s
}

// extractJSONAssignment finds `<marker> = {...}` and returns the balanced {...} object,
// honoring string literals and escapes so braces inside strings don't unbalance it.
func extractJSONAssignment(s, marker string) (string, bool) {
	i := strings.Index(s, marker)
	if i < 0 {
		return "", false
	}
	rest := s[i+len(marker):]
	eq := strings.IndexByte(rest, '=')
	if eq < 0 {
		return "", false
	}
	rest = rest[eq+1:]
	start := strings.IndexByte(rest, '{')
	if start < 0 {
		return "", false
	}
	depth, inStr, esc := 0, false, false
	for j := start; j < len(rest); j++ {
		c := rest[j]
		if esc {
			esc = false
			continue
		}
		switch {
		case c == '\\':
			esc = true
		case c == '"':
			inStr = !inStr
		case inStr:
			// skip
		case c == '{':
			depth++
		case c == '}':
			depth--
			if depth == 0 {
				return rest[start : j+1], true
			}
		}
	}
	return "", false
}

// sanitizeJSAssignment turns JS-only literals (undefined) into valid JSON so encoding/json
// can parse the blob. Only positional occurrences are replaced (never inside string values).
func sanitizeJSAssignment(s string) string {
	r := strings.NewReplacer(
		":undefined", ":null",
		"[undefined", "[null",
		",undefined", ",null",
	)
	return r.Replace(s)
}
