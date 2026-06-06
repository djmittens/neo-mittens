import { tool } from "@opencode-ai/plugin"
import { readFileSync, writeFileSync, unlinkSync, existsSync } from "fs"
import { join, basename, dirname } from "path"
import { deflateRawSync, inflateRawSync, deflateSync, inflateSync } from "zlib"

// ============================================================
// PNG chunk helpers for embedding/extracting draw.io XML
//
// draw.io PNG format (from pzl/drawio-read and draw.io source):
//   zTXt chunk key: "mxGraphModel"
//   zTXt value (after zlib inflate): <mxfile><diagram>PAYLOAD</diagram></mxfile>
//   PAYLOAD: base64( deflateRaw( encodeURIComponent(mxGraphModelXml) ) )
//
// deflateRaw = raw deflate with NO zlib header (wbits=-15)
// ============================================================

function crc32(buf: Buffer): number {
  let crc = 0xffffffff
  for (let i = 0; i < buf.length; i++) {
    crc ^= buf[i]
    for (let j = 0; j < 8; j++) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0)
    }
  }
  return (crc ^ 0xffffffff) >>> 0
}

function encodeDiagramPayload(xml: string): string {
  // mxGraphModel XML → URL-encode → raw deflate → base64
  const urlEncoded = encodeURIComponent(xml)
  const deflated = deflateRawSync(Buffer.from(urlEncoded, "utf-8"))
  return deflated.toString("base64")
}

function decodeDiagramPayload(payload: string): string {
  // base64 → raw inflate → URL-decode → mxGraphModel XML
  const deflated = Buffer.from(payload, "base64")
  const urlEncoded = inflateRawSync(deflated).toString("utf-8")
  return decodeURIComponent(urlEncoded)
}

function embedXmlInPng(pngPath: string, xml: string): void {
  const data = readFileSync(pngPath)

  // Build the mxfile wrapper with encoded diagram payload
  const payload = encodeDiagramPayload(xml)
  const mxfileXml = `<mxfile><diagram>${payload}</diagram></mxfile>`

  // Build zTXt chunk: key="mxGraphModel\0", compression=0, zlib-compressed mxfile XML
  const key = Buffer.from("mxGraphModel\0", "ascii")
  const compressionMethod = Buffer.from([0]) // zlib
  const compressed = deflateSync(Buffer.from(mxfileXml, "utf-8"))
  const chunkData = Buffer.concat([key, compressionMethod, compressed])

  const chunkType = Buffer.from("zTXt", "ascii")
  const lengthBuf = Buffer.alloc(4)
  lengthBuf.writeUInt32BE(chunkData.length, 0)

  const crcInput = Buffer.concat([chunkType, chunkData])
  const crcBuf = Buffer.alloc(4)
  crcBuf.writeUInt32BE(crc32(crcInput), 0)

  const chunk = Buffer.concat([lengthBuf, chunkType, chunkData, crcBuf])

  // Insert the zTXt chunk before IEND (last 12 bytes of a valid PNG)
  const iendStart = data.length - 12
  const before = data.subarray(0, iendStart)
  const iend = data.subarray(iendStart)

  writeFileSync(pngPath, Buffer.concat([before, chunk, iend]))
}

function extractXmlFromPng(pngPath: string): string | null {
  const data = readFileSync(pngPath)

  // Walk PNG chunks looking for zTXt with key "mxGraphModel"
  let pos = 8 // skip PNG signature
  while (pos < data.length) {
    const length = data.readUInt32BE(pos)
    const chunkType = data.subarray(pos + 4, pos + 8).toString("ascii")
    const chunkData = data.subarray(pos + 8, pos + 8 + length)

    if (chunkType === "zTXt") {
      const nullPos = chunkData.indexOf(0)
      const key = chunkData.subarray(0, nullPos).toString("ascii")
      if (key === "mxGraphModel") {
        // byte after null is compression method (0), then zlib-compressed data
        const compressed = chunkData.subarray(nullPos + 2)
        const mxfileXml = inflateSync(compressed).toString("utf-8")
        // Parse the <mxfile><diagram>PAYLOAD</diagram></mxfile> wrapper
        const match = mxfileXml.match(/<diagram[^>]*>([\s\S]*?)<\/diagram>/)
        if (match) {
          return decodeDiagramPayload(match[1])
        }
        // Fallback: return the raw mxfile XML if no diagram tag found
        return mxfileXml
      }
    }

    pos += 12 + length
  }
  return null
}

// ============================================================
// Export helper using npx draw.io-export
// ============================================================

