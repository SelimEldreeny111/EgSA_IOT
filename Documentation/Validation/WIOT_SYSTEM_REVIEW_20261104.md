# WIOT system review and two-node bench guide

Reviewed on **4 November 2026** against the active STM32 Arduino firmware,
Python web server and RS485 simulator sources. This guide covers the current
deployment. The release archive also includes historical verification reports
and separate firmware ports with their own build instructions.

## System paths

| Part | Entry point | Responsibility |
| --- | --- | --- |
| STM32 sensor node | `IoT_Node_Encrypted.ino`, `AppConfig.h`, `AppState.h` | Poll enabled RS485 sensors, acquire battery voltage, service commands and schedule reports and sleep. |
| LoRa link | `LoraLink.cpp`, `AS32_Config.h` | Frame and reassemble encrypted payloads, handle fragment acknowledgements and send WOR wake probes. |
| STM32 gateway | `GatewayApp.cpp`, `MQTT.cpp` | Forward radio Status and Telemetry to scoped MQTT routes. Subscribe to direct and regional broadcast commands and forward validated downlinks. |
| SPI telemetry archive | `TelemetryArchive.cpp`, `TelemetryJournal.cpp`, `S25Fl064l.cpp` | Capture completed samples, verify commits, recover records and serve acknowledged history. The WIOT chip driver uses Arduino `SPI.h`. |
| Python web server | `server_web.py`, `region_topics.py`, `flash_archive.py`, `command_queue.py` | Validate MQTT routes and payloads, correlate command outcomes, persist measurements and archive records, and serve the dashboard. |
| RS485 simulators | Multi-sensor, TUF and Supmea tools under `SENSORS` | Exercise addresses, measurement scaling, absent replies and recovery on the bench. |

The node runs command handling, polling, flash work and transmission
cooperatively. A sample can contain invalid measurement groups and still
produce a Status. An overdue Status gets a turn after the completed cycle
and pending flash write before the next poll starts. Periodic Status prefers
the latest committed sample, carries its acquisition time, and overlays
current operating state. It uses a marked live fallback when no usable stored
sample is available. GOSTM reads the cached snapshot on demand.
[Sensor failure guide](../../Node/IoT_Node_Encrypted/SENSOR_UNAVAILABLE_ZERO_GUIDE.md)

The 8 MiB S25FL064L journal commits records with CRC and a final marker.
The retention generation rolls after 24 elapsed hours with trusted RTC.
FLASH_TODAY selects the current calendar day from the retained generation.
The server stores a history record before sending HISTORY_ACK. Radio fragment
ACKs confirm pieces of a radio transfer, and application ACKs report a command
outcome. Check the appropriate stage when tracing a request.
[Flash architecture and commands](../../Node/IoT_Node_Encrypted/SPI_FLASH_TELEMETRY_GUIDE.md)

## Confirm the firmware on each board

The final-folder header inspected for this review selects Company_1,
Region_1, node ID 3 and sensor ID 3. All four sensor polling flags are false,
SPI logging and automatic command ACKs are enabled, and debug is FULL with
raw frames off. The node uses LoRa WOR and UART RX wake. The startup
defaults are a 10-second sample period and a 15-second send period.
Use the boot log to confirm the settings of each flashed device.

| Setting | Node 2 build | Node 3 build | Gateway build |
| --- | --- | --- | --- |
| Role | `APP_ROLE_SENSOR_NODE` | `APP_ROLE_SENSOR_NODE` | `APP_ROLE_LORA_GATEWAY` |
| Node ID | `APP_NODE_ID=2` | `APP_NODE_ID=3` | Gateway LoRa source is 0 |
| Uplink | `APP_UPLINK_LORA_TO_GATEWAY` | `APP_UPLINK_LORA_TO_GATEWAY` | LoRa bridge with IP MQTT |
| Controller and LoRa for WOR test | `LORA_WOR` and `WAKE_ON_RADIO` | `LORA_WOR` and `WAKE_ON_RADIO` | Controller and radio NORMAL at rest |
| Gateway wake probe | | | `APP_LORA_GATEWAY_WOR_TX=1` |

