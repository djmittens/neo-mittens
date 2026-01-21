import { tool } from "@opencode-ai/plugin"
import { readFileSync, existsSync } from "fs"
import { homedir } from "os"
import { join } from "path"

// ============================================================
// STYLING CONFIGURATION (inspired by GenAI Secret Sauce)
// ============================================================

const COLORS = {
  // Headings
  HEADING_RED: '#980000',      // Red accent for H1/H2
  HEADING_DARK: '#444444',     // Dark text for headings
  CHARCOAL: '#221F1F',         // Body text
  DARK_GRAY: '#333333',        // Secondary text
  
  // Tables
  TABLE_HEADER: '#333333',     // Dark header background
  TABLE_HEADER_TEXT: '#FFFFFF', // White header text
  TABLE_BORDER: '#E8E8E8',     // Subtle borders
  TABLE_ALT_ROW: '#F9F9F9',    // Alternating row color
  
  // Links
  LINK_BLUE: '#1155CC',        // Standard link blue
}

const STYLES = {
  fonts: {
    primary: 'Google Sans Text',
    secondary: 'Montserrat',
    code: 'Roboto Mono',
  },
  sizes: {
    title: 26,
    h1: 22,
    h2: 20,
    h3: 18,
    h4: 16,
    h5: 14,
    body: 11,
  },
  spacing: {
    h1Before: 24,
    h1After: 12,
    h2Before: 18,
    h2After: 8,
    h3Before: 14,
    h3After: 6,
    paragraphAfter: 8,
  },
  // Heading prefixes for visual hierarchy
  prefixes: {
    h1: '┃',  // Vertical bar for H1
    h2: '→',  // Arrow for H2
  }
}

// ============================================================
// HELPER FUNCTIONS
// ============================================================

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

