---
name: drawio
description: Create, generate, or design diagrams, flowcharts, architecture diagrams, ER diagrams, sequence diagrams, class diagrams, network diagrams, or any visual diagram using draw.io. Produces native .drawio files with optional PNG/SVG/PDF export (with embedded XML so exports remain editable in draw.io).
license: Apache-2.0
compatibility: Requires Python 3.10+ and `npx draw.io-export` on PATH
metadata:
  category: diagramming
  system: drawio
  upstream: https://github.com/jgraph/drawio-mcp/tree/main/skill-cli
---

# Draw.io Diagram Skill

Create and edit draw.io diagrams using `scripts/drawio.py`. The script handles PNG export (via `npx draw.io-export`) and embeds the source XML into the PNG as a zTXt chunk, so the file is both viewable as an image and editable in draw.io.

**Data privacy:** Everything runs locally. No diagram data is sent to any external server.

## Script Usage

```bash
# Create a new diagram from XML
uv run scripts/drawio.py create --xml '<mxGraphModel>...</mxGraphModel>' -o diagram.drawio.png
uv run scripts/drawio.py create --xml-file diagram.xml -o diagram.drawio.png

# Extract XML from an existing .drawio.png
uv run scripts/drawio.py read diagram.drawio.png

# Update an existing .drawio.png with new XML
uv run scripts/drawio.py update --xml '<mxGraphModel>...</mxGraphModel>' diagram.drawio.png
uv run scripts/drawio.py update --xml-file updated.xml diagram.drawio.png
```

XML can also be piped via stdin (omit `--xml` and `--xml-file`).

## Workflow

### Creating a new diagram
1. Generate draw.io mxGraphModel XML for the requested diagram
2. Write XML to a temp file (or pass via `--xml`)
3. Run: `uv run scripts/drawio.py create --xml-file tmp.xml -o diagram.drawio.png`
4. The script writes a `.drawio` file, exports to PNG, embeds XML into the PNG, and cleans up

### Editing an existing diagram
1. Extract current XML: `uv run scripts/drawio.py read diagram.drawio.png`
2. Modify the XML as needed
3. Write it back: `uv run scripts/drawio.py update --xml-file updated.xml diagram.drawio.png`

### Review loop
After creating or updating, show the resulting PNG to the user. If they request changes, read + update to iterate.

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
