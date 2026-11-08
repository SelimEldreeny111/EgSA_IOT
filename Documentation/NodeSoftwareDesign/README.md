# STM32 node software design documentation

The [4 November system review](../Validation/WIOT_SYSTEM_REVIEW_20261104.md)
records the current firmware behavior, configuration and verification results.
Use it with the dated design editions below.

[Open the updated Word design](WIOT_STM32_Node_Software_Design_V1.2.docx).

The earlier local edition is preserved. The cover, identifier and revision
history identify the new file as **V1.2, 7 November 2026**. It incorporates
the reviewed runtime source at `c604aa6a5a49c61f86bada826a329dc600dac9f6`
and the refreshed system flowchart definitions.

Scope: the active Arduino STM32F401 node, its selectable LoRa gateway role, and the node/server protocol boundary. ESP32, STM32CubeIDE and server internal implementation are outside this document's scope.

The document preserves the supplied EgSA organization, cover, logo and header.
The identifier is WIOT-NOD-DDS-07-001-V1.2. Reviewer and approval fields are unassigned.

It contains **45 numbered design tables, 35 acceptance procedures and ten
embedded flowcharts**. The diagram appendix uses A3 landscape
pages for readability; the main design remains portrait.

Updated material includes independent WOR sampling and transmission deadlines,
continued Status reporting when sensors fail, direct and regional broadcast
gateway subscriptions, and OFF, LITE and FULL diagnostics. The design covers
separate power/WDT counters and clear commands, UART RX LoRa WOR wake, and the
initial reported 9-mA assembly observation. It describes S25FL064L wiring, capacity,
commit-last sample recovery, elapsed 24-hour retention, memory queries and
acknowledged history export. All six protobuf message tables and command IDs
1-14 match the current protocol. Packet/build budgets, module ownership and test
allocation are updated, with ten core node diagrams in Appendix D and references
to the [complete thirty-chart system package](../Flowcharts/README.md).

[VERIFICATION.md](VERIFICATION.md) records schema checks, Word field refresh,
continuous numbering, retained-template layout and page-image review.
The 4 November integrated regression and firmware builds supply software
evidence. The acceptance procedures identify physical tests to perform on
the deployed boards.

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
