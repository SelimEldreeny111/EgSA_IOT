# Flowchart verification record

Edition **7 November 2026** describes reviewed runtime source
`c604aa6a5a49c61f86bada826a329dc600dac9f6`.

| Check | Result |
| --- | --- |
| Source references | All anchors resolve against 50 public source files. SHA-256 values match source_manifest.json. |
| Graph structure | All 30 definitions have unique node IDs and valid edge endpoints. |
| Generated editions | Offline HTML, Markdown, DOT, Mermaid, SVG, PDF and editable PowerPoint use the shared definitions. |
| PDF | 34 A3 landscape pages. The builder finds every chart heading and node label in extracted PDF text. |
| Diagram type | Minimum effective node text is 10.50 pt and arrow text is 8.65 pt. |
| Current behavior | F04 includes overdue Status priority. F14 includes both gateway subscriptions. F22 follows independent SRATE and STRAN deadlines by default. |
| PowerPoint | All 38 slides rendered in Microsoft PowerPoint. Native node, arrow and table editing passed in a separate copy. Package and geometry checks reported zero findings. |
| Runtime evidence | The 4 November review records software tests and firmware compilation. Physical acceptance uses the feature test plans. |

The [PowerPoint verification record](PPTX_VERIFICATION.md) identifies the
editable package and its digest. The [Word design](../NodeSoftwareDesign/README.md)
embeds ten core node diagrams from these definitions.