async function docsApi(endpoint: string, options: RequestInit = {}): Promise<any> {
  const token = await getAccessToken()
  const quotaProject = getQuotaProject()
  
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  }
  
  if (quotaProject) {
    headers["x-goog-user-project"] = quotaProject
  }
  
  const response = await fetch(`https://docs.googleapis.com${endpoint}`, {
    ...options,
    headers: {
      ...headers,
      ...options.headers,
    },
  })
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Google Docs API error (${response.status}): ${error}`)
  }
  return response.json()
}

function hexToRgb(hex: string): { red: number; green: number; blue: number } {
  const h = hex.replace("#", "")
  return {
    red: parseInt(h.slice(0, 2), 16) / 255,
    green: parseInt(h.slice(2, 4), 16) / 255,
    blue: parseInt(h.slice(4, 6), 16) / 255,
  }
}

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

// ============================================================
// BASIC TOOLS
// ============================================================

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

    const doc = await docsApi("/v1/documents", {
      method: "POST",
      body: JSON.stringify({ title }),
    })

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

    const doc = await docsApi(`/v1/documents/${document_id}`)
    const endIndex = doc.body?.content?.slice(-1)[0]?.endIndex || 1

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

// ============================================================
// PROFESSIONAL FORMATTING TOOLS
// ============================================================

export const format_document = tool({
  description: `Apply professional formatting to an entire Google Doc. This applies heading styles, colors, and proper typography throughout the document. Based on the GenAI Secret Sauce formatting patterns.`,
  args: {
    document_id: tool.schema.string().describe("The Google Doc ID"),
  },
  async execute(args) {
    const { document_id } = args

    const doc = await docsApi(`/v1/documents/${document_id}`)
    const content = doc.body?.content || []
    const requests: any[] = []

    // Find all paragraphs and their styles
    for (const element of content) {
      if (!element.paragraph) continue
      
      const style = element.paragraph.paragraphStyle?.namedStyleType
      const startIndex = element.startIndex
      const endIndex = element.endIndex
      
      if (!startIndex || !endIndex) continue

      // Format based on heading level
      if (style === "TITLE") {
        requests.push({
          updateTextStyle: {
            range: { startIndex, endIndex },
            textStyle: {
              fontSize: { magnitude: STYLES.sizes.title, unit: "PT" },
              weightedFontFamily: { fontFamily: STYLES.fonts.primary },
              bold: true,
              foregroundColor: { color: { rgbColor: hexToRgb(COLORS.HEADING_DARK) } },
            },
            fields: "fontSize,weightedFontFamily,bold,foregroundColor",
          },
        })
      } else if (style === "HEADING_1") {
        requests.push({
          updateTextStyle: {
            range: { startIndex, endIndex },
            textStyle: {
              fontSize: { magnitude: STYLES.sizes.h1, unit: "PT" },
              weightedFontFamily: { fontFamily: STYLES.fonts.primary },
              bold: true,
              foregroundColor: { color: { rgbColor: hexToRgb(COLORS.HEADING_RED) } },
            },
            fields: "fontSize,weightedFontFamily,bold,foregroundColor",
          },
        })
        requests.push({
          updateParagraphStyle: {
            range: { startIndex, endIndex },
            paragraphStyle: {
              spaceAbove: { magnitude: STYLES.spacing.h1Before, unit: "PT" },
              spaceBelow: { magnitude: STYLES.spacing.h1After, unit: "PT" },
            },
            fields: "spaceAbove,spaceBelow",
          },
        })
      } else if (style === "HEADING_2") {
        requests.push({
          updateTextStyle: {
            range: { startIndex, endIndex },
            textStyle: {
              fontSize: { magnitude: STYLES.sizes.h2, unit: "PT" },
              weightedFontFamily: { fontFamily: STYLES.fonts.primary },
              bold: true,
              foregroundColor: { color: { rgbColor: hexToRgb(COLORS.HEADING_RED) } },
            },
            fields: "fontSize,weightedFontFamily,bold,foregroundColor",
          },
        })
        requests.push({
          updateParagraphStyle: {
            range: { startIndex, endIndex },
            paragraphStyle: {
              spaceAbove: { magnitude: STYLES.spacing.h2Before, unit: "PT" },
              spaceBelow: { magnitude: STYLES.spacing.h2After, unit: "PT" },
            },
            fields: "spaceAbove,spaceBelow",
          },
        })
      } else if (style === "HEADING_3") {
        requests.push({
          updateTextStyle: {
            range: { startIndex, endIndex },
            textStyle: {
              fontSize: { magnitude: STYLES.sizes.h3, unit: "PT" },
              weightedFontFamily: { fontFamily: STYLES.fonts.primary },
              bold: true,
              foregroundColor: { color: { rgbColor: hexToRgb(COLORS.HEADING_DARK) } },
            },
            fields: "fontSize,weightedFontFamily,bold,foregroundColor",
          },
        })
      } else if (style === "HEADING_4") {
        requests.push({
          updateTextStyle: {
            range: { startIndex, endIndex },
            textStyle: {
              fontSize: { magnitude: STYLES.sizes.h4, unit: "PT" },
              weightedFontFamily: { fontFamily: STYLES.fonts.secondary },
              foregroundColor: { color: { rgbColor: hexToRgb(COLORS.DARK_GRAY) } },
            },
            fields: "fontSize,weightedFontFamily,foregroundColor",
          },
        })
      } else if (style === "HEADING_5") {
        requests.push({
          updateTextStyle: {
            range: { startIndex, endIndex },
            textStyle: {
              fontSize: { magnitude: STYLES.sizes.h5, unit: "PT" },
              weightedFontFamily: { fontFamily: STYLES.fonts.primary },
              bold: true,
              foregroundColor: { color: { rgbColor: hexToRgb(COLORS.DARK_GRAY) } },
            },
            fields: "fontSize,weightedFontFamily,bold,foregroundColor",
          },
        })
      }
    }

    if (requests.length === 0) {
      return "No formattable content found in document."
    }

    await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
      method: "POST",
      body: JSON.stringify({ requests }),
    })

    return `Applied professional formatting to ${requests.length} elements in document.`
  },
})

export const apply_heading_style = tool({
  description: `Convert existing text to a heading style by finding it in the document.`,
  args: {
    document_id: tool.schema.string().describe("The Google Doc ID"),
    find_text: tool.schema.string().describe("Text to find and convert to heading"),
    level: tool.schema
      .enum(["1", "2", "3", "4", "5", "6"])
      .describe("Heading level (1-6)"),
  },
  async execute(args) {
    const { document_id, find_text, level } = args

    const doc = await docsApi(`/v1/documents/${document_id}`)
    const ranges: { start: number; end: number }[] = []
    
    for (const element of doc.body?.content || []) {
      if (element.paragraph) {
        let paragraphText = ""
        const paragraphStart = element.startIndex
        const paragraphEnd = element.endIndex
        
        for (const elem of element.paragraph.elements || []) {
          if (elem.textRun?.content) {
            paragraphText += elem.textRun.content
          }
        }
        
        if (paragraphText.includes(find_text)) {
          ranges.push({ start: paragraphStart, end: paragraphEnd })
        }
      }
    }

    if (ranges.length === 0) {
      return `Text "${find_text}" not found in document`
    }

    const requests = ranges.map((range) => ({
      updateParagraphStyle: {
        range: {
          startIndex: range.start,
          endIndex: range.end,
        },
        paragraphStyle: {
          namedStyleType: `HEADING_${level}`,
        },
        fields: "namedStyleType",
      },
    }))

    await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
      method: "POST",
      body: JSON.stringify({ requests }),
    })

    return `Applied H${level} style to ${ranges.length} paragraph(s) containing "${find_text}"`
  },
})

export const insert_table = tool({
  description: `Insert a professionally styled table into a Google Doc with dark header row and alternating row colors.`,
  args: {
    document_id: tool.schema.string().describe("The Google Doc ID"),
    rows: tool.schema.number().describe("Number of rows"),
    columns: tool.schema.number().describe("Number of columns"),
    data: tool.schema
      .string()
      .optional()
      .describe("Table data as JSON 2D array, e.g. [[\"Header1\",\"Header2\"],[\"Row1Col1\",\"Row1Col2\"]]"),
    index: tool.schema
      .number()
      .optional()
      .describe("Insert position (1-based index, default: end of document)"),
  },
  async execute(args) {
    const { document_id, rows, columns, data, index } = args

    const doc = await docsApi(`/v1/documents/${document_id}`)
    const insertIndex = index || (doc.body?.content?.slice(-1)[0]?.endIndex - 1) || 1

    // Create the table
    await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
      method: "POST",
      body: JSON.stringify({
        requests: [{
          insertTable: {
            rows,
            columns,
            location: { index: insertIndex },
          },
        }],
      }),
    })

    // If data provided, populate and style the table
    if (data) {
      const tableData = JSON.parse(data) as string[][]
      
      // Re-fetch doc to get table structure
      const updatedDoc = await docsApi(`/v1/documents/${document_id}`)
      
      // Find the table we just inserted
      let table: any = null
      for (const element of updatedDoc.body?.content || []) {
        if (element.table && element.startIndex >= insertIndex) {
          table = element
          break
        }
      }

      if (table) {
        const cellRequests: any[] = []
        const styleRequests: any[] = []
        
        for (let r = 0; r < Math.min(rows, tableData.length); r++) {
          for (let c = 0; c < Math.min(columns, tableData[r]?.length || 0); c++) {
            const cell = table.table.tableRows[r]?.tableCells[c]
            if (cell && tableData[r][c]) {
              const paragraph = cell.content?.[0]
              if (paragraph) {
                cellRequests.push({
                  insertText: {
                    location: { index: paragraph.startIndex },
                    text: tableData[r][c],
                  },
                })
                
                // Style header row (first row)
                if (r === 0) {
                  styleRequests.push({
                    updateTableCellStyle: {
                      tableRange: {
                        tableCellLocation: {
                          tableStartLocation: { index: table.startIndex },
                          rowIndex: r,
                          columnIndex: c,
                        },
                        rowSpan: 1,
                        columnSpan: 1,
                      },
                      tableCellStyle: {
                        backgroundColor: { color: { rgbColor: hexToRgb(COLORS.TABLE_HEADER) } },
                      },
                      fields: "backgroundColor",
                    },
                  })
                }
                // Alternating row colors
                else if (r % 2 === 0) {
                  styleRequests.push({
                    updateTableCellStyle: {
                      tableRange: {
                        tableCellLocation: {
                          tableStartLocation: { index: table.startIndex },
                          rowIndex: r,
                          columnIndex: c,
                        },
                        rowSpan: 1,
                        columnSpan: 1,
                      },
                      tableCellStyle: {
                        backgroundColor: { color: { rgbColor: hexToRgb(COLORS.TABLE_ALT_ROW) } },
                      },
                      fields: "backgroundColor",
                    },
                  })
                }
              }
            }
          }
        }

        if (cellRequests.length > 0) {
          // Insert text in reverse order to maintain indices
          await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
            method: "POST",
            body: JSON.stringify({ requests: cellRequests.reverse() }),
          })
        }

        if (styleRequests.length > 0) {
          await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
            method: "POST",
            body: JSON.stringify({ requests: styleRequests }),
          })
        }
      }
    }

    return `Inserted ${rows}x${columns} professionally styled table at index ${insertIndex}`
  },
})

export const format_text = tool({
  description: `Apply formatting to text in a Google Doc by finding and styling it.`,
  args: {
    document_id: tool.schema.string().describe("The Google Doc ID"),
    find_text: tool.schema.string().describe("Text to find and format"),
    bold: tool.schema.boolean().optional().describe("Make text bold"),
    italic: tool.schema.boolean().optional().describe("Make text italic"),
    underline: tool.schema.boolean().optional().describe("Underline text"),
    font_size: tool.schema.number().optional().describe("Font size in points"),
    foreground_color: tool.schema
      .string()
      .optional()
      .describe("Text color as hex (e.g. #FF0000 for red)"),
    background_color: tool.schema
      .string()
      .optional()
      .describe("Background/highlight color as hex"),
  },
  async execute(args) {
    const { document_id, find_text, bold, italic, underline, font_size, foreground_color, background_color } = args

    const doc = await docsApi(`/v1/documents/${document_id}`)
    const ranges: { start: number; end: number }[] = []
    
    for (const element of doc.body?.content || []) {
      if (element.paragraph) {
        for (const elem of element.paragraph.elements || []) {
          if (elem.textRun?.content) {
            let idx = 0
            const content = elem.textRun.content
            const startIdx = elem.startIndex
            
            while ((idx = content.indexOf(find_text, idx)) !== -1) {
              ranges.push({
                start: startIdx + idx,
                end: startIdx + idx + find_text.length,
              })
              idx += find_text.length
            }
          }
        }
      }
    }

    if (ranges.length === 0) {
      return `Text "${find_text}" not found in document`
    }

    const textStyle: any = {}
    const fields: string[] = []

    if (bold !== undefined) {
      textStyle.bold = bold
      fields.push("bold")
    }
    if (italic !== undefined) {
      textStyle.italic = italic
      fields.push("italic")
    }
    if (underline !== undefined) {
      textStyle.underline = underline
      fields.push("underline")
    }
    if (font_size !== undefined) {
      textStyle.fontSize = { magnitude: font_size, unit: "PT" }
      fields.push("fontSize")
    }
    if (foreground_color) {
      textStyle.foregroundColor = { color: { rgbColor: hexToRgb(foreground_color) } }
      fields.push("foregroundColor")
    }
    if (background_color) {
      textStyle.backgroundColor = { color: { rgbColor: hexToRgb(background_color) } }
      fields.push("backgroundColor")
    }

    const requests = ranges.map((range) => ({
      updateTextStyle: {
        range: {
          startIndex: range.start,
          endIndex: range.end,
        },
        textStyle,
        fields: fields.join(","),
      },
    }))

    await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
      method: "POST",
      body: JSON.stringify({ requests }),
    })

    return `Formatted ${ranges.length} occurrence(s) of "${find_text}"`
  },
})

export const batch_format = tool({
  description: `Apply multiple formatting operations in a single batch. Efficient for applying many styles at once.`,
  args: {
    document_id: tool.schema.string().describe("The Google Doc ID"),
    operations: tool.schema.string().describe(`JSON array of operations. Each operation has:
