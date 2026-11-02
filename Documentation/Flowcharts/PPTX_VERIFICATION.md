# Editable PowerPoint flowcharts

Verified **2 November 2026**. This deck converts the existing flowchart reference
for source baseline `f478b47ecedb108328b9befe762b24b85320c225`. The reference's
1 November edition date remains on the cover. No firmware, server, sensor
simulator, deployment settings or secrets were changed.

## Deliverable and editing

[Open the editable PowerPoint](output/pptx/WIOT_Project_Flowcharts_Editable.pptx).

| Slides | Content |
|---|---|
| 1 | Cover |
| 2–3 | F01–F30 index and slide numbers |
| 4 | Symbols and editing instructions |
| 5–34 | All 30 project flows, one per slide |
| 35–36 | Command IDs 1–14 |
| 37–38 | Supported and rejected power combinations |

All diagram nodes contain editable text. The arrows are editable PowerPoint
freeform paths, with their original route and arrow direction preserved.
Use **Shape Format > Edit Shape > Edit Points** to adjust a route. After moving
a node, adjust its arrow endpoints separately. The simple cover links are
attached straight connectors. No flowchart is a screenshot or embedded SVG.

Open **Home > Select > Selection Pane** to select named objects, such as
`F22 node a`, `F22 edge 01` or its branch label. Speaker Notes retain each
chart's purpose, implementation caveats, source paths and function anchors.
Use **Save As** to keep a personal edited copy. Diagrams and code do not
automatically synchronize after manual PowerPoint edits.

## Checks completed

- All 38 slides opened and rendered at 1920 × 1080 in installed Microsoft
  PowerPoint. Every rendered slide was inspected individually, including
  the corrected branch-label spacing and multiline labels.
- All 289 flowchart node texts and 188 arrow-label texts exactly match the
  shared chart definitions. All 341 logical arrows remain editable paths.
- All 158 cells in the four native command/power tables match their source
  values. All chart source references are present in Speaker Notes.
- Package integrity and slide/font/layout validation passed with zero
  findings and zero warnings. The deck also passed Artifact Tool import.
- A separate copy passed a PowerPoint editing test: change/restore node
  text, change/restore an arrow path point, edit/restore a table cell, save,
  close and reopen. The delivered file was not changed by that test.
- There are zero embedded pictures. All visible text uses Arial.

Final file: **260,325 bytes**. SHA-256:

```text
b859d11ea8d3d9af82f1ebb7f19d7a9f74705bb9c65cc9000744f524203726ee
```

Native PowerPoint was the visual acceptance application. Custom freeform
arrow rendering can differ in other presentation viewers. This is a document
conversion, not new hardware or software behavior validation.

## Regeneration

The authoring source uses `@oai/artifact-tool` from the supplied Codex Node.js
runtime. `prepare_editable_pptx.py` reads the existing Graphviz DOT layouts and
shared chart definitions, then adds native arrowheads and checks the exported
package. Graphviz, Python and the existing flowchart builder dependencies must
be available. Microsoft PowerPoint is needed only for native rendering and
the optional edit test.

Run from the repository root. Adapt bundled paths if the runtime moves:

```powershell
$pptNode = 'C:/Users/Selim/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
$pptPython = 'C:/Users/Selim/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$env:RUNTIME_NODE_MODULES = 'C:/Users/Selim/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'

# Choose a NEW output path when regenerating; validation preserves existing files.
$env:WIOT_FINAL_PPTX = Join-Path $PWD 'Documentation/Flowcharts/output/pptx/WIOT_Project_Flowcharts_Editable_Revision2.pptx'

& $pptPython Documentation/Flowcharts/prepare_editable_pptx.py prepare
& $pptNode Documentation/Flowcharts/build_editable_pptx.mjs
& $pptPython Documentation/Flowcharts/prepare_editable_pptx.py patch
& $pptNode Documentation/Flowcharts/build_editable_pptx.mjs --finalize
& $pptPython Documentation/Flowcharts/prepare_editable_pptx.py verify --pptx $env:WIOT_FINAL_PPTX
& Documentation/Flowcharts/check_editable_pptx.ps1 -PresentationPath $env:WIOT_FINAL_PPTX -EditSmokeTest
```

The skill path and Python executable can also be supplied through
`WIOT_PRESENTATION_SKILL_DIR` and `WIOT_RUNTIME_PYTHON`. Intermediate layouts,
draft packages, validation receipts, editing-test copies and rendered PNGs
stay under the ignored `tmp/pptx` directory. Inspect the new renders before
delivering a regenerated deck.
