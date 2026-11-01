# Flowchart verification record

Edition: **1 November 2026**. Software baseline:
`f478b47ecedb108328b9befe762b24b85320c225`.

| Check | Result |
| --- | --- |
| Source traceability | Function/text anchors resolved against 50 source files. SHA-256 hashes match the recorded manifest. No private configuration or secret files are included. |
| Graph structure | All 30 chart definitions have unique node IDs, valid edge endpoints and supported shapes. |
| Rendered editions | 30 SVGs, 30 DOT files and 30 Mermaid files generated from the same definitions used in the HTML and PDF. |
| Printable reference | 34 A3 landscape pages; every chart heading and node label found in extracted PDF text. |
| PDF navigation | 63 internal links; chart index, chart return links and appendix destinations are included. |
| Page bounds | PDF text stays within page boundaries with at least 20 pt horizontal and 10 pt vertical clearance. |
| Diagram type size | Smallest effective node text is 10.50 pt; smallest arrow-label text is 8.65 pt. The builder rejects layouts below its minimum thresholds. |
| Visual review | All 34 pages rendered with Poppler and reviewed in page contact sheets; detailed review also covered the history-transfer and LoRa WOR charts and offline viewer screenshots. |
| Offline browser loading | Opened the HTML directly using a local file URL. All 30 charts loaded, with their nodes, edges, headings and source references present. No external HTTP resources requested. |
| Viewer interactions | Search and empty results, direct chart selection, URL fragments, Previous/Next, zoom, Fit and drag-to-pan passed. |
| Responsive viewer | Checked at 1440 x 1000 and 390 x 844. Toolbar wraps without horizontal page overflow. |
| Browser diagnostics | No page console errors or warnings on the final local-file build. |
| Change scope | Documentation and repository README only. Firmware, server and simulator execution behavior is unchanged. |

The software references and documentation controls were checked for this
edition. This record does not claim new physical sensor, RF, valve, flash
power-cut or electrical measurements; the project's hardware acceptance plans
remain the reference for those tests.
