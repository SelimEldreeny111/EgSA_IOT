# WIOT system overview

## Simple overview v2.0 - recommended for presentations

Use this edition to explain the project to a general audience. One page contains five stages: **Sensors -> STM32 node -> Connection -> Python server -> Dashboard**. A single purple return path explains commands. Four supporting services summarize measurement/time handling, flash storage, automatic recovery and power management.

- [Editable PowerPoint v2.0](output/WIOT_Software_Overview_Simple_v2.0.pptx): simple overview on slide 1 and the existing realistic system illustration on slide 2.
- [Large simple overview PNG](output/WIOT_Software_Overview_Simple_v2.0.png): 6400 x 3600 pixels.
- [Simple overview SVG](output/WIOT_Software_Overview_Simple_v2.0.svg): vector text, shapes and icons.

Main-stage text uses plain language. Protocol details, power-mode limits, sensor-total distinctions and source references are retained in slide 1 Speaker Notes. The Connection stage groups the selected link, optional LoRa gateway and MQTT exchange. The purple line is a conceptual command route through the server and the same connection, rather than a direct physical browser-to-node link.

Blocks, text, icons and arrows are native editable PowerPoint objects. Select them by name in the Selection Pane; use Edit Points for routed arrows and adjust endpoints after moving blocks. The second slide remains an embedded representative illustration.

Regenerate using `build_simple_overview.mjs`, `prepare_simple_overview.py patch`, `build_simple_overview.mjs --finalize`, `prepare_simple_overview.py verify`, and `check_simple_overview.ps1 -EditSmokeTest`, with the runtime configuration described below. Set `WIOT_SIMPLE_PPTX` to a new filename for a later revision. Actual verification is recorded in [SIMPLE_OVERVIEW_VERIFICATION.md](SIMPLE_OVERVIEW_VERIFICATION.md).

## Detailed architecture v1.0

The earlier detailed edition remains available as an engineering reference. It is not the recommended opening view for a general audience. Both editions describe the same Arduino STM32 architecture, prepared on 2 November 2026.

- [Editable PowerPoint](output/WIOT_System_Architecture_Overview_v1.0.pptx): slide 1 is one large architecture flowchart; slide 2 is the deployment illustration.
- [Large flowchart PNG](output/WIOT_Software_Architecture.png): 6400 x 3600, suitable for zooming or insertion in a document.
- [Scalable flowchart SVG](output/WIOT_Software_Architecture.svg): vector shapes and text.
- [Realistic system illustration](output/WIOT_Node_Gateway_Server_Illustration.png): two field nodes, LoRa gateway, MQTT broker and server/dashboard.

The illustration was generated with the built-in Image Generation tool. It shows the topology and representative hardware; it is not a photograph of the actual PCB or an electrical wiring reference. The complete final generation prompt is preserved in [image_prompt.txt](image_prompt.txt).

## What the flowchart covers

The single page follows the field interfaces, STM32 application, selected communications route and server. It includes all four independently enabled RS485 sensor types, per-sensor addresses and failure validity, the bench simulator, valve actuation, battery ADC, boot/recovery, command priority, sampling, flash commit and retrieval, protobuf/AES framing, LoRa fragmentation and gateway forwarding, direct WiFi/SIM MQTT, server validation, databases, dashboard and command tracking.

Supporting services include Supmea RTC consumption, TUF native period totals, hardware watchdog progress checks, reset counters, network retry recovery, power policies and radio wake. It is a functional architecture overview, rather than an exhaustive function call graph or wiring diagram. The existing [30 detailed flowcharts](../Flowcharts/README.md) retain the individual state-machine details.

Blue arrows show measurements/transport; purple arrows show commands/results; dashed arrows show a bench or supporting-service connection. Double arrowheads show bidirectional exchange. Line crossings without a junction do not join paths. A node build selects direct IP **or** LoRa; the gateway does not perform field sensor polling or maintain a local sample archive.

RTC alarms schedule normal wakeups. IWDG expiry resets the controller. LoRa WOR requires a normal gateway with `APP_LORA_GATEWAY_WOR_TX=1`; the node wakes on UART RX in the current default policy, while AUX remains a readiness input. The probe can lose its first bytes during clock restoration; the following command is the executable message. WOR uses `APP_POWER_SLEEP_SECONDS` for its report cycle; independent SRATE/STRAN scheduling belongs to schedule-driven REMOTE_WAKE.

Flash retention is 24 elapsed hours. `FLASH_TODAY` filters the retained batch by calendar day. A valve acknowledgement confirms the software pulse, without measuring physical position. Sondas register configuration must match the purchased probe. ESP32 and CubeIDE ports are separate snapshots and are outside this active Arduino architecture.

## Edit and regenerate

Use PowerPoint's Selection Pane to select named blocks and arrows. Text, boxes and arrow paths on slide 1 are native objects. Use **Shape Format > Edit Shape > Edit Points** for routed arrows; adjust their endpoints after moving boxes. Slide 2 contains an embedded raster illustration.

The shared layout and source references are in [build_overview.mjs](build_overview.mjs). The builder uses the bundled `@oai/artifact-tool` runtime and Arial. Set `RUNTIME_NODE_MODULES`, `WIOT_RUNTIME_PYTHON` and `WIOT_PRESENTATION_SKILL_DIR` for another machine, then run from the repository root:

```powershell
node Documentation/SystemOverview/build_overview.mjs
python Documentation/SystemOverview/prepare_overview.py patch
node Documentation/SystemOverview/build_overview.mjs --finalize
python Documentation/SystemOverview/prepare_overview.py verify
powershell -File Documentation/SystemOverview/check_overview.ps1 -EditSmokeTest
```

The finalizer refuses to overwrite an existing final deck; use a new output path for a revision. The finalizer checks package integrity, layout, fonts and first-party import. The additional verifier checks native text and freeform arrow geometry. The PowerPoint check renders both slides and tests text/arrow editing in a separate copy. See [VERIFICATION.md](VERIFICATION.md) for the checks actually completed for this edition.

Firmware, server and simulator behavior are unchanged by this documentation release. Sources are recorded in slide 1 Speaker Notes; the source baseline is `b4fc108519d870491c5fd97b3aaef808378e3928`.
