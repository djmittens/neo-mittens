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
 * Make authenticated request to Google Sheets API
 */
async function sheetsApi(endpoint: string, options: RequestInit = {}): Promise<any> {
  const token = await getAccessToken()
  const quotaProject = getQuotaProject()
  
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  }
  
  if (quotaProject) {
    headers["x-goog-user-project"] = quotaProject
  }
  
  const response = await fetch(`https://sheets.googleapis.com${endpoint}`, {
    ...options,
    headers: {
      ...headers,
      ...options.headers,
    },
  })
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Google Sheets API error (${response.status}): ${error}`)
  }
  return response.json()
}

export const read = tool({
  description: `Read data from a Google Sheet.
  
Returns cell values from a specified range. Use A1 notation for range.`,
  args: {
    spreadsheet_id: tool.schema.string().describe("The spreadsheet ID"),
    range: tool.schema
      .string()
      .optional()
      .default("A1:Z100")
      .describe("A1 notation range (e.g., 'Sheet1!A1:D10', default: 'A1:Z100')"),
  },
  async execute(args) {
    const { spreadsheet_id, range = "A1:Z100" } = args

    const data = await sheetsApi(
      `/v4/spreadsheets/${spreadsheet_id}/values/${encodeURIComponent(range)}`
    )

    if (!data.values || data.values.length === 0) {
      return `No data found in range: ${range}`
    }

    // Format as markdown table
    const rows = data.values as string[][]
    const header = rows[0]
    const headerRow = "| " + header.join(" | ") + " |"
    const separator = "| " + header.map(() => "---").join(" | ") + " |"
    const dataRows = rows
      .slice(1)
      .map((row) => "| " + row.join(" | ") + " |")
      .join("\n")

    return `## Sheet Data: ${range}\n\n${headerRow}\n${separator}\n${dataRows}`
  },
})

export const get_info = tool({
  description: `Get information about a Google Sheet including all sheet names.`,
  args: {
    spreadsheet_id: tool.schema.string().describe("The spreadsheet ID"),
  },
  async execute(args) {
    const { spreadsheet_id } = args

    const data = await sheetsApi(
      `/v4/spreadsheets/${spreadsheet_id}?fields=properties,sheets.properties`
    )

    const sheets = data.sheets
      .map(
        (s: any) =>
          `- **${s.properties.title}** (ID: ${s.properties.sheetId}, ${s.properties.gridProperties.rowCount} rows x ${s.properties.gridProperties.columnCount} cols)`
      )
      .join("\n")

    return `## Spreadsheet: ${data.properties.title}

**ID:** ${spreadsheet_id}
**URL:** https://docs.google.com/spreadsheets/d/${spreadsheet_id}

### Sheets:
${sheets}`
  },
})

export const write = tool({
  description: `Write data to a Google Sheet.
  
Writes values to a specified range. Data is provided as a 2D array.`,
  args: {
    spreadsheet_id: tool.schema.string().describe("The spreadsheet ID"),
    range: tool.schema
      .string()
      .describe("A1 notation range to write to (e.g., 'Sheet1!A1')"),
    values: tool.schema
      .array(tool.schema.array(tool.schema.string()))
      .describe("2D array of values to write"),
  },
  async execute(args) {
    const { spreadsheet_id, range, values } = args

    const result = await sheetsApi(
      `/v4/spreadsheets/${spreadsheet_id}/values/${encodeURIComponent(range)}?valueInputOption=USER_ENTERED`,
      {
        method: "PUT",
        body: JSON.stringify({ values }),
      }
    )

    return `Updated ${result.updatedCells} cells in range: ${result.updatedRange}`
  },
})

export const append_rows = tool({
  description: `Append rows to a Google Sheet.
  
Appends data after the last row with data.`,
  args: {
    spreadsheet_id: tool.schema.string().describe("The spreadsheet ID"),
    sheet_name: tool.schema
      .string()
      .optional()
      .default("Sheet1")
      .describe("Sheet name (default: Sheet1)"),
    values: tool.schema
      .array(tool.schema.array(tool.schema.string()))
      .describe("2D array of rows to append"),
  },
  async execute(args) {
    const { spreadsheet_id, sheet_name = "Sheet1", values } = args

    const range = `${sheet_name}!A:A`
    const result = await sheetsApi(
      `/v4/spreadsheets/${spreadsheet_id}/values/${encodeURIComponent(range)}:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS`,
      {
        method: "POST",
        body: JSON.stringify({ values }),
      }
    )

    return `Appended ${values.length} row(s) to ${result.updates.updatedRange}`
  },
})

export const create = tool({
  description: `Create a new Google Sheet.`,
  args: {
    title: tool.schema.string().describe("Spreadsheet title"),
    sheet_names: tool.schema
      .array(tool.schema.string())
      .optional()
      .describe("Sheet names to create (default: ['Sheet1'])"),
  },
  async execute(args) {
    const { title, sheet_names } = args

    const sheets = (sheet_names || ["Sheet1"]).map((name) => ({
      properties: { title: name },
    }))

    const result = await sheetsApi("/v4/spreadsheets", {
      method: "POST",
      body: JSON.stringify({
        properties: { title },
        sheets,
      }),
    })

    return `## Created Spreadsheet

**Title:** ${result.properties.title}
**ID:** ${result.spreadsheetId}
**URL:** ${result.spreadsheetUrl}`
  },
})

export const clear = tool({
  description: `Clear values from a range in a Google Sheet.`,
  args: {
    spreadsheet_id: tool.schema.string().describe("The spreadsheet ID"),
    range: tool.schema
      .string()
      .describe("A1 notation range to clear (e.g., 'Sheet1!A1:D10')"),
  },
  async execute(args) {
    const { spreadsheet_id, range } = args

    await sheetsApi(
      `/v4/spreadsheets/${spreadsheet_id}/values/${encodeURIComponent(range)}:clear`,
      {
        method: "POST",
        body: JSON.stringify({}),
      }
    )

    return `Cleared range: ${range}`
  },
})
