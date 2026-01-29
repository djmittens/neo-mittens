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
 * Make authenticated request to Google Calendar API
 */
async function calendarApi(endpoint: string, options: RequestInit = {}): Promise<any> {
  const token = await getAccessToken()
  const quotaProject = getQuotaProject()
  
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  }
  
  if (quotaProject) {
    headers["x-goog-user-project"] = quotaProject
  }
  
  const response = await fetch(`https://www.googleapis.com/calendar/v3${endpoint}`, {
    ...options,
    headers: {
      ...headers,
      ...options.headers,
    },
  })
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Google Calendar API error (${response.status}): ${error}`)
  }
  return response.json()
}

/**
 * Format event for display
 */
function formatEvent(event: any): string {
  const start = event.start?.dateTime || event.start?.date || "?"
  const end = event.end?.dateTime || event.end?.date || "?"
  const location = event.location ? `\n  Location: ${event.location}` : ""
  const description = event.description
    ? `\n  Description: ${event.description.slice(0, 100)}...`
    : ""
  const attendees = event.attendees
    ? `\n  Attendees: ${event.attendees.map((a: any) => a.email).join(", ")}`
    : ""

  return `- **${event.summary || "(No title)"}**
  ID: ${event.id}
  Start: ${start}
  End: ${end}${location}${description}${attendees}`
}

export const list_calendars = tool({
  description: `List all calendars accessible to the user.`,
  args: {},
  async execute() {
    const data = await calendarApi("/users/me/calendarList")

    const calendars = (data.items || [])
      .map(
        (c: any) =>
          `- **${c.summary}**\n  ID: ${c.id}\n  Access: ${c.accessRole}`
      )
      .join("\n\n")

    return `## Your Calendars\n\n${calendars}`
  },
})

export const list_events = tool({
  description: `List upcoming events from a calendar.`,
  args: {
    calendar_id: tool.schema
      .string()
      .optional()
      .default("primary")
      .describe("Calendar ID (default: primary)"),
    max_results: tool.schema
      .number()
      .optional()
      .default(10)
      .describe("Maximum events to return (default: 10)"),
    time_min: tool.schema
      .string()
      .optional()
      .describe("Start time filter (ISO 8601, default: now)"),
    time_max: tool.schema
      .string()
      .optional()
      .describe("End time filter (ISO 8601)"),
  },
  async execute(args) {
    const {
      calendar_id = "primary",
      max_results = 10,
      time_min,
      time_max,
    } = args

    const params = new URLSearchParams({
      maxResults: String(max_results),
      singleEvents: "true",
      orderBy: "startTime",
      timeMin: time_min || new Date().toISOString(),
    })
    if (time_max) {
      params.set("timeMax", time_max)
    }

    const data = await calendarApi(
      `/calendars/${encodeURIComponent(calendar_id)}/events?${params}`
    )

    if (!data.items || data.items.length === 0) {
      return "No upcoming events found."
    }

    const events = data.items.map(formatEvent).join("\n\n")

    return `## Upcoming Events\n\n${events}`
  },
})

export const get_event = tool({
  description: `Get details of a specific calendar event.`,
  args: {
    calendar_id: tool.schema
      .string()
      .optional()
      .default("primary")
      .describe("Calendar ID (default: primary)"),
    event_id: tool.schema.string().describe("Event ID"),
  },
  async execute(args) {
    const { calendar_id = "primary", event_id } = args

    const event = await calendarApi(
      `/calendars/${encodeURIComponent(calendar_id)}/events/${event_id}`
    )

    return `## Event: ${event.summary || "(No title)"}

**ID:** ${event.id}
**Status:** ${event.status}
**Start:** ${event.start?.dateTime || event.start?.date}
**End:** ${event.end?.dateTime || event.end?.date}
**Location:** ${event.location || "None"}
**Creator:** ${event.creator?.email || "Unknown"}
**Organizer:** ${event.organizer?.email || "Unknown"}

### Description
${event.description || "No description"}

### Attendees
${
  event.attendees
    ? event.attendees
        .map(
          (a: any) =>
            `- ${a.email} (${a.responseStatus || "unknown"}${a.organizer ? ", organizer" : ""})`
        )
        .join("\n")
    : "No attendees"
}

**Link:** ${event.htmlLink}`
  },
})

