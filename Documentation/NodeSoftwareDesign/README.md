# STM32 node software design documentation

`WIOT_STM32_Node_Software_Design_V1.0.docx` is the full node design definition and justification document, dated 7 October 2026.

Scope: the active Arduino STM32F401 node, its selectable LoRa gateway role, and the node/server protocol boundary. ESP32, STM32CubeIDE and server internal implementation are outside this document's scope.

The document adapts the supplied EgSA DDS example's organization, cover and header. The proposed identifier is WIOT-NOD-DDS-07-001-V1.0; reviewer and approval fields remain unassigned. It is an engineering review edition, not a qualification certificate.

It contains 59 physical pages, 40 numbered design tables, full deployed protobuf field maps, configuration and power combination tables, 26 individual test procedures, a public module interface reference and troubleshooting guidance. It distinguishes existing regression evidence from hardware acceptance that remains to be performed.

Document QA: Microsoft Word field refresh and PDF export, canonical document rasterization, page-by-page visual review, contents/page numbering checks and template package preservation checks. The source example remains unchanged. Private deployment keys and passwords are not reproduced. QA render images and intermediate PDFs are not release deliverables.

The inspected working baseline is `WIOT_Final_PowerModes_20261001/Node/IoT_Node_Encrypted`, including the 5 October schedule-driven remote-wake update. The documentation release makes no firmware or server changes. Later code/configuration updates require document review and renewed verification.
