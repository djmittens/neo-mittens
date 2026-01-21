#!/usr/bin/env bun

// Continue formatting the design document from section 7
const DOC_ID = "1EnBqk4Y27BNuSIz6HcnIaOK1YUk6Mf0hrb7AKZburiY"
const QUOTA_PROJECT = "ck-orp-nick-dev"

const COLORS = {
  HEADING_RED: { red: 0.596, green: 0, blue: 0 },
  HEADING_DARK: { red: 0.267, green: 0.267, blue: 0.267 },
  WHITE: { red: 1, green: 1, blue: 1 },
  TABLE_HEADER: { red: 0.2, green: 0.2, blue: 0.2 },
}

async function getAccessToken(): Promise<string> {
  const proc = Bun.spawn(["gcloud", "auth", "application-default", "print-access-token"], { stdout: "pipe" })
  return (await new Response(proc.stdout).text()).trim()
}

async function docsApi(endpoint: string, body?: any): Promise<any> {
  const token = await getAccessToken()
  const response = await fetch(`https://docs.googleapis.com${endpoint}`, {
    method: body ? "POST" : "GET",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "x-goog-user-project": QUOTA_PROJECT,
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) throw new Error(`API error: ${await response.text()}`)
  return response.json()
}

async function getEndIndex(): Promise<number> {
  const doc = await docsApi(`/v1/documents/${DOC_ID}`)
  return doc.body?.content?.slice(-1)[0]?.endIndex || 2
}

async function insertAndStyle(text: string, style: "h1" | "h2" | "h3" | "bullet" | "p" | "code"): Promise<void> {
  const idx = (await getEndIndex()) - 1
  const fullText = text + "\n"
  
  await docsApi(`/v1/documents/${DOC_ID}:batchUpdate`, {
    requests: [{ insertText: { location: { index: idx }, text: fullText } }],
  })
  
  const endIdx = idx + fullText.length
  const requests: any[] = []
  
  if (style === "h1") {
    requests.push({
      updateParagraphStyle: {
        range: { startIndex: idx, endIndex: endIdx },
        paragraphStyle: { namedStyleType: "HEADING_1", spaceAbove: { magnitude: 24, unit: "PT" }, spaceBelow: { magnitude: 12, unit: "PT" } },
        fields: "namedStyleType,spaceAbove,spaceBelow",
      },
    })
    requests.push({
      updateTextStyle: {
        range: { startIndex: idx, endIndex: endIdx - 1 },
        textStyle: { bold: true, fontSize: { magnitude: 18, unit: "PT" }, foregroundColor: { color: { rgbColor: COLORS.HEADING_RED } } },
        fields: "bold,fontSize,foregroundColor",
      },
    })
  } else if (style === "h2") {
    requests.push({
      updateParagraphStyle: {
        range: { startIndex: idx, endIndex: endIdx },
        paragraphStyle: { namedStyleType: "HEADING_2", spaceAbove: { magnitude: 18, unit: "PT" }, spaceBelow: { magnitude: 8, unit: "PT" } },
        fields: "namedStyleType,spaceAbove,spaceBelow",
      },
    })
    requests.push({
      updateTextStyle: {
        range: { startIndex: idx, endIndex: endIdx - 1 },
        textStyle: { bold: true, fontSize: { magnitude: 14, unit: "PT" }, foregroundColor: { color: { rgbColor: COLORS.HEADING_RED } } },
        fields: "bold,fontSize,foregroundColor",
      },
    })
  } else if (style === "h3") {
    requests.push({
      updateParagraphStyle: {
        range: { startIndex: idx, endIndex: endIdx },
        paragraphStyle: { namedStyleType: "HEADING_3", spaceAbove: { magnitude: 14, unit: "PT" }, spaceBelow: { magnitude: 6, unit: "PT" } },
        fields: "namedStyleType,spaceAbove,spaceBelow",
      },
    })
    requests.push({
      updateTextStyle: {
        range: { startIndex: idx, endIndex: endIdx - 1 },
        textStyle: { bold: true, fontSize: { magnitude: 12, unit: "PT" }, foregroundColor: { color: { rgbColor: COLORS.HEADING_DARK } } },
        fields: "bold,fontSize,foregroundColor",
      },
    })
  } else if (style === "bullet") {
    requests.push({
      createParagraphBullets: {
        range: { startIndex: idx, endIndex: endIdx },
        bulletPreset: "BULLET_DISC_CIRCLE_SQUARE",
      },
    })
  } else if (style === "code") {
    requests.push({
      updateTextStyle: {
        range: { startIndex: idx, endIndex: endIdx - 1 },
        textStyle: {
          weightedFontFamily: { fontFamily: "Roboto Mono" },
          fontSize: { magnitude: 9, unit: "PT" },
          backgroundColor: { color: { rgbColor: { red: 0.96, green: 0.96, blue: 0.96 } } },
        },
        fields: "weightedFontFamily,fontSize,backgroundColor",
      },
    })
  }
  
  if (requests.length > 0) {
    await docsApi(`/v1/documents/${DOC_ID}:batchUpdate`, { requests })
  }
}

async function insertTable(headers: string[], rows: string[][]): Promise<void> {
  const idx = (await getEndIndex()) - 1
  const numRows = rows.length + 1
  const numCols = headers.length
  
  await docsApi(`/v1/documents/${DOC_ID}:batchUpdate`, {
    requests: [{ insertTable: { rows: numRows, columns: numCols, location: { index: idx } } }],
  })
  
  // Get table
  const doc = await docsApi(`/v1/documents/${DOC_ID}`)
  let table: any = null
  for (const el of doc.body?.content || []) {
    if (el.table && el.startIndex >= idx) { table = el; break }
  }
  if (!table) return
  
  // Populate cells
  const allRows = [headers, ...rows]
  const textReqs: any[] = []
  for (let r = 0; r < numRows; r++) {
    for (let c = 0; c < numCols; c++) {
      const cell = table.table.tableRows[r]?.tableCells[c]
      const val = allRows[r]?.[c] || ""
      if (cell?.content?.[0] && val) {
        textReqs.push({ insertText: { location: { index: cell.content[0].startIndex }, text: val } })
      }
    }
  }
  if (textReqs.length > 0) {
    await docsApi(`/v1/documents/${DOC_ID}:batchUpdate`, { requests: textReqs.reverse() })
  }
  
  // Style header
  const styleReqs: any[] = []
  for (let c = 0; c < numCols; c++) {
    styleReqs.push({
      updateTableCellStyle: {
        tableRange: { tableCellLocation: { tableStartLocation: { index: table.startIndex }, rowIndex: 0, columnIndex: c }, rowSpan: 1, columnSpan: 1 },
        tableCellStyle: { backgroundColor: { color: { rgbColor: COLORS.TABLE_HEADER } } },
        fields: "backgroundColor",
      },
    })
  }
  await docsApi(`/v1/documents/${DOC_ID}:batchUpdate`, { requests: styleReqs })
  
  // White header text
  const doc2 = await docsApi(`/v1/documents/${DOC_ID}`)
  let table2: any = null
  for (const el of doc2.body?.content || []) {
    if (el.table && el.startIndex >= idx) { table2 = el; break }
  }
  if (table2) {
    const hdrReqs: any[] = []
    for (let c = 0; c < numCols; c++) {
      const cell = table2.table.tableRows[0]?.tableCells[c]
      if (cell?.content?.[0]) {
        const s = cell.content[0].startIndex, e = cell.content[0].endIndex - 1
        if (s < e) {
          hdrReqs.push({
            updateTextStyle: {
              range: { startIndex: s, endIndex: e },
              textStyle: { foregroundColor: { color: { rgbColor: COLORS.WHITE } }, bold: true },
              fields: "foregroundColor,bold",
            },
          })
        }
      }
    }
    if (hdrReqs.length > 0) {
      await docsApi(`/v1/documents/${DOC_ID}:batchUpdate`, { requests: hdrReqs })
    }
  }
}

async function main() {
  console.log("Continuing from Section 7...")
  
  // 7.1 Command-Line Arguments
  await insertAndStyle("7.1 Command-Line Arguments", "h2")
  await insertAndStyle("Core Parameters", "h3")
  await insertTable(["Parameter", "Description"], [
    ["--job-type", "\"streaming\" or \"batch\""],
    ["--project-id", "Spanner project ID"],
    ["--instance-id", "Spanner instance ID"],
    ["--database-id", "Spanner database ID"],
    ["--spanner-schemas", "Base64-encoded JSON schema"],
  ])
  
  await insertAndStyle("Streaming-Specific", "h3")
  await insertTable(["Parameter", "Description"], [
    ["--change-stream-name", "Change stream name"],
    ["--metadata-instance-id", "Metadata database instance"],
    ["--metadata-database-id", "Metadata database name"],
  ])
  
  await insertAndStyle("Batch-Specific", "h3")
  await insertTable(["Parameter", "Description"], [
    ["--snapshot-read-timestamp", "Point-in-time snapshot"],
  ])
  
  await insertAndStyle("Sink Parameters", "h3")
  await insertTable(["Parameter", "Description"], [
    ["--bigquery-project-id", "BigQuery project"],
    ["--bigquery-dataset-id", "BigQuery dataset"],
    ["--write-mode", "\"upsert\" or \"append\""],
  ])
  
  await insertAndStyle("Encryption Parameters", "h3")
  await insertTable(["Parameter", "Description"], [
    ["--encryption-ingress-gateway-url", "Mesh ingress URL"],
    ["--encryption-gsm-project-id", "Secret Manager project"],
    ["--encryption-use-mtls", "Enable mTLS (true/false)"],
    ["--encryption-gca-project-id", "CAS project for mTLS"],
    ["--encryption-gca-ca-pool-id", "CA pool for mTLS"],
  ])
  
  // 7.2 Supported Types
  await insertAndStyle("7.2 Supported Types", "h2")
  await insertTable(["Spanner", "Beam", "BigQuery"], [
    ["INT64", "INT64", "INT64"],
    ["STRING", "STRING", "STRING"],
    ["BOOL", "BOOLEAN", "BOOL"],
    ["FLOAT64", "DOUBLE", "FLOAT64"],
    ["NUMERIC", "DECIMAL", "NUMERIC"],
    ["BYTES", "BYTES", "BYTES"],
    ["JSON", "STRING", "STRING"],
    ["DATE", "Logical Date", "DATE"],
    ["TIMESTAMP", "DATETIME", "TIMESTAMP"],
  ])
  
  // Section 8
  console.log("Writing Section 8...")
  await insertAndStyle("8. Infrastructure Requirements", "h1")
  await insertAndStyle("8.1 Network Architecture", "h2")
  await insertAndStyle("Dataflow workers require network access to:", "p")
  await insertAndStyle("Spanner (source database)", "bullet")
  await insertAndStyle("BigQuery (destination)", "bullet")
  await insertAndStyle("Auth Service v2 (JWT tokens)", "bullet")
  await insertAndStyle("Key Service v1 (DEK decryption)", "bullet")
  await insertAndStyle("Secret Manager (credentials)", "bullet")
  await insertAndStyle("Certificate Authority Service (mTLS certs)", "bullet")
  
  await insertAndStyle("8.2 Connection Modes", "h2")
  await insertAndStyle("mTLS Mode (Production/Dataflow)", "h3")
  await insertAndStyle("Mutual TLS with SNI-based routing", "bullet")
  await insertAndStyle("Certificates from Google CAS", "bullet")
  await insertAndStyle("Ingress: mesh-ingress-gateway.vault.cktest.us-central1.ckint.io:32080", "bullet")
  
  await insertAndStyle("Local Sidecar Mode (Development)", "h3")
  await insertAndStyle("Plain HTTP through local Envoy proxy at http://localhost:4140", "bullet")
  await insertAndStyle("Host header routing", "bullet")
  
  // Section 9
  console.log("Writing Section 9...")
  await insertAndStyle("9. Security Considerations", "h1")
  await insertAndStyle("9.1 Credential Management", "h2")
  await insertAndStyle("Auth client credentials stored in Secret Manager", "bullet")
  await insertAndStyle("mTLS certificates provisioned dynamically from CAS", "bullet")
  await insertAndStyle("JWT tokens cached with automatic refresh", "bullet")
  
  await insertAndStyle("9.2 Data Protection", "h2")
  await insertAndStyle("Encrypted data never written to logs (Sanitizer redaction)", "bullet")
  await insertAndStyle("PII numericIds redacted from log messages", "bullet")
  await insertAndStyle("Decrypted data only exists in memory during processing", "bullet")
  await insertAndStyle("BigQuery destination should have appropriate access controls", "bullet")
  
  await insertAndStyle("9.3 Access Control", "h2")
  await insertAndStyle("Dataflow service account requires:", "p")
  await insertAndStyle("Spanner read access", "bullet")
  await insertAndStyle("BigQuery write access", "bullet")
  await insertAndStyle("Secret Manager access", "bullet")
  await insertAndStyle("CAS certificate issuance", "bullet")
  
  // Appendix A
  console.log("Writing Appendix A...")
  await insertAndStyle("Appendix A: Project Structure", "h1")
  await insertAndStyle(`daf_dataflow-templates/
├── build.sbt                    # Root build
├── spanner-to-bigquery/         # Main production module
│   ├── src/main/scala/          # Pipeline code
│   ├── src/main/thrift/         # Thrift IDLs
│   └── src/test/scala/          # Unit tests
├── hello-dataflow/              # Example/POC module
├── integration/                 # Integration tests
└── ai-docs/                     # Documentation`, "code")
  
  // Appendix B
  console.log("Writing Appendix B...")
  await insertAndStyle("Appendix B: Key Files Reference", "h1")
  await insertTable(["Category", "Key Files"], [
    ["Entry Point", "SpannerToBQ.scala"],
    ["Pipelines", "StreamingPipeline.scala, BatchPipeline.scala"],
    ["Configuration", "TemplateConfig.scala, SchemaRegistry.scala"],
    ["Transforms", "TransformOps.scala, DecryptionTransformOps"],
    ["Sink", "BigQuery.scala"],
    ["Auth/Crypto", "AuthServiceClient, KeyServiceClient"],
    ["mTLS", "GcaCertificateProvider, MtlsHttpClientFactory"],
    ["Utilities", "Sanitizer.scala, ETLMetrics.scala"],
  ])
  
  console.log("\nDocument complete!")
  console.log(`URL: https://docs.google.com/document/d/${DOC_ID}/edit`)
}

main().catch(console.error)
