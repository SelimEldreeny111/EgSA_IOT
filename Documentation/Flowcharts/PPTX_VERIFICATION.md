# Editable PowerPoint flowcharts

Verified on **7 November 2026** against reviewed runtime source
`c604aa6a5a49c61f86bada826a329dc600dac9f6`.

[Open the current editable PowerPoint](output/pptx/WIOT_Project_Flowcharts_Editable_20261107.pptx).
The earlier undated deck remains the prior edition.

| Slides | Content |
| --- | --- |
| 1 | Cover |
| 2 and 3 | F01 through F30 index |
| 4 | Symbols and editing instructions |
| 5 through 34 | Thirty project flows |
| 35 and 36 | Command IDs 1 through 14 |
| 37 and 38 | Supported power combinations and configuration guards |

All 289 diagram nodes contain editable text. The 341 logical arrows are
editable PowerPoint paths. Select named objects in the Selection Pane and
use Edit Points to adjust routes. After moving a node, adjust its arrow
endpoints. Speaker Notes contain source references and implementation conditions.

The package checks verified every node text, all 188 arrow labels, and all
158 cells in the four native command and power tables. The deck contains
zero embedded pictures and uses Arial throughout. Package integrity,
geometry, font validation and Artifact Tool import passed with zero findings.

All 38 slides rendered in Microsoft PowerPoint. A separate copy passed
node text, arrow point and table cell edits, followed by save and reopen.
Visual review covered the changed loop, gateway and WOR diagrams and
the remaining slide layouts.

The final package is **260,844 bytes** with SHA-256
`39b3a651cee47a15cbd49c47cb846cfcb0c8fbd5d9234cfdbd8ab4efbf42a2e2`.

## Regeneration

Use the workspace dependency loader for bundled Node.js and Python paths.
Set RUNTIME_NODE_MODULES, WIOT_PRESENTATION_SKILL_DIR and WIOT_RUNTIME_PYTHON
to the installed runtime. Set WIOT_FINAL_PPTX to a new output filename.

Run these commands from the repository root after reviewing charts.py.

```powershell
python Documentation/Flowcharts/build_flowcharts.py
python Documentation/Flowcharts/prepare_editable_pptx.py prepare
node Documentation/Flowcharts/build_editable_pptx.mjs
python Documentation/Flowcharts/prepare_editable_pptx.py patch
node Documentation/Flowcharts/build_editable_pptx.mjs --finalize
python Documentation/Flowcharts/prepare_editable_pptx.py verify --pptx $env:WIOT_FINAL_PPTX
./Documentation/Flowcharts/check_editable_pptx.ps1 -PresentationPath $env:WIOT_FINAL_PPTX -EditSmokeTest
```

The builder uses the supplied Artifact Tool runtime. Validation preserves
existing output files. Microsoft PowerPoint supplies native rendering and
the edit test. Render and inspect new editions after source changes.
