#!/usr/bin/env bun

// Script to format the design document with proper styling
// Run with: bun run format-design-doc.ts

const DOC_ID = "1EnBqk4Y27BNuSIz6HcnIaOK1YUk6Mf0hrb7AKZburiY"
const QUOTA_PROJECT = "ck-orp-nick-dev"

const COLORS = {
  HEADING_RED: { red: 0.596, green: 0, blue: 0 },
  HEADING_DARK: { red: 0.267, green: 0.267, blue: 0.267 },
  WHITE: { red: 1, green: 1, blue: 1 },
  TABLE_HEADER: { red: 0.2, green: 0.2, blue: 0.2 },
  TABLE_ALT: { red: 0.976, green: 0.976, blue: 0.976 },
}

async function getAccessToken(): Promise<string> {
  const proc = Bun.spawn(["gcloud", "auth", "application-default", "print-access-token"], {
    stdout: "pipe",
  })
  const output = await new Response(proc.stdout).text()
  return output.trim()
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
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`API error: ${error}`)
  }
  return response.json()
}

async function getEndIndex(): Promise<number> {
  const doc = await docsApi(`/v1/documents/${DOC_ID}`)
  return doc.body?.content?.slice(-1)[0]?.endIndex || 2
}

async function insertText(index: number, text: string): Promise<void> {
  await docsApi(`/v1/documents/${DOC_ID}:batchUpdate`, {
    requests: [{ insertText: { location: { index }, text } }],
  })
}

async function applyStyles(requests: any[]): Promise<void> {
  if (requests.length === 0) return
  await docsApi(`/v1/documents/${DOC_ID}:batchUpdate`, { requests })
}

