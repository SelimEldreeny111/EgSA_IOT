# STM32 node software design documentation

[Open the updated Word design](WIOT_STM32_Node_Software_Design_V1.0.docx).

The requested legacy filename is retained. The cover, identifier and revision
history identify this edition as **V1.1, 1 November 2026**. It supersedes the
7 October V1.0 contents and incorporates runtime release
`f478b47ecedb108328b9befe762b24b85320c225` plus the system flowchart reference
published in `104cf15`.

Scope: the active Arduino STM32F401 node, its selectable LoRa gateway role, and the node/server protocol boundary. ESP32, STM32CubeIDE and server internal implementation are outside this document's scope.

The document preserves the supplied EgSA organization, cover, logo and header.
The identifier is WIOT-NOD-DDS-07-001-V1.1; reviewer/approval fields remain unassigned.

It contains **78 physical pages, 44 numbered design tables, 34 acceptance
procedures and ten embedded flowcharts**. The diagram appendix uses A3 landscape
pages for readability; the main design remains portrait.

Updated material includes regional MQTT routes, separate power/WDT counters and
clear commands, UART RX LoRa WOR wake, RTC heartbeat/report scheduling, and the
initial reported 9-mA assembly observation. It adds S25FL064L wiring, capacity,
commit-last sample recovery, elapsed 24-hour retention, memory queries and
acknowledged history export. All six protobuf message tables and command IDs
1-14 match the current protocol. Packet/build budgets, module ownership and test
allocation are updated, with ten core node diagrams in Appendix D and references
to the [complete thirty-chart system package](../Flowcharts/README.md).

[VERIFICATION.md](VERIFICATION.md) records schema checks, Word field refresh,
continuous numbering, retained-template layout and page-image review.
Prior runtime regression/build results are cited as existing evidence; this
documentation update does not claim a new hardware test run.

## Regeneration

From a Git checkout containing the pinned original edition and flowchart sources:

```powershell
python Documentation/NodeSoftwareDesign/update_design.py
./Documentation/NodeSoftwareDesign/refresh_word.ps1
```

The builder needs Python, python-docx and Graphviz. The second step requires
Microsoft Word on Windows. It uses a separate hidden instance, updates contents
and page fields, saves the DOCX and exports a QA PDF under ignored `tmp/design`.
Render and inspect all pages after changes. QA PDFs/page images are not release
deliverables.

The builder is an edition-specific revision of the pinned template. Review its
text, source contract and configuration values before regenerating against a
later runtime release. Firmware, server, simulator and private deployment files
are unchanged by this documentation update.
