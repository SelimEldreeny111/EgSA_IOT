# Design document verification

Edition **V1.2, 7 November 2026** uses a separate file to preserve local edits
in the earlier V1.0 filename.
Reviewed runtime source is `c604aa6a5a49c61f86bada826a329dc600dac9f6`.

| Check | Result |
| --- | --- |
| Template | The EgSA cover, logo, header and page system follow the retained design document. |
| Current behavior | Updated independent WOR scheduling, overdue Status priority, gateway subscriptions and debug choices. |
| Protobuf | Six document tables match every deployed field tag, name and type. FlowReading has 16 fields, Status 40, CMD 4, Telemetry 51, FlashLogInfo 17 and HistoryInfo 10. |
| Tables | 45 continuous numbered captions and 46 body tables including the cover. |
| Acceptance | Procedures A01 through A35 cover existing features and current scheduling, offline reporting and debug checks. |
| Diagrams | Ten embedded node diagrams use the shared definitions. Long note sets use smaller figures to keep diagrams and notes together. |
| Word fields | Microsoft Word refreshed contents and page fields and exported the QA PDF. |
| Rendering | The packaged DOCX renderer reported missing LibreOffice on PATH. Native Word supplied the QA PDF and the packaged rasterizer produced page images. |
| Layout | Reviewed rendered pages, widened the debug macro column and removed redundant text that created sparse pages. |
| Runtime evidence | The 4 November release checks and builds are recorded software evidence. Hardware acceptance follows Appendix A. |

QA PDFs, page images and machine-readable checks stay under the ignored tmp
directory. The Word document is the design deliverable.
