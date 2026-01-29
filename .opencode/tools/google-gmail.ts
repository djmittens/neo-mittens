import { tool } from "@opencode-ai/plugin"
import { readFileSync, existsSync } from "fs"
import { homedir } from "os"
import { join } from "path"

/**
 * Get quota project from ADC credentials file
 */
function getQuotaProject(): string | null {
  const adcPath = join(homedir(), ".config", "gcloud", "application_default_credentials.json")
  if (!existsSync(adcPath)) {
    return null
  }
  try {
    const adc = JSON.parse(readFileSync(adcPath, "utf-8"))
    return adc.quota_project_id || null
  } catch {
    return null
  }
}

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
 * Make authenticated request to Gmail API
 */
async function gmailApi(endpoint: string, options: RequestInit = {}): Promise<any> {
  const token = await getAccessToken()
  const quotaProject = getQuotaProject()
  
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  }
  
  if (quotaProject) {
    headers["x-goog-user-project"] = quotaProject
  }
  
  const response = await fetch(`https://gmail.googleapis.com${endpoint}`, {
    ...options,
    headers: {
      ...headers,
      ...options.headers,
    },
  })
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Gmail API error (${response.status}): ${error}`)
  }
  return response.json()
}

/**
 * Decode base64url encoded string
 */
function decodeBase64Url(str: string): string {
  // Convert base64url to base64
  const base64 = str.replace(/-/g, "+").replace(/_/g, "/")
  // Decode
  return Buffer.from(base64, "base64").toString("utf-8")
}

/**
 * Extract header value from message
 */
function getHeader(headers: any[], name: string): string {
  const header = headers?.find(
    (h: any) => h.name.toLowerCase() === name.toLowerCase()
  )
  return header?.value || ""
}

/**
 * Extract plain text body from message
 */
function extractBody(payload: any): string {
  // Direct body
  if (payload.body?.data) {
    return decodeBase64Url(payload.body.data)
  }

  // Multipart
  if (payload.parts) {
    // Look for text/plain first
    const textPart = payload.parts.find(
      (p: any) => p.mimeType === "text/plain"
    )
    if (textPart?.body?.data) {
      return decodeBase64Url(textPart.body.data)
    }

    // Fallback to text/html
    const htmlPart = payload.parts.find(
      (p: any) => p.mimeType === "text/html"
    )
    if (htmlPart?.body?.data) {
      const html = decodeBase64Url(htmlPart.body.data)
      // Basic HTML stripping
      return html
        .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "")
        .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "")
        .replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .trim()
    }

    // Nested multipart
    for (const part of payload.parts) {
      if (part.parts) {
        const nested = extractBody(part)
        if (nested) return nested
      }
    }
  }

  return ""
}

export const list = tool({
  description: `List emails from Gmail inbox.
  
Returns recent emails with sender, subject, and date.`,
  args: {
    query: tool.schema
      .string()
      .optional()
      .describe("Gmail search query (e.g., 'from:user@example.com', 'is:unread')"),
    max_results: tool.schema
      .number()
      .optional()
      .default(10)
      .describe("Maximum emails to return (default: 10)"),
    label: tool.schema
      .string()
      .optional()
      .default("INBOX")
      .describe("Label to filter by (default: INBOX)"),
  },
  async execute(args) {
    const { query, max_results = 10, label = "INBOX" } = args

    const params = new URLSearchParams({
      maxResults: String(max_results),
    })
    if (query) params.set("q", query)
    if (label) params.set("labelIds", label)

    const list = await gmailApi(`/gmail/v1/users/me/messages?${params}`)

    if (!list.messages || list.messages.length === 0) {
      return "No emails found."
    }

    // Fetch metadata for each message
    const messages: string[] = []
    for (const msg of list.messages.slice(0, max_results)) {
      const detail = await gmailApi(
        `/gmail/v1/users/me/messages/${msg.id}?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date`
      )
      const from = getHeader(detail.payload?.headers, "From")
      const subject = getHeader(detail.payload?.headers, "Subject")
      const date = getHeader(detail.payload?.headers, "Date")
      const snippet = detail.snippet || ""

      messages.push(
        `- **${subject || "(No subject)"}**\n  ID: ${msg.id}\n  From: ${from}\n  Date: ${date}\n  ${snippet.slice(0, 100)}...`
      )
    }

    return `## Emails\n\n${messages.join("\n\n")}`
  },
})

