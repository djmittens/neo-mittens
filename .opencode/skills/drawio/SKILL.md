---
name: drawio
description: Create, generate, or design diagrams, flowcharts, architecture diagrams, ER diagrams, sequence diagrams, class diagrams, network diagrams, or any visual diagram using draw.io. Produces native .drawio files with optional PNG/SVG/PDF export (with embedded XML so exports remain editable in draw.io).
license: Apache-2.0
compatibility: opencode
metadata:
  category: diagramming
  system: drawio
  upstream: https://github.com/jgraph/drawio-mcp/tree/main/skill-cli
---

# Draw.io Diagram Skill

Create and edit draw.io diagrams using the `drawio` tools (`create_diagram`, `read_diagram`, `update_diagram`).

**Data privacy:** Everything runs locally. No diagram data is sent to any external server.

## Workflow

### Creating a new diagram
1. Generate draw.io mxGraphModel XML for the requested diagram
2. Call `create_diagram` with the XML and an output path ending in `.drawio.png`
3. The tool writes a `.drawio` file, exports to PNG, embeds the XML inside the PNG, and cleans up

### Editing an existing diagram
1. Call `read_diagram` with the `.drawio.png` path to extract the current XML
2. Modify the XML as needed
3. Call `update_diagram` with the new XML and the same path

### Review loop
After creating or updating, show the resulting PNG to the user. If they request changes, use `read_diagram` + `update_diagram` to iterate.

## XML format

A `.drawio` file is mxGraphModel XML. Always generate XML directly -- never Mermaid or CSV.

### Basic structure

```xml
<mxGraphModel adaptiveColors="auto">
  <root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
  </root>
</mxGraphModel>
```

- Cell `id="0"` is the root layer, `id="1"` is the default parent
- All diagram elements use `parent="1"` unless inside a container

## XML reference

For the complete draw.io XML reference (styles, edge routing, containers, layers, tags, metadata, dark mode), fetch:
https://raw.githubusercontent.com/jgraph/drawio-mcp/main/shared/xml-reference.md

## CRITICAL rules

- **NEVER include XML comments** (`<!-- -->`) in diagram XML
- Escape special characters: `&amp;`, `&lt;`, `&gt;`, `&quot;`
- Use unique `id` values for each `mxCell`
- Every edge must have a child: `<mxGeometry relative="1" as="geometry" />`
- Use `html=1` in styles when labels contain HTML tags
- Use `&#xa;` or `&lt;br&gt;` for line breaks, never `\n`
