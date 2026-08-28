package main

// BBC article extraction.
//
// BBC article pages render an enormous amount of chrome (global nav, cookie/consent banners,
// "onward journeys", topic lists, promos). yarr's readability then struggles and leads with
// "BBC HomepageSkip to content..." junk. But the clean article - headline, paragraphs,
// crossheads, images - is embedded verbatim in `window.__INITIAL_DATA__` (a JSON *string*),
// under the Optimo `article?...` node's `data.content.model.blocks`. We parse that and rebuild
// tidy HTML, so yarr shows just the article.

import (
	"encoding/json"
	"html"
	"strings"
)

// extractBBCArticle rebuilds a BBC article from window.__INITIAL_DATA__. Returns (html, true).
func extractBBCArticle(pageHTML string) (string, bool) {
	obj, ok := bbcInitialData(pageHTML)
	if !ok {
		return "", false
	}
	data, _ := obj["data"].(map[string]any)
	if data == nil {
		return "", false
	}
	// The article node's key is "article?<querystring>" (there's also "product-navigation?..."
	// which we must not match).
	var art map[string]any
	for k, v := range data {
		if strings.HasPrefix(k, "article?") {
			if m, ok := v.(map[string]any); ok {
				art = m
				break
			}
		}
	}
	if art == nil {
		return "", false
	}
	blocks, _ := dig(art, "data", "content", "model", "blocks").([]any)
	if len(blocks) == 0 {
		return "", false
	}

	var b strings.Builder
	b.WriteString("<article>")
	// Headline: metadata.headline is often null on these pages, so fall back to the top-level
	// "headline" block's text.
	hl := str(dig(art, "data", "metadata", "headline"))
	if hl == "" {
		for _, raw := range blocks {
			if blk, ok := raw.(map[string]any); ok && str(blk["type"]) == "headline" {
				hl = bbcFirstText(blk)
				break
			}
		}
	}
	if hl != "" {
		b.WriteString("<h1>" + html.EscapeString(hl) + "</h1>")
	}

	paras := bbcRenderBlocks(blocks, &b)
	b.WriteString("</article>")
	if paras < 2 {
		return "", false
	}
	return b.String(), true
}

func bbcRenderBlocks(blocks []any, b *strings.Builder) int {
	paras := 0
	for _, raw := range blocks {
		blk, _ := raw.(map[string]any)
		if blk == nil {
			continue
		}
		switch str(blk["type"]) {
		case "text":
			inner, _ := dig(blk, "model", "blocks").([]any)
			for _, p := range inner {
				pm, _ := p.(map[string]any)
				if pm == nil {
					continue
				}
				t := strings.TrimSpace(str(dig(pm, "model", "text")))
				if t == "" {
					continue
				}
				switch str(pm["type"]) {
				case "crosshead", "subheadline":
					b.WriteString("<h2>" + html.EscapeString(t) + "</h2>")
				default: // paragraph, etc.
					b.WriteString("<p>" + html.EscapeString(t) + "</p>")
					paras++
				}
			}
		case "unorderedList", "orderedList", "list":
			tag := "ul"
			if str(blk["type"]) == "orderedList" {
				tag = "ol"
			}
			items, _ := dig(blk, "model", "blocks").([]any)
			if len(items) == 0 {
				continue
			}
			b.WriteString("<" + tag + ">")
			for _, it := range items {
				if t := strings.TrimSpace(bbcFirstText(it)); t != "" {
					b.WriteString("<li>" + html.EscapeString(t) + "</li>")
				}
			}
			b.WriteString("</" + tag + ">")
		case "media":
			if u := bbcImageURL(blk); u != "" {
				b.WriteString(`<figure><img src="` + html.EscapeString(u) + `"/></figure>`)
			}
		}
	}
	return paras
}

// bbcFirstText returns the first non-empty "text" string found anywhere in a subtree.
func bbcFirstText(v any) string {
	switch n := v.(type) {
	case map[string]any:
		if t, ok := n["text"].(string); ok && strings.TrimSpace(t) != "" {
			return t
		}
		// Prefer model/blocks traversal order for stability.
		for _, k := range []string{"model", "blocks"} {
			if sub, ok := n[k]; ok {
				if t := bbcFirstText(sub); t != "" {
					return t
				}
			}
		}
		for k, sub := range n {
			if k == "model" || k == "blocks" {
				continue
			}
			if t := bbcFirstText(sub); t != "" {
				return t
			}
		}
	case []any:
		for _, e := range n {
			if t := bbcFirstText(e); t != "" {
				return t
			}
		}
	}
	return ""
}

// bbcImageURL finds the first ichef image URL in a block and fills the $recipe size template.
func bbcImageURL(v any) string {
	u := bbcFindString(v, "ichef.bbci.co.uk")
	if u == "" {
		return ""
	}
	return strings.Replace(u, "$recipe", "1024x576", 1)
}

// bbcFindString returns the first string value in a subtree containing the given substring.
func bbcFindString(v any, contains string) string {
	switch n := v.(type) {
	case string:
		if strings.Contains(n, contains) {
			return n
		}
	case map[string]any:
		for _, sub := range n {
			if s := bbcFindString(sub, contains); s != "" {
				return s
			}
		}
	case []any:
		for _, e := range n {
			if s := bbcFindString(e, contains); s != "" {
				return s
			}
		}
	}
	return ""
}

// bbcInitialData extracts and double-decodes window.__INITIAL_DATA__ (a JSON string literal
// whose contents are themselves JSON).
func bbcInitialData(pageHTML string) (map[string]any, bool) {
	const marker = "window.__INITIAL_DATA__="
	i := strings.Index(pageHTML, marker)
	if i < 0 {
		return nil, false
	}
	rest := strings.TrimLeft(pageHTML[i+len(marker):], " ")
	if rest == "" {
		return nil, false
	}
	var innerJSON string
	if rest[0] == '"' {
		lit, ok := jsonStringLiteral(rest)
		if !ok {
			return nil, false
		}
		if err := json.Unmarshal([]byte(lit), &innerJSON); err != nil {
			return nil, false
		}
	} else if rest[0] == '{' {
		// Older/object form: the value is the object directly.
		obj, ok := balancedBraces(rest)
		if !ok {
			return nil, false
		}
		innerJSON = obj
	} else {
		return nil, false
	}
	var out map[string]any
	if err := json.Unmarshal([]byte(innerJSON), &out); err != nil {
		return nil, false
	}
	return out, true
}

// jsonStringLiteral returns the JSON string literal (including surrounding quotes) that s
// starts with, honoring backslash escapes.
func jsonStringLiteral(s string) (string, bool) {
	if len(s) == 0 || s[0] != '"' {
		return "", false
	}
	esc := false
	for j := 1; j < len(s); j++ {
		c := s[j]
		if esc {
			esc = false
			continue
		}
		if c == '\\' {
			esc = true
			continue
		}
		if c == '"' {
			return s[:j+1], true
		}
	}
	return "", false
}

// balancedBraces returns the balanced {...} object at the start of s (strings/escapes aware).
func balancedBraces(s string) (string, bool) {
	depth, inStr, esc := 0, false, false
	for j := 0; j < len(s); j++ {
		c := s[j]
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
		case c == '{':
			depth++
		case c == '}':
			depth--
			if depth == 0 {
				return s[:j+1], true
			}
		}
	}
	return "", false
}
