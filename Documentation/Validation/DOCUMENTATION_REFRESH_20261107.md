# WIOT documentation refresh

Reviewed on **7 November 2026** against runtime commit
`c604aa6a5a49c61f86bada826a329dc600dac9f6`.

## Current deliverables

- [Word software design V1.2](../NodeSoftwareDesign/WIOT_STM32_Node_Software_Design_V1.2.docx) preserves the EgSA template and uses a separate filename alongside the locally edited earlier edition.
- [Editable detailed flowcharts](../Flowcharts/output/pptx/WIOT_Project_Flowcharts_Editable_20261107.pptx) contain thirty flows and command and power tables in 38 slides.
- [Simple editable overview V2.1](../SystemOverview/output/WIOT_Software_Overview_Simple_v2.1.pptx) provides the opening architecture view and representative deployment illustration.
- [Offline flowchart viewer](../Flowcharts/WIOT_Project_Flowcharts.html) and [printable reference](../Flowcharts/output/pdf/WIOT_Project_Flowcharts.pdf) use the same chart definitions.

## Updated behavior descriptions

Default LoRa WOR uses independent SRATE and STRAN deadlines. The RTC heartbeat
services the IWDG and returns to Stop when no work is due. Stop residence ages
the application task clocks through RTC elapsed time. The legacy combined
sleep cycle is available with APP_LORA_WOR_USE_APP_SCHEDULE=false.

After a completed acquisition, the application gives an overdue Status an
opportunity before starting another poll cycle. Failed sensor groups report
zero with invalid quality. Disabling all polling flags still permits reports
with a zero sensor mask. Command and pending flash work retain priority.

The gateway subscribes to the regional node-command wildcard and the regional
broadcast topic. Both routes share scope validation and command forwarding.
A failed subscription write schedules MQTT reconnect.

The Word design describes OFF, LITE and FULL diagnostics and raw frame dumps.
The command ACK switch remains independent. Its acceptance appendix includes
two-node routing, independent WOR deadlines, unavailable sensors and debug
comparisons. The document distinguishes public defaults from the inspected
node 3 bench configuration.

## Verification

The six protobuf tables match every deployed tag, name and type. The Word
design has 45 numbered tables, 35 acceptance procedures and ten embedded
node diagrams. Microsoft Word refreshed its contents and page fields.
Native Word supplied the QA PDF because the packaged renderer could not find
LibreOffice on PATH. The packaged rasterizer produced page images for review.

The diagram builder verified all source anchors and SHA-256 values against
50 public files. The 34-page PDF contains every chart node label. Both
PowerPoint packages passed integrity, geometry, font and Artifact Tool import
checks. Microsoft PowerPoint rendered all slides and passed text and arrow
editing tests in separate copies. The detailed deck also passed native table
editing and exact node, arrow label and table-cell comparisons.

The [4 November system review](WIOT_SYSTEM_REVIEW_20261104.md) records the
integrated runtime tests and firmware builds. The current changes update
documentation. Physical sensor, RF, current and interruption acceptance use
the existing bench procedures.