export const create_event = tool({
  description: `Create a new calendar event.`,
  args: {
    calendar_id: tool.schema
      .string()
      .optional()
      .default("primary")
      .describe("Calendar ID (default: primary)"),
    summary: tool.schema.string().describe("Event title"),
    start: tool.schema
      .string()
      .describe("Start time (ISO 8601, e.g., '2024-01-20T10:00:00-05:00')"),
    end: tool.schema
      .string()
      .describe("End time (ISO 8601)"),
    description: tool.schema.string().optional().describe("Event description"),
    location: tool.schema.string().optional().describe("Event location"),
    attendees: tool.schema
      .array(tool.schema.string())
      .optional()
      .describe("Email addresses of attendees"),
  },
  async execute(args) {
    const {
      calendar_id = "primary",
      summary,
      start,
      end,
      description,
      location,
      attendees,
    } = args

    const event: any = {
      summary,
      start: { dateTime: start },
      end: { dateTime: end },
    }
    if (description) event.description = description
    if (location) event.location = location
    if (attendees) {
      event.attendees = attendees.map((email) => ({ email }))
    }

    const result = await calendarApi(
      `/calendars/${encodeURIComponent(calendar_id)}/events`,
      {
        method: "POST",
        body: JSON.stringify(event),
      }
    )

    return `## Created Event

**Title:** ${result.summary}
**ID:** ${result.id}
**Start:** ${result.start?.dateTime || result.start?.date}
**End:** ${result.end?.dateTime || result.end?.date}
**Link:** ${result.htmlLink}`
  },
})

export const update_event = tool({
  description: `Update an existing calendar event.`,
  args: {
    calendar_id: tool.schema
      .string()
      .optional()
      .default("primary")
      .describe("Calendar ID (default: primary)"),
    event_id: tool.schema.string().describe("Event ID to update"),
    summary: tool.schema.string().optional().describe("New title"),
    start: tool.schema.string().optional().describe("New start time (ISO 8601)"),
    end: tool.schema.string().optional().describe("New end time (ISO 8601)"),
    description: tool.schema.string().optional().describe("New description"),
    location: tool.schema.string().optional().describe("New location"),
  },
  async execute(args) {
    const {
      calendar_id = "primary",
      event_id,
      summary,
      start,
      end,
      description,
      location,
    } = args

    // Get existing event first
    const existing = await calendarApi(
      `/calendars/${encodeURIComponent(calendar_id)}/events/${event_id}`
    )

    // Merge updates
    const updated: any = { ...existing }
    if (summary) updated.summary = summary
    if (start) updated.start = { dateTime: start }
    if (end) updated.end = { dateTime: end }
    if (description !== undefined) updated.description = description
    if (location !== undefined) updated.location = location

    const result = await calendarApi(
      `/calendars/${encodeURIComponent(calendar_id)}/events/${event_id}`,
      {
        method: "PUT",
        body: JSON.stringify(updated),
      }
    )

    return `Updated event: ${result.summary} (${result.id})`
  },
})

export const delete_event = tool({
  description: `Delete a calendar event.`,
  args: {
    calendar_id: tool.schema
      .string()
      .optional()
      .default("primary")
      .describe("Calendar ID (default: primary)"),
    event_id: tool.schema.string().describe("Event ID to delete"),
  },
  async execute(args) {
    const { calendar_id = "primary", event_id } = args

    const token = await getAccessToken()
    const response = await fetch(
      `https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(calendar_id)}/events/${event_id}`,
      {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      }
    )

    if (!response.ok && response.status !== 204) {
      throw new Error(`Failed to delete event: ${response.status}`)
    }

    return `Deleted event: ${event_id}`
  },
})

export const search_events = tool({
  description: `Search for events by text query.`,
  args: {
    calendar_id: tool.schema
      .string()
      .optional()
      .default("primary")
      .describe("Calendar ID (default: primary)"),
    query: tool.schema.string().describe("Search query"),
    max_results: tool.schema
      .number()
      .optional()
      .default(10)
      .describe("Maximum results (default: 10)"),
  },
  async execute(args) {
    const { calendar_id = "primary", query, max_results = 10 } = args

    const params = new URLSearchParams({
      q: query,
      maxResults: String(max_results),
      singleEvents: "true",
      orderBy: "startTime",
      timeMin: new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString(), // Past year
    })

    const data = await calendarApi(
      `/calendars/${encodeURIComponent(calendar_id)}/events?${params}`
    )

    if (!data.items || data.items.length === 0) {
      return `No events found matching: ${query}`
    }

    const events = data.items.map(formatEvent).join("\n\n")

    return `## Search results for: ${query}\n\n${events}`
  },
})