- type: "heading" | "text_style" | "paragraph_style"
- startIndex: number
- endIndex: number
- For heading: level (1-6)
- For text_style: bold, italic, underline, fontSize, foregroundColor (hex)
- For paragraph_style: spaceAbove, spaceBelow (in PT)

Example: [{"type":"heading","startIndex":2,"endIndex":50,"level":1},{"type":"text_style","startIndex":100,"endIndex":150,"bold":true}]`),
  },
  async execute(args) {
    const { document_id, operations } = args
    
    const ops = JSON.parse(operations) as any[]
    const requests: any[] = []
    
    for (const op of ops) {
      if (op.type === "heading") {
        requests.push({
          updateParagraphStyle: {
            range: { startIndex: op.startIndex, endIndex: op.endIndex },
            paragraphStyle: { namedStyleType: `HEADING_${op.level}` },
            fields: "namedStyleType",
          },
        })
      } else if (op.type === "text_style") {
        const textStyle: any = {}
        const fields: string[] = []
        
        if (op.bold !== undefined) { textStyle.bold = op.bold; fields.push("bold") }
        if (op.italic !== undefined) { textStyle.italic = op.italic; fields.push("italic") }
        if (op.underline !== undefined) { textStyle.underline = op.underline; fields.push("underline") }
        if (op.fontSize) { textStyle.fontSize = { magnitude: op.fontSize, unit: "PT" }; fields.push("fontSize") }
        if (op.foregroundColor) { textStyle.foregroundColor = { color: { rgbColor: hexToRgb(op.foregroundColor) } }; fields.push("foregroundColor") }
        
        requests.push({
          updateTextStyle: {
            range: { startIndex: op.startIndex, endIndex: op.endIndex },
            textStyle,
            fields: fields.join(","),
          },
        })
      } else if (op.type === "paragraph_style") {
        const paragraphStyle: any = {}
        const fields: string[] = []
        
        if (op.spaceAbove !== undefined) { paragraphStyle.spaceAbove = { magnitude: op.spaceAbove, unit: "PT" }; fields.push("spaceAbove") }
        if (op.spaceBelow !== undefined) { paragraphStyle.spaceBelow = { magnitude: op.spaceBelow, unit: "PT" }; fields.push("spaceBelow") }
        
        requests.push({
          updateParagraphStyle: {
            range: { startIndex: op.startIndex, endIndex: op.endIndex },
            paragraphStyle,
            fields: fields.join(","),
          },
        })
      }
    }

    if (requests.length === 0) {
      return "No valid operations to apply."
    }

    await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
      method: "POST",
      body: JSON.stringify({ requests }),
    })

    return `Applied ${requests.length} formatting operations to document.`
  },
})

export const insert_heading = tool({
  description: `Insert a styled heading at a specific position in a Google Doc.`,
  args: {
    document_id: tool.schema.string().describe("The Google Doc ID"),
    text: tool.schema.string().describe("Heading text"),
    level: tool.schema
      .enum(["1", "2", "3", "4", "5", "6"])
      .describe("Heading level (1-6)"),
    index: tool.schema
      .number()
      .optional()
      .describe("Insert position (1-based index, default: end of document)"),
  },
  async execute(args) {
    const { document_id, text, level, index } = args

    const doc = await docsApi(`/v1/documents/${document_id}`)
    const insertIndex = index || (doc.body?.content?.slice(-1)[0]?.endIndex - 1) || 1

    const headingText = text + "\n"
    const endIndex = insertIndex + headingText.length

    await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
      method: "POST",
      body: JSON.stringify({
        requests: [
          {
            insertText: {
              location: { index: insertIndex },
              text: headingText,
            },
          },
          {
            updateParagraphStyle: {
              range: {
                startIndex: insertIndex,
                endIndex: endIndex,
              },
              paragraphStyle: {
                namedStyleType: `HEADING_${level}`,
              },
              fields: "namedStyleType",
            },
          },
        ],
      }),
    })

    return `Inserted H${level} heading "${text}" at index ${insertIndex}`
  },
})

export const clear_document = tool({
  description: `Clear all content from a Google Doc, leaving it empty for fresh content.`,
  args: {
    document_id: tool.schema.string().describe("The Google Doc ID"),
  },
  async execute(args) {
    const { document_id } = args

    const doc = await docsApi(`/v1/documents/${document_id}`)
    const content = doc.body?.content || []
    
    // Find the range of all content (skip first structural element)
    let endIndex = 1
    for (const element of content) {
      if (element.endIndex && element.endIndex > endIndex) {
        endIndex = element.endIndex
      }
    }
    
    if (endIndex <= 2) {
      return "Document is already empty."
    }

    await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
      method: "POST",
      body: JSON.stringify({
        requests: [
          {
            deleteContentRange: {
              range: {
                startIndex: 1,
                endIndex: endIndex - 1,
              },
            },
          },
        ],
      }),
    })

    return `Cleared document "${doc.title}"`
  },
})

export const write_formatted_section = tool({
  description: `Write a formatted section to a Google Doc. This tool writes content and applies formatting in one operation. Perfect for building professionally formatted documents section by section.`,
  args: {
    document_id: tool.schema.string().describe("The Google Doc ID"),
    content: tool.schema.string().describe(`JSON array of content blocks. Each block has:
