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
 * Make authenticated request to Google Slides API
 */
async function slidesApi(endpoint: string, options: RequestInit = {}): Promise<any> {
  const token = await getAccessToken()
  const response = await fetch(`https://slides.googleapis.com${endpoint}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...options.headers,
    },
  })
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Google Slides API error (${response.status}): ${error}`)
  }
  return response.json()
}

/**
 * Extract text from a page element
 */
function extractTextFromElement(element: any): string {
  if (element.shape?.text?.textElements) {
    return element.shape.text.textElements
      .filter((te: any) => te.textRun)
      .map((te: any) => te.textRun.content)
      .join("")
  }
  if (element.table) {
    const rows: string[] = []
    for (const row of element.table.tableRows || []) {
      const cells = (row.tableCells || [])
        .map((cell: any) => {
          const text = cell.text?.textElements
            ?.filter((te: any) => te.textRun)
            .map((te: any) => te.textRun.content.trim())
            .join("")
          return text || ""
        })
        .join(" | ")
      rows.push(cells)
    }
    return rows.join("\n")
  }
  return ""
}

export const read = tool({
  description: `Read the contents of a Google Slides presentation.
  
Returns text content from all slides.`,
  args: {
    presentation_id: tool.schema.string().describe("The presentation ID"),
  },
  async execute(args) {
    const { presentation_id } = args

    const pres = await slidesApi(`/v1/presentations/${presentation_id}`)

    const slides: string[] = [`## ${pres.title}`, ""]

    for (let i = 0; i < pres.slides.length; i++) {
      const slide = pres.slides[i]
      slides.push(`### Slide ${i + 1}`)
      slides.push("")

      for (const element of slide.pageElements || []) {
        const text = extractTextFromElement(element)
        if (text.trim()) {
          slides.push(text.trim())
        }
      }
      slides.push("")
    }

    return slides.join("\n")
  },
})

export const get_info = tool({
  description: `Get information about a Google Slides presentation.`,
  args: {
    presentation_id: tool.schema.string().describe("The presentation ID"),
  },
  async execute(args) {
    const { presentation_id } = args

    const pres = await slidesApi(`/v1/presentations/${presentation_id}`)

    const slideInfo = pres.slides
      .map((s: any, i: number) => {
        // Try to get title from first text element
        const titleElem = s.pageElements?.find(
          (e: any) =>
            e.shape?.placeholder?.type === "TITLE" ||
            e.shape?.placeholder?.type === "CENTERED_TITLE"
        )
        const title = titleElem
          ? extractTextFromElement(titleElem).trim().slice(0, 50)
          : "Untitled"
        return `- Slide ${i + 1}: ${title}`
      })
      .join("\n")

    return `## Presentation: ${pres.title}

**ID:** ${presentation_id}
**URL:** https://docs.google.com/presentation/d/${presentation_id}
**Slides:** ${pres.slides.length}
**Size:** ${pres.pageSize?.width?.magnitude || "?"} x ${pres.pageSize?.height?.magnitude || "?"} ${pres.pageSize?.width?.unit || ""}

### Slides:
${slideInfo}`
  },
})

export const create = tool({
  description: `Create a new Google Slides presentation.`,
  args: {
    title: tool.schema.string().describe("Presentation title"),
  },
  async execute(args) {
    const { title } = args

    const result = await slidesApi("/v1/presentations", {
      method: "POST",
      body: JSON.stringify({ title }),
    })

    return `## Created Presentation

**Title:** ${result.title}
**ID:** ${result.presentationId}
**URL:** https://docs.google.com/presentation/d/${result.presentationId}`
  },
})

export const add_slide = tool({
  description: `Add a new slide to a presentation.`,
  args: {
    presentation_id: tool.schema.string().describe("The presentation ID"),
    layout: tool.schema
      .enum([
        "BLANK",
        "TITLE",
        "TITLE_AND_BODY",
        "TITLE_AND_TWO_COLUMNS",
        "TITLE_ONLY",
        "SECTION_HEADER",
        "CAPTION_ONLY",
        "BIG_NUMBER",
      ])
      .optional()
      .default("TITLE_AND_BODY")
      .describe("Slide layout (default: TITLE_AND_BODY)"),
    insert_at: tool.schema
      .number()
      .optional()
      .describe("Position to insert (0-based, default: end)"),
  },
  async execute(args) {
    const { presentation_id, layout = "TITLE_AND_BODY", insert_at } = args

    const requests: any[] = [
      {
        createSlide: {
          insertionIndex: insert_at,
          slideLayoutReference: {
            predefinedLayout: layout,
          },
        },
      },
    ]

    const result = await slidesApi(
      `/v1/presentations/${presentation_id}:batchUpdate`,
      {
        method: "POST",
        body: JSON.stringify({ requests }),
      }
    )

    const slideId = result.replies?.[0]?.createSlide?.objectId

    return `Created new slide with layout: ${layout}\nSlide ID: ${slideId}`
  },
})

export const update_text = tool({
  description: `Update text in a specific shape or placeholder on a slide.`,
  args: {
    presentation_id: tool.schema.string().describe("The presentation ID"),
    object_id: tool.schema
      .string()
      .describe("The shape/placeholder object ID to update"),
    text: tool.schema.string().describe("New text content"),
  },
  async execute(args) {
    const { presentation_id, object_id, text } = args

    const requests = [
      {
        deleteText: {
          objectId: object_id,
          textRange: { type: "ALL" },
        },
      },
      {
        insertText: {
          objectId: object_id,
          insertionIndex: 0,
          text: text,
        },
      },
    ]

    await slidesApi(`/v1/presentations/${presentation_id}:batchUpdate`, {
      method: "POST",
      body: JSON.stringify({ requests }),
    })

    return `Updated text in object: ${object_id}`
  },
})

export const get_slide_elements = tool({
  description: `Get all elements on a specific slide with their IDs.`,
  args: {
    presentation_id: tool.schema.string().describe("The presentation ID"),
    slide_index: tool.schema
      .number()
      .describe("Slide index (0-based)"),
  },
  async execute(args) {
    const { presentation_id, slide_index } = args

    const pres = await slidesApi(`/v1/presentations/${presentation_id}`)

    if (slide_index >= pres.slides.length) {
      throw new Error(
        `Slide index ${slide_index} out of range (${pres.slides.length} slides)`
      )
    }

    const slide = pres.slides[slide_index]
    const elements = (slide.pageElements || []).map((e: any) => {
      const type = e.shape
        ? `Shape (${e.shape.shapeType})`
        : e.table
          ? "Table"
          : e.image
            ? "Image"
            : "Unknown"
      const placeholder = e.shape?.placeholder?.type || ""
      const text = extractTextFromElement(e).trim().slice(0, 50)
      return `- **${e.objectId}**: ${type}${placeholder ? ` [${placeholder}]` : ""}\n  Text: "${text || "(empty)"}"`
    })

    return `## Slide ${slide_index + 1} Elements

${elements.join("\n\n")}`
  },
})
