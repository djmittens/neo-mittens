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
 * Make authenticated request to Google API
 */
async function googleApi(endpoint: string, options: RequestInit = {}): Promise<any> {
  const token = await getAccessToken()
  const response = await fetch(`https://www.googleapis.com${endpoint}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...options.headers,
    },
  })
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Google API error (${response.status}): ${error}`)
  }
  return response.json()
}

export const list = tool({
  description: `List files in Google Drive.
  
Lists files and folders. Use query parameter for filtering.
Examples: "mimeType='application/vnd.google-apps.document'" for Docs only.`,
  args: {
    query: tool.schema
      .string()
      .optional()
      .describe("Drive search query (e.g., \"name contains 'report'\")"),
    max_results: tool.schema
      .number()
      .optional()
      .default(10)
      .describe("Maximum files to return (default: 10)"),
    folder_id: tool.schema
      .string()
      .optional()
      .describe("Folder ID to list contents of (default: root)"),
  },
  async execute(args) {
    const { query, max_results = 10, folder_id } = args

    let q = "trashed = false"
    if (folder_id) {
      q += ` and '${folder_id}' in parents`
    }
    if (query) {
      q += ` and (${query})`
    }

    const params = new URLSearchParams({
      q,
      pageSize: String(max_results),
      fields: "files(id,name,mimeType,modifiedTime,webViewLink)",
      orderBy: "modifiedTime desc",
    })

    const data = await googleApi(`/drive/v3/files?${params}`)

    if (!data.files || data.files.length === 0) {
      return "No files found."
    }

    const results = data.files
      .map((f: any) => {
        const type = f.mimeType.replace("application/vnd.google-apps.", "")
        return `- **${f.name}** (${type})\n  ID: ${f.id}\n  Modified: ${f.modifiedTime}\n  ${f.webViewLink || ""}`
      })
      .join("\n\n")

    return `## Google Drive Files\n\n${results}`
  },
})

export const search = tool({
  description: `Search for files in Google Drive by name or content.`,
  args: {
    term: tool.schema.string().describe("Search term"),
    max_results: tool.schema
      .number()
      .optional()
      .default(10)
      .describe("Maximum results (default: 10)"),
  },
  async execute(args) {
    const { term, max_results = 10 } = args

    const q = `trashed = false and (name contains '${term}' or fullText contains '${term}')`
    const params = new URLSearchParams({
      q,
      pageSize: String(max_results),
      fields: "files(id,name,mimeType,modifiedTime,webViewLink)",
      orderBy: "modifiedTime desc",
    })

    const data = await googleApi(`/drive/v3/files?${params}`)

    if (!data.files || data.files.length === 0) {
      return `No files found matching: ${term}`
    }

    const results = data.files
      .map((f: any) => {
        const type = f.mimeType.replace("application/vnd.google-apps.", "")
        return `- **${f.name}** (${type})\n  ID: ${f.id}\n  ${f.webViewLink || ""}`
      })
      .join("\n\n")

    return `## Search results for: ${term}\n\n${results}`
  },
})

export const get_file_info = tool({
  description: `Get detailed information about a file in Google Drive.`,
  args: {
    file_id: tool.schema.string().describe("The file ID"),
  },
  async execute(args) {
    const { file_id } = args

    const params = new URLSearchParams({
      fields:
        "id,name,mimeType,description,createdTime,modifiedTime,size,webViewLink,owners,permissions",
    })

    const data = await googleApi(`/drive/v3/files/${file_id}?${params}`)

    return `## File: ${data.name}

- **ID:** ${data.id}
- **Type:** ${data.mimeType}
- **Created:** ${data.createdTime}
- **Modified:** ${data.modifiedTime}
- **Size:** ${data.size || "N/A"} bytes
- **Link:** ${data.webViewLink || "N/A"}
- **Description:** ${data.description || "None"}
- **Owner:** ${data.owners?.map((o: any) => o.emailAddress).join(", ") || "Unknown"}`
  },
})

export const download = tool({
  description: `Download content from a Google Drive file. Works with Docs, Sheets, etc. exported as text.`,
  args: {
    file_id: tool.schema.string().describe("The file ID"),
    format: tool.schema
      .enum(["text", "html", "pdf", "docx", "xlsx", "csv"])
      .optional()
      .default("text")
      .describe("Export format (default: text)"),
  },
  async execute(args) {
    const { file_id, format = "text" } = args

    // Get file info first
    const info = await googleApi(`/drive/v3/files/${file_id}?fields=mimeType,name`)

    const mimeMap: Record<string, string> = {
      text: "text/plain",
      html: "text/html",
      pdf: "application/pdf",
      docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      csv: "text/csv",
    }

    const token = await getAccessToken()

    // For Google Docs/Sheets/etc, use export endpoint
    if (info.mimeType.startsWith("application/vnd.google-apps.")) {
      const exportUrl = `https://www.googleapis.com/drive/v3/files/${file_id}/export?mimeType=${encodeURIComponent(mimeMap[format])}`
      const response = await fetch(exportUrl, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!response.ok) {
        throw new Error(`Export failed: ${response.status}`)
      }
      const content = await response.text()
      return `## ${info.name}\n\n${content}`
    }

    // For regular files, download directly
    const downloadUrl = `https://www.googleapis.com/drive/v3/files/${file_id}?alt=media`
    const response = await fetch(downloadUrl, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!response.ok) {
      throw new Error(`Download failed: ${response.status}`)
    }
    const content = await response.text()
    return `## ${info.name}\n\n${content}`
  },
})