- type: "title" | "h1" | "h2" | "h3" | "h4" | "text" | "bullet" | "code"
- text: The content text
- bold: (optional) Make text bold (for type: "text")

Example:
[
  {"type": "h1", "text": "Section Title"},
  {"type": "text", "text": "Some paragraph text here."},
  {"type": "bullet", "text": "First bullet point"},
  {"type": "bullet", "text": "Second bullet point"},
  {"type": "h2", "text": "Subsection"},
  {"type": "code", "text": "code example here"}
]`),
  },
  async execute(args) {
    const { document_id, content } = args
    
    const blocks = JSON.parse(content) as Array<{
      type: "title" | "h1" | "h2" | "h3" | "h4" | "text" | "bullet" | "code"
      text: string
      bold?: boolean
    }>
    
    // Get current document end
    const doc = await docsApi(`/v1/documents/${document_id}`)
    let insertIndex = (doc.body?.content?.slice(-1)[0]?.endIndex || 2) - 1
    
    // Build all text first, then apply formatting
    const insertRequests: any[] = []
    const formatRequests: any[] = []
    
    // Track positions for formatting (we insert in reverse order so positions are stable)
    const positions: Array<{
      start: number
      end: number
      type: string
      bold?: boolean
    }> = []
    
    // Calculate positions
    let currentPos = insertIndex
    for (const block of blocks) {
      const text = block.text + "\n"
      positions.push({
        start: currentPos,
        end: currentPos + text.length,
        type: block.type,
        bold: block.bold,
      })
      currentPos += text.length
    }
    
    // Build full text to insert
    const fullText = blocks.map(b => b.text + "\n").join("")
    
    // Insert all text at once
    insertRequests.push({
      insertText: {
        location: { index: insertIndex },
        text: fullText,
      },
    })
    
    // Build formatting requests
    for (const pos of positions) {
      const namedStyle = 
        pos.type === "title" ? "TITLE" :
        pos.type === "h1" ? "HEADING_1" :
        pos.type === "h2" ? "HEADING_2" :
        pos.type === "h3" ? "HEADING_3" :
        pos.type === "h4" ? "HEADING_4" :
        "NORMAL_TEXT"
      
      // Apply paragraph style
      formatRequests.push({
        updateParagraphStyle: {
          range: { startIndex: pos.start, endIndex: pos.end },
          paragraphStyle: { namedStyleType: namedStyle },
          fields: "namedStyleType",
        },
      })
      
      // Apply heading colors
      if (pos.type === "h1" || pos.type === "h2") {
        formatRequests.push({
          updateTextStyle: {
            range: { startIndex: pos.start, endIndex: pos.end - 1 },
            textStyle: {
              foregroundColor: { color: { rgbColor: hexToRgb(COLORS.HEADING_RED) } },
              bold: true,
            },
            fields: "foregroundColor,bold",
          },
        })
      } else if (pos.type === "h3" || pos.type === "h4") {
        formatRequests.push({
          updateTextStyle: {
            range: { startIndex: pos.start, endIndex: pos.end - 1 },
            textStyle: {
              foregroundColor: { color: { rgbColor: hexToRgb(COLORS.HEADING_DARK) } },
              bold: true,
            },
            fields: "foregroundColor,bold",
          },
        })
      } else if (pos.type === "bullet") {
        formatRequests.push({
          createParagraphBullets: {
            range: { startIndex: pos.start, endIndex: pos.end },
            bulletPreset: "BULLET_DISC_CIRCLE_SQUARE",
          },
        })
      } else if (pos.type === "code") {
        formatRequests.push({
          updateTextStyle: {
            range: { startIndex: pos.start, endIndex: pos.end - 1 },
            textStyle: {
              weightedFontFamily: { fontFamily: STYLES.fonts.code },
              fontSize: { magnitude: 10, unit: "PT" },
              backgroundColor: { color: { rgbColor: hexToRgb("#F5F5F5") } },
            },
            fields: "weightedFontFamily,fontSize,backgroundColor",
          },
        })
      } else if (pos.type === "text" && pos.bold) {
        formatRequests.push({
          updateTextStyle: {
            range: { startIndex: pos.start, endIndex: pos.end - 1 },
            textStyle: { bold: true },
            fields: "bold",
          },
        })
      }
    }
    
    // Execute insert first, then formatting
    await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
      method: "POST",
      body: JSON.stringify({ requests: insertRequests }),
    })
    
    if (formatRequests.length > 0) {
      await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
        method: "POST",
        body: JSON.stringify({ requests: formatRequests }),
      })
    }
    
    return `Wrote ${blocks.length} formatted blocks to document`
  },
})

export const insert_styled_table = tool({
  description: `Insert a professionally styled table with dark header and clean formatting.`,
  args: {
    document_id: tool.schema.string().describe("The Google Doc ID"),
    headers: tool.schema.string().describe("Comma-separated header labels (e.g. 'Name,Type,Description')"),
    rows: tool.schema.string().describe(`JSON array of rows, each row is an array of cell values.