export const read = tool({
  description: `Read the full content of an email.`,
  args: {
    message_id: tool.schema.string().describe("The message ID"),
  },
  async execute(args) {
    const { message_id } = args

    const msg = await gmailApi(
      `/gmail/v1/users/me/messages/${message_id}?format=full`
    )

    const from = getHeader(msg.payload?.headers, "From")
    const to = getHeader(msg.payload?.headers, "To")
    const subject = getHeader(msg.payload?.headers, "Subject")
    const date = getHeader(msg.payload?.headers, "Date")
    const body = extractBody(msg.payload)

    return `## ${subject || "(No subject)"}

**From:** ${from}
**To:** ${to}
**Date:** ${date}
**ID:** ${message_id}

---

${body}`
  },
})

export const search = tool({
  description: `Search emails using Gmail's search syntax.
  
Examples: "from:user@example.com", "subject:invoice", "after:2024/01/01", "has:attachment"`,
  args: {
    query: tool.schema.string().describe("Gmail search query"),
    max_results: tool.schema
      .number()
      .optional()
      .default(10)
      .describe("Maximum results (default: 10)"),
  },
  async execute(args) {
    const { query, max_results = 10 } = args

    const params = new URLSearchParams({
      q: query,
      maxResults: String(max_results),
    })

    const list = await gmailApi(`/gmail/v1/users/me/messages?${params}`)

    if (!list.messages || list.messages.length === 0) {
      return `No emails found matching: ${query}`
    }

    // Fetch metadata for each message
    const messages: string[] = []
    for (const msg of list.messages) {
      const detail = await gmailApi(
        `/gmail/v1/users/me/messages/${msg.id}?format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date`
      )
      const from = getHeader(detail.payload?.headers, "From")
      const subject = getHeader(detail.payload?.headers, "Subject")
      const date = getHeader(detail.payload?.headers, "Date")

      messages.push(
        `- **${subject || "(No subject)"}**\n  ID: ${msg.id}\n  From: ${from}\n  Date: ${date}`
      )
    }

    return `## Search results for: ${query}\n\n${messages.join("\n\n")}`
  },
})

export const list_labels = tool({
  description: `List all Gmail labels.`,
  args: {},
  async execute() {
    const data = await gmailApi("/gmail/v1/users/me/labels")

    const labels = (data.labels || [])
      .map((l: any) => `- **${l.name}** (${l.type})\n  ID: ${l.id}`)
      .join("\n\n")

    return `## Gmail Labels\n\n${labels}`
  },
})

export const get_thread = tool({
  description: `Get all messages in an email thread.`,
  args: {
    thread_id: tool.schema.string().describe("Thread ID"),
  },
  async execute(args) {
    const { thread_id } = args

    const thread = await gmailApi(
      `/gmail/v1/users/me/threads/${thread_id}?format=full`
    )

    const messages: string[] = [`## Thread: ${thread_id}`, ""]

    for (let i = 0; i < thread.messages.length; i++) {
      const msg = thread.messages[i]
      const from = getHeader(msg.payload?.headers, "From")
      const date = getHeader(msg.payload?.headers, "Date")
      const body = extractBody(msg.payload)

      messages.push(`### Message ${i + 1}`)
      messages.push(`**From:** ${from}`)
      messages.push(`**Date:** ${date}`)
      messages.push("")
      messages.push(body.slice(0, 500) + (body.length > 500 ? "..." : ""))
      messages.push("")
      messages.push("---")
      messages.push("")
    }

    return messages.join("\n")
  },
})

export const mark_read = tool({
  description: `Mark an email as read.`,
  args: {
    message_id: tool.schema.string().describe("Message ID"),
  },
  async execute(args) {
    const { message_id } = args

    await gmailApi(`/gmail/v1/users/me/messages/${message_id}/modify`, {
      method: "POST",
      body: JSON.stringify({
        removeLabelIds: ["UNREAD"],
      }),
    })

    return `Marked message ${message_id} as read`
  },
})

export const mark_unread = tool({
  description: `Mark an email as unread.`,
  args: {
    message_id: tool.schema.string().describe("Message ID"),
  },
  async execute(args) {
    const { message_id } = args

    await gmailApi(`/gmail/v1/users/me/messages/${message_id}/modify`, {
      method: "POST",
      body: JSON.stringify({
        addLabelIds: ["UNREAD"],
      }),
    })

    return `Marked message ${message_id} as unread`
  },
})