Use the same LoRa channel, air rate, UART settings, network ID and radio
configuration across the three units. Use the same company, region and
application key for this bench. The gateway's MQTT client ID must be unique
among connected broker clients. On a sensor-node build, the LoRa UART is
STM32 RX PA12 and TX PA11. On a gateway, LoRa is RX PA10 and TX PA9, and the
modem uses RX PA12 and TX PA11. The LoRa AUX input and the valve STBY output
share PC13. The LoRa profile inhibits the valve output through its pin guard.
[Pin and setup reference](../../Node/IoT_Node_Encrypted/README.md)

For the schedule-driven WOR profile, SRATE and STRAN set independent
deadlines. `APP_POWER_SLEEP_SECONDS` is used for the legacy combined WOR
cycle when application scheduling is disabled. The RTC heartbeat services
IWDG during long idle periods. Send STIME to establish RTC trust before
testing sleep or archive retention.
[WOR scheduling and wake checks](../../Node/IoT_Node_Encrypted/LORA_WOR_APP_SCHEDULE_GUIDE.md)

## Trace a command or missing Status

1. Reset the two sensor boards and label the serial ports from
   `boot role=SENSOR node=2` and `boot role=SENSOR node=3`.
2. Send a direct GOSTM to node 3 on
   `wiot/Company_1/Region_1/3/cmd`. On node 3, match `command_rx` and
   `reply_tx` by request ID. On the gateway, check `command_forwarded`
   and then an uplink from source 3. Confirm the server received the reply
   on `wiot/Company_1/Region_1/3/data`. Repeat for node 2.
3. In FULL logging, the other node can show a target mismatch after hearing
   the same downlink. An overheard fragment or a reassembly timeout belongs
   to the source and message ID on that line. Use the addressed node's
   console and server request ID to confirm the GOSTM.
4. Test an intentional regional GOSTM broadcast on
   `wiot/Company_1/Region_1/broadcast`. The gateway now subscribes to this
   exact route in addition to `wiot/Company_1/Region_1/+/cmd`. Check the
   returned reply separately for each node.
5. For the offline sensor test, enable Supmea and Sondas, establish trusted
   RTC and confirm the flash log is Ready. Stop both sensor replies. Wait
   for a completed poll, flash commit or live fallback, and a new Status on
   `.../{node}/status`. Sensor values should be zero and validity flags
   false. In a separate test, disable all four polling flags. The sensor
   mask should be zero for a fresh sample, and Status should continue.
6. For a node that answers while awake only, verify the gateway build's
   WOR TX flag and compare the node's wake and receive logs. If the node
   logs a transmit attempt, check the gateway uplink and then the server
   receipt timestamp to locate the next failure boundary.

LITE retains boot identity, command and report events, and critical errors.
Use FULL when you need sensor timeouts, radio fragments or sleep snapshots.
OFF suppresses serial diagnostics. Command ACK policy has its own switch.
[Debug settings](../../Node/IoT_Node_Encrypted/DEBUG_LOGGING_GUIDE.md) ·
[Topic contract](../../Node/IoT_Node_Encrypted/REGIONAL_MQTT_TOPICS_GUIDE.md)

## Review results

| Check | Evidence |
| --- | --- |
| Host release check | All ten node suites, Python server and three simulator suites, dashboard JavaScript and cross-component contract tests passed. |
| Gateway change | A host test runs the production MQTT setup and callback. It checks both subscription strings, forwarding of direct and broadcast commands, rejection of wrong targets and regions, and reconnect behavior on broadcast subscription failure. |
| Firmware builds | Gateway WOR, sensor WOR, direct SIM and direct Wi-Fi compiled. The matrix checked that load sections end below the reserved EEPROM sector. The working node 3 configuration also compiled. |
| Source agreement | Checked the active node, server, simulator and cross-component sources in the final copy against the release baseline. The differences were in the local node configuration. |
| Bench acceptance | The checks above use host fixtures and compile verification. Use the physical sequence in this guide to confirm radio delivery, flash behavior and wake on the deployed boards. |

Use `Validate-Release.ps1 -UseFactoryConfigurationFixture` with the installed
Python, g++ and Node.js tools to reproduce the host checks. This branch carries
commissioned valve values, so the fixture uses compile-time test overrides to
exercise inhibited factory settings. The plain factory assertion fails with
those commissioned values. The fixture preserves the local header.
See the repository's `RELEASE_GUIDE.md` for tool and configuration setup.
