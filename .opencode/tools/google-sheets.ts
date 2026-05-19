import { tool } from "@opencode-ai/plugin"
import { googleApi } from "./google-auth"

const SHEETS_BASE = "https://sheets.googleapis.com"

async function sheetsApi(endpoint: string, options: RequestInit = {}): Promise<any> {
  return googleApi(SHEETS_BASE, "Google Sheets", endpoint, options)
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

/**
 * Convert markdown-style links `[text](url)` to Sheets HYPERLINK formulas.
 * Plain strings pass through unchanged.
 */
function convertLinks(values: string[][]): string[][] {
  const linkPattern = /^\[([^\]]+)\]\(([^)]+)\)$/
  return values.map((row) =>
    row.map((cell) => {
      const match = cell.match(linkPattern)
      if (match) {
        const [, text, url] = match
        return `=HYPERLINK("${url}","${text}")`
      }
      return cell
    })
  )
}

export const write = tool({
  description: `Write data to a Google Sheet.
  
Writes values to a specified range. Data is provided as a 2D array.
Supports markdown-style links: use [text](url) to create clickable hyperlinks.`,
  args: {
    spreadsheet_id: tool.schema.string().describe("The spreadsheet ID"),
    range: tool.schema
      .string()
      .describe("A1 notation range to write to (e.g., 'Sheet1!A1')"),
    values: tool.schema
      .array(tool.schema.array(tool.schema.string()))
      .describe("2D array of values to write. Use [text](url) for hyperlinks."),
  },
  async execute(args) {
    const { spreadsheet_id, range, values } = args

    const result = await sheetsApi(
      `/v4/spreadsheets/${spreadsheet_id}/values/${encodeURIComponent(range)}?valueInputOption=USER_ENTERED`,
      {
        method: "PUT",
        body: JSON.stringify({ values: convertLinks(values) }),
      }
    )

    return `Updated ${result.updatedCells} cells in range: ${result.updatedRange}`
  },
})

export const append_rows = tool({
  description: `Append rows to a Google Sheet.
  
Appends data after the last row with data. Supports [text](url) for hyperlinks.`,
  args: {
    spreadsheet_id: tool.schema.string().describe("The spreadsheet ID"),
    sheet_name: tool.schema
      .string()
      .optional()
      .default("Sheet1")
      .describe("Sheet name (default: Sheet1)"),
    values: tool.schema
      .array(tool.schema.array(tool.schema.string()))
      .describe("2D array of rows to append. Use [text](url) for hyperlinks."),
  },
  async execute(args) {
    const { spreadsheet_id, sheet_name = "Sheet1", values } = args

    const range = `${sheet_name}!A:A`
    const result = await sheetsApi(
      `/v4/spreadsheets/${spreadsheet_id}/values/${encodeURIComponent(range)}:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS`,
      {
        method: "POST",
        body: JSON.stringify({ values: convertLinks(values) }),
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

export const insert_rows = tool({
  description: `Insert rows into a Google Sheet at a specific position, shifting existing rows down.
  
Unlike 'write' (which overwrites), this inserts new rows without clobbering existing data below.`,
  args: {
    spreadsheet_id: tool.schema.string().describe("The spreadsheet ID"),
    sheet_name: tool.schema
      .string()
      .optional()
      .default("Sheet1")
      .describe("Sheet name (default: Sheet1)"),
    row_index: tool.schema
      .number()
      .describe("0-based row index to insert at (e.g., 5 inserts before current row 6)"),
    values: tool.schema
      .array(tool.schema.array(tool.schema.string()))
      .describe("2D array of rows to insert"),
  },
  async execute(args) {
    const { spreadsheet_id, sheet_name = "Sheet1", row_index, values } = args

    // First, get the sheet ID from the sheet name
    const info = await sheetsApi(
      `/v4/spreadsheets/${spreadsheet_id}?fields=sheets.properties`
    )
    const sheet = info.sheets.find(
      (s: any) => s.properties.title === sheet_name
    )
    if (!sheet) {
      throw new Error(`Sheet '${sheet_name}' not found in spreadsheet`)
    }
    const sheetId = sheet.properties.sheetId

    // Insert blank rows
    await sheetsApi(`/v4/spreadsheets/${spreadsheet_id}:batchUpdate`, {
      method: "POST",
      body: JSON.stringify({
        requests: [
          {
            insertDimension: {
              range: {
                sheetId,
                dimension: "ROWS",
                startIndex: row_index,
                endIndex: row_index + values.length,
              },
              inheritFromBefore: row_index > 0,
            },
          },
        ],
      }),
    })

    // Write values into the new rows (1-based for A1 notation)
    const range = `${sheet_name}!A${row_index + 1}`
    const result = await sheetsApi(
      `/v4/spreadsheets/${spreadsheet_id}/values/${encodeURIComponent(range)}?valueInputOption=USER_ENTERED`,
      {
        method: "PUT",
        body: JSON.stringify({ values: convertLinks(values) }),
      }
    )

    return `Inserted ${values.length} row(s) at row ${row_index + 1} in ${result.updatedRange}`
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