Example: [["INT64","Number type","Primary key"],["STRING","Text type","Names and labels"]]`),
  },
  async execute(args) {
    const { document_id, headers, rows } = args
    
    const headerCells = headers.split(",").map(h => h.trim())
    const dataRows = JSON.parse(rows) as string[][]
    const numColumns = headerCells.length
    const numRows = dataRows.length + 1 // +1 for header
    
    // Get current document end
    const doc = await docsApi(`/v1/documents/${document_id}`)
    const insertIndex = (doc.body?.content?.slice(-1)[0]?.endIndex || 2) - 1
    
    // Create the table
    await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
      method: "POST",
      body: JSON.stringify({
        requests: [{
          insertTable: {
            rows: numRows,
            columns: numColumns,
            location: { index: insertIndex },
          },
        }],
      }),
    })
    
    // Re-fetch doc to get table structure
    const updatedDoc = await docsApi(`/v1/documents/${document_id}`)
    
    // Find the table we just inserted
    let table: any = null
    for (const element of updatedDoc.body?.content || []) {
      if (element.table && element.startIndex >= insertIndex) {
        table = element
        break
      }
    }
    
    if (!table) {
      return "Table created but could not find it for styling"
    }
    
    const textRequests: any[] = []
    const styleRequests: any[] = []
    
    // Combine headers and data rows
    const allRows = [headerCells, ...dataRows]
    
    for (let r = 0; r < numRows; r++) {
      for (let c = 0; c < numColumns; c++) {
        const cell = table.table.tableRows[r]?.tableCells[c]
        const cellValue = allRows[r]?.[c] || ""
        
        if (cell && cellValue) {
          const paragraph = cell.content?.[0]
          if (paragraph) {
            textRequests.push({
              insertText: {
                location: { index: paragraph.startIndex },
                text: cellValue,
              },
            })
          }
        }
        
        // Style header row
        if (r === 0) {
          styleRequests.push({
            updateTableCellStyle: {
              tableRange: {
                tableCellLocation: {
                  tableStartLocation: { index: table.startIndex },
                  rowIndex: r,
                  columnIndex: c,
                },
                rowSpan: 1,
                columnSpan: 1,
              },
              tableCellStyle: {
                backgroundColor: { color: { rgbColor: hexToRgb(COLORS.TABLE_HEADER) } },
              },
              fields: "backgroundColor",
            },
          })
        }
        // Alternating row colors for data rows
        else if (r % 2 === 0) {
          styleRequests.push({
            updateTableCellStyle: {
              tableRange: {
                tableCellLocation: {
                  tableStartLocation: { index: table.startIndex },
                  rowIndex: r,
                  columnIndex: c,
                },
                rowSpan: 1,
                columnSpan: 1,
              },
              tableCellStyle: {
                backgroundColor: { color: { rgbColor: hexToRgb(COLORS.TABLE_ALT_ROW) } },
              },
              fields: "backgroundColor",
            },
          })
        }
      }
    }
    
    // Insert text in reverse order to maintain indices
    if (textRequests.length > 0) {
      await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
        method: "POST",
        body: JSON.stringify({ requests: textRequests.reverse() }),
      })
    }
    
    // Apply cell styling
    if (styleRequests.length > 0) {
      await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
        method: "POST",
        body: JSON.stringify({ requests: styleRequests }),
      })
    }
    
    // Style header text (white, bold)
    const refreshedDoc = await docsApi(`/v1/documents/${document_id}`)
    let refreshedTable: any = null
    for (const element of refreshedDoc.body?.content || []) {
      if (element.table && element.startIndex >= insertIndex) {
        refreshedTable = element
        break
      }
    }
    
    if (refreshedTable) {
      const headerTextStyles: any[] = []
      for (let c = 0; c < numColumns; c++) {
        const cell = refreshedTable.table.tableRows[0]?.tableCells[c]
        if (cell?.content?.[0]) {
          const start = cell.content[0].startIndex
          const end = cell.content[0].endIndex - 1
          if (start < end) {
            headerTextStyles.push({
              updateTextStyle: {
                range: { startIndex: start, endIndex: end },
                textStyle: {
                  foregroundColor: { color: { rgbColor: hexToRgb(COLORS.TABLE_HEADER_TEXT) } },
                  bold: true,
                },
                fields: "foregroundColor,bold",
              },
            })
          }
        }
      }
      
      if (headerTextStyles.length > 0) {
        await docsApi(`/v1/documents/${document_id}:batchUpdate`, {
          method: "POST",
          body: JSON.stringify({ requests: headerTextStyles }),
        })
      }
    }
    
    return `Inserted ${numRows}x${numColumns} styled table with headers: ${headers}`
  },
})
