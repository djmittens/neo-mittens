import { tool } from "@opencode-ai/plugin"

/**
 * Helper to get access token from gcloud ADC
 */
async function getAccessToken(): Promise<string> {
  const proc = Bun.spawn(["gcloud", "auth", "application-default", "print-access-token"], {
    stdout: "pipe",
    stderr: "pipe",
  })
  const output = await new Response(proc.stdout).text()
  const exitCode = await proc.exited
  if (exitCode !== 0) {
    const stderr = await new Response(proc.stderr).text()
    throw new Error(`Failed to get access token: ${stderr}`)
  }
  return output.trim()
}

/**
 * Make authenticated request to Google Docs API
 */
async function docsApi(endpoint: string, options: RequestInit = {}): Promise<any> {
  const token = await getAccessToken()
  const response = await fetch(`https://docs.googleapis.com${endpoint}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...options.headers,
    },
  })
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Google Docs API error (${response.status}): ${error}`)
  }
  return response.json()
}

/**
 * Extract plain text from Google Docs structure
 */
function extractText(doc: any): string {
  const content = doc.body?.content || []
  let text = ""

  for (const element of content) {
    if (element.paragraph) {
      for (const elem of element.paragraph.elements || []) {
        if (elem.textRun) {
          text += elem.textRun.content
        }
      }
    } else if (element.table) {
      text += "[Table]\n"
      for (const row of element.table.tableRows || []) {
        const cells = row.tableCells || []
        const rowText = cells
          .map((cell: any) => {
            let cellText = ""
            for (const content of cell.content || []) {
              if (content.paragraph) {
                for (const elem of content.paragraph.elements || []) {
                  if (elem.textRun) {
                    cellText += elem.textRun.content.trim()
                  }
                }
              }
            }
            return cellText
          })
          .join(" | ")
        text += rowText + "\n"
      }
    }
  }

  return text
}

export const read = tool({
  description: `Read the contents of a Google Doc.
  
Returns the document text content. Use google-drive_search to find document IDs.`,
  args: {
    document_id: tool.schema.string().describe("The Google Doc ID"),
    include_suggestions: tool.schema
      .boolean()
      .optional()
      .default(false)
      .describe("Include suggested changes (default: false)"),
  },
  async execute(args) {
    const { document_id } = args

    const doc = await docsApi(`/v1/documents/${document_id}`)

    const text = extractText(doc)

    return `## ${doc.title}

**Document ID:** ${document_id}
**Last modified:** Check Drive for details

---

${text}`
  },
})

export const get_structure = tool({
  description: `Get the structure of a Google Doc including headings and sections.`,
  args: {
    document_id: tool.schema.string().describe("The Google Doc ID"),
  },
  async execute(args) {
    const { document_id } = args

    const doc = await docsApi(`/v1/documents/${document_id}`)

    const structure: string[] = [`## Document Structure: ${doc.title}`, ""]

    const content = doc.body?.content || []
    let headingCount = 0

    for (const element of content) {
      if (element.paragraph) {
        const style = element.paragraph.paragraphStyle?.namedStyleType
        if (style && style.startsWith("HEADING_")) {
          headingCount++
          const level = parseInt(style.replace("HEADING_", ""))
          const text = element.paragraph.elements
            ?.map((e: any) => e.textRun?.content || "")
            .join("")
            .trim()
          structure.push(`${"  ".repeat(level - 1)}- ${text}`)
        }
      }
    }

    if (headingCount === 0) {
      structure.push("No headings found in document.")
    }

    return structure.join("\n")
  },
})

export const create = tool({
  description: `Create a new Google Doc.`,
  args: {
    title: tool.schema.string().describe("Document title"),
    content: tool.schema
      .string()
      .optional()
      .describe("Initial text content (optional)"),
  },
  async execute(args) {
    const { title, content } = args

    // Create the document
    const doc = await docsApi("/v1/documents", {
      method: "POST",
      body: JSON.stringify({ title }),
    })

    // If content provided, insert it
    if (content) {
      await docsApi(`/v1/documents/${doc.documentId}:batchUpdate`, {
        method: "POST",
        body: JSON.stringify({
          requests: [
            {
              insertText: {
                location: { index: 1 },
                text: content,
              },
            },
          ],
        }),
      })
    }

    return `## Created Document

**Title:** ${doc.title}
**ID:** ${doc.documentId}
**URL:** https://docs.google.com/document/d/${doc.documentId}/edit`
  },
})

export const append = tool({
  description: `Append text to the end of a Google Doc.`,
  args: {
    document_id: tool.schema.string().describe("The Google Doc ID"),
    text: tool.schema.string().describe("Text to append"),
  },
  async execute(args) {
    const { document_id, text } = args

    // Get current document to find end index
    const doc = await docsApi(`/v1/documents/${document_id}`)
    const endIndex = doc.body?.content?.slice(-1)[0]?.endIndex || 1

    // Insert at end (before final newline)
    await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
      method: "POST",
      body: JSON.stringify({
        requests: [
          {
            insertText: {
              location: { index: endIndex - 1 },
              text: "\n" + text,
            },
          },
        ],
      }),
    })

    return `Appended ${text.length} characters to document: ${doc.title}`
  },
})

export const find_replace = tool({
  description: `Find and replace text in a Google Doc.`,
  args: {
    document_id: tool.schema.string().describe("The Google Doc ID"),
    find: tool.schema.string().describe("Text to find"),
    replace: tool.schema.string().describe("Replacement text"),
    match_case: tool.schema
      .boolean()
      .optional()
      .default(false)
      .describe("Case-sensitive match (default: false)"),
  },
  async execute(args) {
    const { document_id, find, replace, match_case = false } = args

    const result = await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
      method: "POST",
      body: JSON.stringify({
        requests: [
          {
            replaceAllText: {
              containsText: {
                text: find,
                matchCase: match_case,
              },
              replaceText: replace,
            },
          },
        ],
      }),
    })

    const count =
      result.replies?.[0]?.replaceAllText?.occurrencesChanged || 0

    return `Replaced ${count} occurrence(s) of "${find}" with "${replace}"`
  },
})