// Document structure
const sections = [
  {
    type: "h1",
    text: "1. Executive Summary",
    content: [
      { type: "h3", text: "Purpose" },
      { type: "p", text: "This project provides production-ready Apache Beam/Scio Dataflow templates for ETL pipelines that read data from Google Cloud Spanner and write to BigQuery. The key differentiator is native support for envelope encryption, enabling secure processing of PII data without requiring custom code in each service." },
      { type: "h3", text: "Key Capabilities" },
      { type: "bullet", text: "Streaming Pipeline: Real-time CDC (Change Data Capture) via Spanner Change Streams" },
      { type: "bullet", text: "Batch Pipeline: Point-in-time snapshots for historical data loads" },
      { type: "bullet", text: "Envelope Decryption: Integrated Key Service for DEK unwrapping" },
      { type: "bullet", text: "NumericId Mapping: Translation of internal IDs to data warehouse IDs" },
      { type: "bullet", text: "Flexible Transforms: Per-table SQL transformations" },
      { type: "bullet", text: "BigQuery CDC: Native UPSERT/DELETE support via Storage Write API" },
      { type: "h3", text: "Technology Stack" },
      { type: "table", headers: ["Component", "Technology"], rows: [
        ["Language", "Scala 2.12"],
        ["Framework", "Apache Beam 2.66.0, Scio 0.14.18"],
        ["Runtime", "Java 17 on Google Dataflow"],
        ["Protocols", "Apache Thrift 0.22.0"],
      ]},
    ],
  },
  {
    type: "h1",
    text: "2. Architecture Overview",
    content: [
      { type: "h3", text: "High-Level System Architecture" },
      { type: "p", text: "The system follows a standard ETL pattern with three main stages:" },
      { type: "p", text: "SOURCE (Spanner) → TRANSFORM (Dataflow) → SINK (BigQuery)" },
      { type: "h3", text: "Data Sources" },
      { type: "bullet", text: "Spanner Change Streams for real-time streaming" },
      { type: "bullet", text: "Spanner Table Snapshots for batch processing" },
      { type: "h3", text: "Transformations" },
      { type: "bullet", text: "Schema conversion (Spanner → Beam → BigQuery)" },
      { type: "bullet", text: "Envelope decryption for encrypted fields" },
      { type: "bullet", text: "NumericId to DWNumericId mapping" },
      { type: "bullet", text: "Custom SQL transforms per table" },
      { type: "h3", text: "Destinations" },
      { type: "bullet", text: "BigQuery with Storage Write API" },
      { type: "bullet", text: "CDC mode (UPSERT/DELETE) or Append mode" },
    ],
  },
  {
    type: "h1",
    text: "3. Pipeline Types",
    content: [
      { type: "h2", text: "3.1 Streaming Pipeline" },
      { type: "p", text: "The streaming pipeline processes Change Data Capture events in real-time." },
      { type: "table", headers: ["Property", "Value"], rows: [
        ["Entry Point", "StreamingPipeline.scala"],
        ["Source", "SpannerIO.readChangeStream()"],
        ["Latency", "Near real-time (seconds to minutes)"],
        ["Use Case", "Continuous data synchronization"],
      ]},
      { type: "h3", text: "Flow" },
      { type: "bullet", text: "Read from Spanner Change Stream" },
      { type: "bullet", text: "Partition records by table name" },
      { type: "bullet", text: "Convert DataChangeRecord to Beam Row" },
      { type: "bullet", text: "Apply transformations and decryption" },
      { type: "bullet", text: "Write to BigQuery with CDC semantics" },
      { type: "h3", text: "CDC Operations Supported" },
      { type: "bullet", text: "INSERT: New records" },
      { type: "bullet", text: "UPDATE: Modified records (UPSERT in BigQuery)" },
      { type: "bullet", text: "DELETE: Removed records (DELETE in BigQuery)" },
      { type: "h2", text: "3.2 Batch Pipeline" },
      { type: "p", text: "The batch pipeline reads complete table snapshots at a specific timestamp." },
      { type: "table", headers: ["Property", "Value"], rows: [
        ["Entry Point", "BatchPipeline.scala"],
        ["Source", "SpannerIO.read()"],
        ["Use Case", "Initial loads, backfills, snapshots"],
      ]},
    ],
  },
  {
    type: "h1",
    text: "4. Core Components",
    content: [
      { type: "h2", text: "4.1 Entry Point" },
      { type: "p", text: "SpannerToBQ.scala - Main application entry point that parses configuration and dispatches to the appropriate pipeline (streaming or batch)." },
      { type: "h2", text: "4.2 Configuration" },
      { type: "table", headers: ["Component", "Purpose"], rows: [
        ["TemplateConfig.scala", "Main config holder, CLI arg parsing"],
        ["StreamingSourceConfig", "Change stream settings"],
        ["BatchSourceConfig", "Snapshot read settings"],
        ["SinkConfig", "BigQuery destination settings"],
        ["EncryptionConfig", "Key Service integration"],
        ["NumericIdMappingConfig", "ID translation settings"],
        ["SchemaRegistry.scala", "Table schemas, type conversions"],
      ]},
      { type: "h2", text: "4.3 Transformations" },
      { type: "table", headers: ["Component", "Purpose"], rows: [
        ["TransformOps.scala", "Main transformation orchestrator"],
        ["DecryptionTransformOps.scala", "Envelope decryption logic"],
        ["BeamRowConverter.scala", "Type-safe Spanner → Beam Row"],
        ["NumericIdFieldsFilter.scala", "ID mapping via Spanner lookup"],
      ]},
      { type: "h2", text: "4.4 Sinks" },
      { type: "p", text: "BigQuery.scala - Configures BigQuery Storage Write API with CDC mode (UPSERT/DELETE) or Append mode." },
      { type: "h2", text: "4.5 Security Clients" },
      { type: "table", headers: ["Component", "Purpose"], rows: [
        ["AuthServiceClient.scala", "JWT token acquisition"],
        ["KeyServiceClient.scala", "DEK decryption via Key Service"],
        ["EnvelopeDecryption.scala", "AES-GCM local decryption"],
        ["SecretManagerClient.scala", "Credential retrieval from GSM"],
        ["GcaCertificateProvider.scala", "mTLS certificate provisioning"],
      ]},
    ],
  },
  {
    type: "h1",
    text: "5. Data Flow",
    content: [
      { type: "h2", text: "Streaming Pipeline Data Flow" },
      { type: "p", text: "The following steps describe the streaming pipeline data flow:" },
      { type: "bullet", text: "[1] Read CDC Events (DataChangeRecord) from Spanner Change Stream" },
      { type: "bullet", text: "[2] Partition by Table Name" },
      { type: "bullet", text: "[3] Convert to Beam Row" },
      { type: "bullet", text: "[4] Decrypt Encrypted Fields (parse DekAndData, call Key Service, AES-GCM decrypt)" },
      { type: "bullet", text: "[5] Map NumericId → DWNumericId (if configured)" },
      { type: "bullet", text: "[6] Apply SQL Transform (if configured)" },
      { type: "bullet", text: "[7] Convert to BigQuery TableRow" },
      { type: "bullet", text: "[8] Write to BigQuery (UPSERT for INSERT/UPDATE, DELETE for DELETE)" },
    ],
  },
  {
    type: "h1",
    text: "6. Encryption Architecture",
    content: [
      { type: "h2", text: "6.1 Envelope Encryption Overview" },
      { type: "p", text: "Envelope encryption is a two-tier encryption scheme:" },
      { type: "bullet", text: "DEK (Data Encryption Key): Symmetric AES-256 key that encrypts actual data" },
      { type: "bullet", text: "KEK (Key Encryption Key): Master key in HSM that encrypts the DEK" },
      { type: "h3", text: "Benefits" },
      { type: "bullet", text: "Data keys can be rotated without re-encrypting all data" },
      { type: "bullet", text: "Master keys never leave the HSM" },
      { type: "bullet", text: "Each record can have its own DEK" },
      { type: "h2", text: "6.2 DekAndData Structure" },
      { type: "p", text: "Data is stored in Spanner as a thrift-serialized DekAndData structure containing:" },
      { type: "bullet", text: "dek: binary - Encrypted DEK (wrapped by member KEK)" },
      { type: "bullet", text: "data: binary - Encrypted payload (AES-256-GCM ciphertext)" },
      { type: "h2", text: "6.3 Decryption Flow" },
      { type: "bullet", text: "Parse DekAndData thrift structure" },
      { type: "bullet", text: "Send encrypted DEK + numericId to Key Service" },
      { type: "bullet", text: "Receive plain DEK from Key Service (unwrapped via HSM)" },
      { type: "bullet", text: "Use plain DEK for local AES-256-GCM decryption" },
      { type: "bullet", text: "Return plain data" },
      { type: "h2", text: "6.4 Security Services Integration" },
      { type: "p", text: "The Dataflow worker integrates with these security services:" },
      { type: "bullet", text: "Secret Manager: Fetch client_id and client_secret credentials" },
      { type: "bullet", text: "Auth Service v2: Obtain JWT tokens for Key Service authentication" },
      { type: "bullet", text: "Key Service v1: Decrypt DEKs using HSM-stored KEKs" },
    ],
  },
  {
    type: "h1",
    text: "7. Configuration",
    content: [
      { type: "h2", text: "7.1 Command-Line Arguments" },
      { type: "h3", text: "Core Parameters" },
      { type: "table", headers: ["Parameter", "Description"], rows: [
        ["--job-type", "\"streaming\" or \"batch\""],
        ["--project-id", "Spanner project ID"],
        ["--instance-id", "Spanner instance ID"],
        ["--database-id", "Spanner database ID"],
        ["--spanner-schemas", "Base64-encoded JSON schema"],
      ]},
      { type: "h3", text: "Streaming-Specific" },
      { type: "table", headers: ["Parameter", "Description"], rows: [
        ["--change-stream-name", "Change stream name"],
        ["--metadata-instance-id", "Metadata database instance"],
        ["--metadata-database-id", "Metadata database name"],
      ]},
      { type: "h3", text: "Batch-Specific" },
      { type: "table", headers: ["Parameter", "Description"], rows: [
        ["--snapshot-read-timestamp", "Point-in-time snapshot timestamp"],
      ]},
      { type: "h3", text: "Sink Parameters" },
      { type: "table", headers: ["Parameter", "Description"], rows: [
        ["--bigquery-project-id", "BigQuery project"],
        ["--bigquery-dataset-id", "BigQuery dataset"],
        ["--write-mode", "\"upsert\" or \"append\""],
      ]},
      { type: "h3", text: "Encryption Parameters" },
      { type: "table", headers: ["Parameter", "Description"], rows: [
        ["--encryption-ingress-gateway-url", "Mesh ingress URL"],
        ["--encryption-gsm-project-id", "Secret Manager project"],
        ["--encryption-use-mtls", "Enable mTLS (true/false)"],
        ["--encryption-gca-project-id", "CAS project for mTLS"],
        ["--encryption-gca-ca-pool-id", "CA pool for mTLS"],
      ]},
      { type: "h2", text: "7.2 Schema Definition Format" },
      { type: "p", text: "Schemas are defined as JSON and passed Base64-encoded. Each field has: name, type, nullable, isPrimaryKey (optional), encrypted (optional), decryptedType (optional), numericIdFieldForDecryption (optional), isNumericId (optional)." },
      { type: "h2", text: "7.3 Supported Types" },
      { type: "table", headers: ["Spanner", "Beam", "BigQuery"], rows: [
        ["INT64", "INT64", "INT64"],
        ["STRING", "STRING", "STRING"],
        ["BOOL", "BOOLEAN", "BOOL"],
        ["FLOAT64", "DOUBLE", "FLOAT64"],
        ["FLOAT32", "FLOAT", "FLOAT64"],
        ["NUMERIC", "DECIMAL", "NUMERIC"],
        ["BYTES", "BYTES", "BYTES"],
        ["JSON", "STRING", "STRING"],
        ["DATE", "Logical Date", "DATE"],
        ["TIMESTAMP", "DATETIME", "TIMESTAMP"],
        ["ARRAY<T>", "array(T)", "REPEATED"],
      ]},
    ],
  },
  {
    type: "h1",
    text: "8. Infrastructure Requirements",
    content: [
      { type: "h2", text: "8.1 Network Architecture" },
      { type: "p", text: "Dataflow workers require network access to:" },
      { type: "bullet", text: "Spanner (source database)" },
      { type: "bullet", text: "BigQuery (destination)" },
      { type: "bullet", text: "Auth Service v2 (JWT tokens)" },
      { type: "bullet", text: "Key Service v1 (DEK decryption)" },
      { type: "bullet", text: "Secret Manager (credentials)" },
      { type: "bullet", text: "Certificate Authority Service (mTLS certs)" },
      { type: "h2", text: "8.2 Connection Modes" },
      { type: "h3", text: "mTLS Mode (Production/Dataflow)" },
      { type: "bullet", text: "Mutual TLS with SNI-based routing" },
      { type: "bullet", text: "Certificates from Google CAS" },
      { type: "bullet", text: "Ingress: mesh-ingress-gateway.vault.cktest.us-central1.ckint.io:32080" },
      { type: "bullet", text: "Auth SNI: auth-service-v2.service.vault" },
      { type: "bullet", text: "Key Service SNI: key-service-bulk.service.vault" },
      { type: "h3", text: "Local Sidecar Mode (Development)" },
      { type: "bullet", text: "Plain HTTP through local Envoy proxy" },
      { type: "bullet", text: "URL: http://localhost:4140" },
      { type: "bullet", text: "Host header routing" },
    ],
  },
  {
    type: "h1",
    text: "9. Security Considerations",
    content: [
      { type: "h2", text: "9.1 Credential Management" },
      { type: "bullet", text: "Auth client credentials stored in Secret Manager" },
      { type: "bullet", text: "mTLS certificates provisioned dynamically from CAS" },
      { type: "bullet", text: "JWT tokens cached with automatic refresh" },
      { type: "h2", text: "9.2 Data Protection" },
      { type: "bullet", text: "Encrypted data never written to logs (Sanitizer redaction)" },
      { type: "bullet", text: "PII numericIds redacted from log messages" },
      { type: "bullet", text: "Decrypted data only exists in memory during processing" },
      { type: "bullet", text: "BigQuery destination should have appropriate access controls" },
      { type: "h2", text: "9.3 Access Control" },
      { type: "p", text: "Dataflow service account requires:" },
      { type: "bullet", text: "Spanner read access" },
      { type: "bullet", text: "BigQuery write access" },
      { type: "bullet", text: "Secret Manager access" },
      { type: "bullet", text: "CAS certificate issuance" },
    ],
  },
  {
    type: "h1",
    text: "Appendix A: Project Structure",
    content: [
      { type: "code", text: "daf_dataflow-templates/\n├── build.sbt                    # Root build\n├── spanner-to-bigquery/         # Main production module\n│   ├── src/main/scala/          # Pipeline code\n│   ├── src/main/thrift/         # Thrift IDLs\n│   └── src/test/scala/          # Unit tests\n├── hello-dataflow/              # Example/POC module\n├── integration/                 # Integration tests\n└── ai-docs/                     # Documentation" },
    ],
  },
  {
    type: "h1",
    text: "Appendix B: Key Files Reference",
    content: [
      { type: "table", headers: ["Category", "Key Files"], rows: [
        ["Entry Point", "SpannerToBQ.scala"],
        ["Pipelines", "StreamingPipeline.scala, BatchPipeline.scala"],
        ["Configuration", "TemplateConfig.scala, SchemaRegistry.scala"],
        ["Transforms", "TransformOps.scala, DecryptionTransformOps"],
        ["Sink", "BigQuery.scala"],
        ["Auth/Crypto", "AuthServiceClient, KeyServiceClient"],
        ["mTLS", "GcaCertificateProvider, MtlsHttpClientFactory"],
        ["Utilities", "Sanitizer.scala, ETLMetrics.scala"],
      ]},
    ],
  },
]

