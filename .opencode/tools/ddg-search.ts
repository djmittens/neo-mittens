import { tool } from "@opencode-ai/plugin"
import { execFile } from "node:child_process"
import { readFile, unlink } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"

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

    // Use the `ddgs` Python library via uvx — handles DDG's token
    // negotiation and bot-detection bypass via the primp HTTP client
    const uvx = process.env.HOME + "/.local/bin/uvx"
    const tmpFile = join(tmpdir(), `ddgs_${Date.now()}_${Math.random().toString(36).slice(2)}.json`)

    try {
      await new Promise<void>((resolve, reject) => {
        execFile(
          uvx,
          [
            "--from", "ddgs",
            "ddgs", "text",
            "-k", query,
            "-m", String(max_results),
            "-o", tmpFile,
          ],
          { timeout: 30_000, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } },
          (err, _stdout, stderr) => {
            if (err) reject(new Error(stderr || err.message))
            else resolve()
          },
        )
      })

      const raw = await readFile(tmpFile, "utf-8")
      const results: SearchResult[] = JSON.parse(raw)

      if (!results || results.length === 0) {
        return `No results found for: ${query}`
      }

      const formatted = results
        .map(
          (r, i) =>
            `### ${i + 1}. ${r.title}\n${r.href}\n\n${r.body}`,
        )
        .join("\n\n---\n\n")

      return `## Search results for: ${query}\n\n${formatted}`
    } catch (error) {
      return `Search failed: ${error instanceof Error ? error.message : String(error)}`
    } finally {
      unlink(tmpFile).catch(() => {})
    }
  },
})
