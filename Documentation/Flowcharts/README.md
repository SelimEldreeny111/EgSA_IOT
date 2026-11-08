# WIOT software flowcharts

Use the [4 November system review](../Validation/WIOT_SYSTEM_REVIEW_20261104.md)
alongside these charts for the current gateway subscriptions, overdue Status
priority and two-node bench checks. WOR follows independent SRATE/STRAN
deadlines when application scheduling is enabled.

For a single large architecture chart and realistic deployment illustration,
see the [system overview](../SystemOverview/README.md), also available in editable PowerPoint.

Reviewed on **7 November 2026** against the active Arduino STM32 release,
commit `c604aa6a5a49c61f86bada826a329dc600dac9f6`. The diagrams describe the
implemented behavior in that release. Source file hashes and verified function
locations are recorded in [source_manifest.json](source_manifest.json).

Open the [offline interactive viewer](WIOT_Project_Flowcharts.html) to search,
zoom and pan through the charts. It works directly from disk without a server
or internet connection. Use the [34-page printable reference](output/pdf/WIOT_Project_Flowcharts.pdf)
for review or printing at A3 landscape. Its index and bookmarks jump to each
chart. Both editions contain the same **30 flowcharts**.

An [editable PowerPoint edition](output/pptx/WIOT_Project_Flowcharts_Editable_20261107.pptx)
contains all 30 flows in a 38-slide deck, with an index, symbol guide and four
editable command/power tables. Nodes, their text and routed arrows are native
PowerPoint objects. Detailed notes and code references are in Speaker Notes.
Use **Shape Format > Edit Shape > Edit Points** to adjust arrow routes. After
moving a node, adjust its incoming/outgoing arrow endpoints separately.
See [PowerPoint build and verification](PPTX_VERIFICATION.md) for regeneration
and the checks performed.

## Chart catalog

| ID | Flow |
| --- | --- |
| F01 | Whole system data and control paths |
| F02 | Compiled role, transport, sensors and configuration |
| F03 | Boot, reset causes and initialization |
| F04 | Sensor node main loop and command priority |
| F05 | Shared RS485 request, response, validation and failures |
| F06 | TUF live values and meter-native day/month/year totals |
| F07 | Supmea live values and cumulative totals |
| F08 | HNDA and Sondas soil measurements |
| F09 | Supmea RTC consumption and calendar boundaries |
| F10 | Telemetry assembly, validity and failed-sensor zeros |
| F11 | Direct WiFi/SIM MQTT send and receive priorities |
| F12 | Connection retries, modem reset and controller recovery |
| F13 | LoRa framing, fragmentation, ACKs and reassembly |
| F14 | Gateway uplink and command forwarding |
| F15 | Server command intent, delivery and execution tracking |
| F16 | Node command validation, replay handling and optional replies |
| F17 | Commissioned solenoid polarity pulse and output cutoff |
| F18 | Watchdog behavior, reset causes and reset counters |
| F19 | Power policy selection and supported combinations |
| F20 | Remote wake with a normal connected modem |
| F21 | Periodic/queued RTC Standby and boot handoff |
| F22 | LoRa wake on radio, UART RX wake and STM32 Stop |
| F23 | External flash sample capture and committed writes |
| F24 | Flash recovery, elapsed 24-hour retention and clear |
| F25 | Stored history transfer and server persistence ACK |
| F26 | Server MQTT ingestion, validation and database storage |
| F27 | Server accounts, access scope, dashboard and reports |
| F28 | Shared-bus four-sensor simulator and independent RTC oracle |
| F29 | Verification, documentation and release workflow |
| F30 | Active STM32 release and separate ESP32/CubeIDE ports |

The PDF also includes a command catalog for IDs 1-14 and a supported power
combination matrix. Chart notes record behavior that would otherwise be easy
to misread, including these points:

- Supmea consumption follows changes in its cumulative forward volume. TUF
  provides its own period totals.
- The RTC schedules wakeups. The watchdog resets a stalled controller; it is
  not the normal wake timer.
- Default WOR uses independent SRATE and STRAN deadlines. A heartbeat services
  the watchdog and returns to Stop when no application work is due.
- A completed sensor cycle gives an overdue Status a turn before another
  acquisition starts. Failed and disabled sensor groups still permit reports.
- The gateway subscribes to both the regional direct-command wildcard and
  regional broadcast route.
- LoRa WOR uses UART RX as the controller wake input in the current default
  configuration. AUX remains the radio readiness signal.
- The flash log clears after **24 elapsed hours**, rather than at midnight.
  The "today" request filters the currently retained batch by the node's
  calendar day.
- Valve telemetry reports the commanded software state. The driver has no
  physical valve-position sensor.
- The gateway and the alternate ESP32/CubeIDE ports have their own role and
  feature boundaries. F30 shows those boundaries explicitly.

## Reading the charts

Dark blue blocks mark an entry or result, blue blocks describe processing,
amber diamonds represent decisions, green cylinders represent stored data,
and pink blocks mark failures or rejections. Purple blocks refer to another
feature or flow. Dashed arrows return to an earlier phase or cross an already
placed peer; they do not imply a background thread. Each chart summarizes a
functional path across relevant functions rather than expanding every helper
into a separate box.

In the viewer, use the sidebar or search field to find a chart. Drag to pan,
use the mouse wheel or +/- controls to zoom, and press **Fit** to restore the
full chart. Keyboard shortcuts inside the chart are **+**, **-** and **F**.
Previous/Next follow the numbered sequence. Each chart has download links for
its SVG, DOT and Mermaid source.

The source paths below each chart resolve relative to the repository root.
The PDF shortens the long directory names using these aliases:

| PDF alias | Repository directory |
| --- | --- |
| `Node/` | `Node/IoT_Node_Encrypted/` |
| `Server/` | `Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard/` |
| `MultiSensor/` | `SENSORS/Multi Sensor RS485 Simulator/` |
| `ESP32/` | `esp32/IoT_Node_ESP32/` |
| `CubeIDE/` | `WIOT_STM32CubeIDE/` |

## Editable sources and regeneration

- [charts.py](charts.py): shared node, arrow, note and source definitions.
- [build_flowcharts.py](build_flowcharts.py): validates references and builds
  the vector PDF, SVGs, viewer, source files and manifest.
- [viewer_template.html](viewer_template.html): offline viewer layout and controls.
- [source](source/): individual Graphviz DOT and Mermaid files.
- [svg](svg/): scalable diagrams for insertion into other documents.
- [Combined Mermaid reference](WIOT_Project_Flowcharts.md): all charts and notes.
- [Verification record](VERIFICATION.md): actual checks performed for this edition.

Install Python with `reportlab` and `pypdf`, and install Graphviz with its
`dot` command on PATH. From the repository root, run:

```powershell
python Documentation/Flowcharts/build_flowcharts.py
```

For a separate output directory or a Graphviz installation outside PATH:

```powershell
python Documentation/Flowcharts/build_flowcharts.py `
  --output "D:/WIOT_Flowcharts" `
  --dot "C:/Program Files/Graphviz/bin/dot.exe"
```

The builder rejects missing source anchors, invalid graph edges and missing
PDF text. It selects the more readable of vertical and horizontal layouts,
records effective font sizes in [layout_report.json](layout_report.json),
and keeps temporary files under `tmp/pdfs`. Review rendered pages after edits;
source verification alone does not check arrow routing or page layout. Update
the baseline/date and review the flow definitions when software behavior changes.

This documentation update does not change firmware, server or simulator behavior.