async function main() {
  console.log("Starting document formatting...")
  
  // Track current position
  let currentIndex = await getEndIndex() - 1
  
  for (const section of sections) {
    console.log(`Writing section: ${section.text}`)
    
    // Insert section heading
    const headingText = section.text + "\n"
    await insertText(currentIndex, headingText)
    
    // Apply H1 style
    const headingEnd = currentIndex + headingText.length
    await applyStyles([
      {
        updateParagraphStyle: {
          range: { startIndex: currentIndex, endIndex: headingEnd },
          paragraphStyle: { 
            namedStyleType: "HEADING_1",
            spaceAbove: { magnitude: 24, unit: "PT" },
            spaceBelow: { magnitude: 12, unit: "PT" },
          },
          fields: "namedStyleType,spaceAbove,spaceBelow",
        },
      },
      {
        updateTextStyle: {
          range: { startIndex: currentIndex, endIndex: headingEnd - 1 },
          textStyle: {
            bold: true,
            fontSize: { magnitude: 18, unit: "PT" },
            foregroundColor: { color: { rgbColor: COLORS.HEADING_RED } },
          },
          fields: "bold,fontSize,foregroundColor",
        },
      },
    ])
    
    currentIndex = headingEnd
    
    // Process content items
    for (const item of section.content) {
      if (item.type === "table") {
        // Insert table
        const tableItem = item as { type: "table"; headers: string[]; rows: string[][] }
        const numRows = tableItem.rows.length + 1
        const numCols = tableItem.headers.length
        
        // Insert table
        await docsApi(`/v1/documents/${DOC_ID}:batchUpdate`, {
          requests: [{
            insertTable: {
              rows: numRows,
              columns: numCols,
              location: { index: currentIndex },
            },
          }],
        })
        
        // Refresh to get table structure
        const doc = await docsApi(`/v1/documents/${DOC_ID}`)
        let table: any = null
        for (const element of doc.body?.content || []) {
          if (element.table && element.startIndex >= currentIndex) {
            table = element
            break
          }
        }
        
        if (table) {
          // Populate cells (in reverse order for stable indices)
          const allRows = [tableItem.headers, ...tableItem.rows]
          const textRequests: any[] = []
          
          for (let r = 0; r < numRows; r++) {
            for (let c = 0; c < numCols; c++) {
              const cell = table.table.tableRows[r]?.tableCells[c]
              const cellValue = allRows[r]?.[c] || ""
              if (cell?.content?.[0] && cellValue) {
                textRequests.push({
                  insertText: {
                    location: { index: cell.content[0].startIndex },
                    text: cellValue,
                  },
                })
              }
            }
          }
          
          if (textRequests.length > 0) {
            await docsApi(`/v1/documents/${DOC_ID}:batchUpdate`, {
              requests: textRequests.reverse(),
            })
          }
          
          // Style header row
          const styleRequests: any[] = []
          for (let c = 0; c < numCols; c++) {
            styleRequests.push({
              updateTableCellStyle: {
                tableRange: {
                  tableCellLocation: {
                    tableStartLocation: { index: table.startIndex },
                    rowIndex: 0,
                    columnIndex: c,
                  },
                  rowSpan: 1,
                  columnSpan: 1,
                },
                tableCellStyle: {
                  backgroundColor: { color: { rgbColor: COLORS.TABLE_HEADER } },
                },
                fields: "backgroundColor",
              },
            })
          }
          
          if (styleRequests.length > 0) {
            await docsApi(`/v1/documents/${DOC_ID}:batchUpdate`, {
              requests: styleRequests,
            })
          }
          
          // Style header text (white, bold)
          const refreshedDoc = await docsApi(`/v1/documents/${DOC_ID}`)
          let refreshedTable: any = null
          for (const element of refreshedDoc.body?.content || []) {
            if (element.table && element.startIndex >= currentIndex) {
              refreshedTable = element
              break
            }
          }
          
          if (refreshedTable) {
            const headerStyles: any[] = []
            for (let c = 0; c < numCols; c++) {
              const cell = refreshedTable.table.tableRows[0]?.tableCells[c]
              if (cell?.content?.[0]) {
                const start = cell.content[0].startIndex
                const end = cell.content[0].endIndex - 1
                if (start < end) {
                  headerStyles.push({
                    updateTextStyle: {
                      range: { startIndex: start, endIndex: end },
                      textStyle: {
                        foregroundColor: { color: { rgbColor: COLORS.WHITE } },
                        bold: true,
                      },
                      fields: "foregroundColor,bold",
                    },
                  })
                }
              }
            }
            
            if (headerStyles.length > 0) {
              await docsApi(`/v1/documents/${DOC_ID}:batchUpdate`, {
                requests: headerStyles,
              })
            }
          }
        }
        
        // Update current index
        const updatedDoc = await docsApi(`/v1/documents/${DOC_ID}`)
        currentIndex = updatedDoc.body?.content?.slice(-1)[0]?.endIndex - 1 || currentIndex
        
      } else if (item.type === "code") {
        // Insert code block
        const codeText = item.text + "\n\n"
        await insertText(currentIndex, codeText)
        
        // Style as code
        await applyStyles([
          {
            updateTextStyle: {
              range: { startIndex: currentIndex, endIndex: currentIndex + codeText.length - 1 },
              textStyle: {
                weightedFontFamily: { fontFamily: "Roboto Mono" },
                fontSize: { magnitude: 9, unit: "PT" },
                backgroundColor: { color: { rgbColor: { red: 0.96, green: 0.96, blue: 0.96 } } },
              },
              fields: "weightedFontFamily,fontSize,backgroundColor",
            },
          },
        ])
        
        currentIndex += codeText.length
        
      } else {
        // Regular text items (p, bullet, h2, h3)
        const text = item.text + "\n"
        await insertText(currentIndex, text)
        const endIdx = currentIndex + text.length
        
        if (item.type === "h2") {
          await applyStyles([
            {
              updateParagraphStyle: {
                range: { startIndex: currentIndex, endIndex: endIdx },
                paragraphStyle: { 
                  namedStyleType: "HEADING_2",
                  spaceAbove: { magnitude: 18, unit: "PT" },
                  spaceBelow: { magnitude: 8, unit: "PT" },
                },
                fields: "namedStyleType,spaceAbove,spaceBelow",
              },
            },
            {
              updateTextStyle: {
                range: { startIndex: currentIndex, endIndex: endIdx - 1 },
                textStyle: {
                  bold: true,
                  fontSize: { magnitude: 14, unit: "PT" },
                  foregroundColor: { color: { rgbColor: COLORS.HEADING_RED } },
                },
                fields: "bold,fontSize,foregroundColor",
              },
            },
          ])
        } else if (item.type === "h3") {
          await applyStyles([
            {
              updateParagraphStyle: {
                range: { startIndex: currentIndex, endIndex: endIdx },
                paragraphStyle: { 
                  namedStyleType: "HEADING_3",
                  spaceAbove: { magnitude: 14, unit: "PT" },
                  spaceBelow: { magnitude: 6, unit: "PT" },
                },
                fields: "namedStyleType,spaceAbove,spaceBelow",
              },
            },
            {
              updateTextStyle: {
                range: { startIndex: currentIndex, endIndex: endIdx - 1 },
                textStyle: {
                  bold: true,
                  fontSize: { magnitude: 12, unit: "PT" },
                  foregroundColor: { color: { rgbColor: COLORS.HEADING_DARK } },
                },
                fields: "bold,fontSize,foregroundColor",
              },
            },
          ])
        } else if (item.type === "bullet") {
          await applyStyles([
            {
              createParagraphBullets: {
                range: { startIndex: currentIndex, endIndex: endIdx },
                bulletPreset: "BULLET_DISC_CIRCLE_SQUARE",
              },
            },
          ])
        }
        // p type is default paragraph, no special styling needed
        
        currentIndex = endIdx
      }
    }
    
    // Add spacing after section
    await insertText(currentIndex, "\n")
    currentIndex += 1
  }
  
  console.log("Document formatting complete!")
  console.log(`URL: https://docs.google.com/document/d/${DOC_ID}/edit`)
}

main().catch(console.error)
