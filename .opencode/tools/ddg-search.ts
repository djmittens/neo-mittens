import { tool } from "@opencode-ai/plugin"

interface SearchResult {
  title: string
  href: string
  body: string
}

export default tool({
  description: `Search the web using DuckDuckGo.
  
Returns web search results including titles, URLs, and snippets.
Useful for finding documentation, examples, current information, etc.`,
  args: {
    query: tool.schema.string().describe("Search query"),
    max_results: tool.schema
      .number()
      .optional()
      .default(5)
      .describe("Maximum number of results to return (default: 5)"),
  },
  async execute(args) {
    const { query, max_results = 5 } = args

    // Use DuckDuckGo HTML search (no API key needed)
    const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`

    try {
      const response = await fetch(url, {
        headers: {
          "User-Agent":
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        },
      })

      if (!response.ok) {
        return `Search failed: HTTP ${response.status}`
      }

      const html = await response.text()

      // Parse results from HTML
      const results: SearchResult[] = []
      const resultRegex =
        /<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]+)<\/a>[\s\S]*?<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>/g

      let match
      while ((match = resultRegex.exec(html)) !== null && results.length < max_results) {
        const href = match[1]
        const title = match[2].trim()
        const body = match[3]
          .replace(/<[^>]+>/g, "") // Strip HTML tags
          .replace(/&amp;/g, "&")
          .replace(/&lt;/g, "<")
          .replace(/&gt;/g, ">")
          .replace(/&quot;/g, '"')
          .replace(/&#x27;/g, "'")
          .replace(/\s+/g, " ")
          .trim()

        // DDG HTML uses redirect URLs, extract actual URL
        const actualUrl = decodeURIComponent(
          href.replace(/.*uddg=([^&]+).*/, "$1")
        )

        results.push({
          title,
          href: actualUrl || href,
          body,
        })
      }

      if (results.length === 0) {
        return `No results found for: ${query}`
      }

      // Format results as markdown
      const formatted = results
        .map(
          (r, i) =>
            `### ${i + 1}. ${r.title}\n${r.href}\n\n${r.body}`
        )
        .join("\n\n---\n\n")

      return `## Search results for: ${query}\n\n${formatted}`
    } catch (error) {
      return `Search failed: ${error instanceof Error ? error.message : String(error)}`
    }
  },
})