async function exportDrawio(drawioPath: string, pngPath: string): Promise<string | null> {
  try {
    const proc = Bun.spawn(["npx", "draw.io-export", drawioPath, "-o", pngPath], {
      stdout: "pipe",
      stderr: "pipe",
    })
    const exitCode = await proc.exited
    if (exitCode !== 0) {
      const stderr = await new Response(proc.stderr).text()
      return `Export failed (exit ${exitCode}): ${stderr}`
    }
    return null // success
  } catch (err) {
    return `Export failed: ${err instanceof Error ? err.message : String(err)}`
  }
}

// ============================================================
// Tools
// ============================================================

export const create_diagram = tool({
  description: `Create a draw.io diagram from XML and export it as a PNG with the diagram XML embedded inside the image (editable by opening the PNG in draw.io).

Workflow:
1. Writes the XML to a temporary .drawio file
2. Exports to PNG via npx draw.io-export
3. Embeds the source XML into the PNG as a zTXt chunk in draw.io's native format (key: "mxGraphModel")
4. Cleans up the intermediate .drawio file
5. Returns the path to the .drawio.png file

The resulting PNG is viewable as a normal image AND editable in draw.io (drag the PNG onto draw.io to recover the full diagram).`,
  args: {
    xml: tool.schema.string().describe("The draw.io mxGraphModel XML content"),
    output_path: tool.schema.string().describe("Output file path (should end in .drawio.png)"),
  },
  async execute(args) {
    const { xml, output_path } = args

    const dir = dirname(output_path)
    const name = basename(output_path, ".drawio.png").replace(/\.png$/, "")
    const drawioPath = join(dir, `${name}.drawio`)
    const pngPath = output_path.endsWith(".drawio.png") ? output_path : `${output_path}.drawio.png`

    // 1. Write .drawio file
    writeFileSync(drawioPath, xml, "utf-8")

    // 2. Export to PNG
    const exportErr = await exportDrawio(drawioPath, pngPath)
    if (exportErr) {
      return `Error: ${exportErr}\n\nThe .drawio file was saved at: ${drawioPath}\nYou can open it in draw.io manually.`
    }

    // 3. Embed XML into PNG
    try {
      embedXmlInPng(pngPath, xml)
    } catch (err) {
      return `PNG exported but XML embedding failed: ${err instanceof Error ? err.message : String(err)}\n\nPNG saved at: ${pngPath}\n.drawio source at: ${drawioPath}`
    }

    // 4. Clean up .drawio file
    try {
      unlinkSync(drawioPath)
    } catch {}

    return `Diagram created: ${pngPath}\n\nThis PNG has the draw.io XML embedded. Open it in draw.io to edit the diagram.`
  },
})

export const read_diagram = tool({
  description: `Extract the draw.io XML source from an existing .drawio.png file.

Reads the embedded mxfile XML from the PNG's zTXt metadata chunk. Returns the XML so it can be modified and written back with update_diagram.`,
  args: {
    png_path: tool.schema.string().describe("Path to the .drawio.png file"),
  },
  async execute(args) {
    const { png_path } = args

    if (!existsSync(png_path)) {
      return `File not found: ${png_path}`
    }

    const xml = extractXmlFromPng(png_path)
    if (!xml) {
      return `No embedded draw.io XML found in: ${png_path}\n\nThis PNG may not have been created with embedded diagram data.`
    }

    return xml
  },
})

export const update_diagram = tool({
  description: `Update an existing .drawio.png file with new XML. 

Overwrites both the PNG image and the embedded XML source. Use read_diagram first to get the current XML, modify it, then call this to save the changes.`,
  args: {
    xml: tool.schema.string().describe("The updated draw.io mxGraphModel XML content"),
    png_path: tool.schema.string().describe("Path to the existing .drawio.png file to update"),
  },
  async execute(args) {
    const { xml, png_path } = args

    const dir = dirname(png_path)
    const name = basename(png_path, ".drawio.png").replace(/\.png$/, "")
    const drawioPath = join(dir, `${name}.tmp.drawio`)

    // 1. Write updated .drawio
    writeFileSync(drawioPath, xml, "utf-8")

    // 2. Re-export PNG
    const exportErr = await exportDrawio(drawioPath, png_path)
    if (exportErr) {
      try { unlinkSync(drawioPath) } catch {}
      return `Error re-exporting: ${exportErr}`
    }

    // 3. Re-embed XML
    try {
      embedXmlInPng(png_path, xml)
    } catch (err) {
      try { unlinkSync(drawioPath) } catch {}
      return `PNG re-exported but XML embedding failed: ${err instanceof Error ? err.message : String(err)}`
    }

    // 4. Clean up temp
    try { unlinkSync(drawioPath) } catch {}

    return `Diagram updated: ${png_path}`
  },
})
