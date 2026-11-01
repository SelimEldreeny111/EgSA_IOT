# Design document verification

Edition: V1.1, 1 November 2026. Requested V1.0 filename retained for existing
references. Runtime source: `f478b47`; flowchart reference: `104cf15`.

| Check | Result |
| --- | --- |
| Original template | EgSA cover/logo and header appearance retained and visually reviewed; Word normalizes some embedded image data on save. |
| Content | Superseded topics, AUX-default wake, one-counter, old packet limits and no-sample-log statements updated. |
| Protobuf | Document tables match every tag/name/type in FlowReading (16), Status_Message (40), CMD_Message (4), Telemetry (51), FlashLogInfo (17) and HistoryInfo (10). |
| Commands | IDs 1-14; internal persistence ACK distinguished from operator actions and optional automatic replies. |
| Tables and tests | 44 sequential table captions; 45 body tables including administrative cover. A01-A34 acceptance procedures with updated feature allocation. |
| Diagrams | Ten embedded charts with F identifiers matching the complete source-verified package. |
| Word fields | Table of contents and page fields refreshed and saved with Microsoft Word. |
| Pagination | 78 physical pages; body labels continue 1-77 after the cover, including A3 landscape pages. |
| Rendering | Packaged render_docx.py diagnosed unavailable LibreOffice. Word supplied the native QA PDF; the packaged rasterize pipeline produced all 78 PNGs from that export. |
| Visual review | All page images inspected. Heading numbering/orphans, new-text font and landscape header placement corrected; updated pages re-rendered and unchanged pages compared by image hash. |
| Structural checks | Schema tables, continuous page labels and page bounds pass; no broken-reference text. |
| Scope | Documentation only. Existing 30 October runtime verification is cited; no new physical qualification claimed. |

QA PDF and page images remain under the ignored temporary directory. The Word
document is the requested release deliverable.
