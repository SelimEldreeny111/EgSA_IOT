# WIOT software flowcharts

Reviewed 1 November 2026. Active source baseline `f478b47ecedb108328b9befe762b24b85320c225`.

The HTML viewer and printable PDF contain the same thirty graphs. Source locations are verified against the code.

## F01 Whole system data and control paths

One sensing architecture supports direct IP nodes and LoRa nodes behind a gateway. Commands travel back through the selected route.

```mermaid
flowchart TD
  s["TUF / Supmea / HNDA / Sondas<br/>One shared RS485 bus"]:::proc
  n["STM32 Arduino sensor node<br/>Acquire, validate and schedule"]:::proc
  f[("External SPI telemetry log<br/>Complete samples / 24 h batches")]:::db
  v["TB6612FNG valve driver<br/>Commanded state only"]:::proc
  ip["ESP8266 or SIM800L<br/>Direct MQTT route"]:::proc
  r["E32 / AS32 LoRa node<br/>Reliable radio frames"]:::proc
  g["LoRa gateway<br/>LoRa + WiFi / SIM uplink"]:::proc
  b[("MQTT broker<br/>Company / region / node topics")]:::db
  w["Python web server<br/>Decrypt, validate, store, command"]:::proc
  u(["Browser dashboard<br/>Live data / commands / history"]):::term
  s -->|Measurements| n
  n -->|Store| f
  f -->|Latest sample| n
  n -->|Valve command| v
  n --> ip
  n --> r
  r -->|Radio| g
  g -->|Commands| r
  ip --> b
  b -->|Commands| ip
  g --> b
  b -->|Commands| g
  b --> w
  w -->|Commands| b
  w --> u
  u -->|Operator intent| w
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- The gateway forwards the encrypted node payload; the server decodes it. LoRa-only nodes do not use their IP-modem path.
- Solid arrows show functional data/control direction. All subsequent charts describe software behavior, not a new hardware wiring diagram.

Sources: Node/IoT_Node_Encrypted.ino:189; Node/src/app/GatewayApp.cpp:54; Server/server_web.py:987

## F02 Choose the compiled product

Build-time macros decide the role, active transport, sensor requests, addresses and power policy before any hardware is used.

```mermaid
flowchart TD
  a(["Read AppConfig.h<br/>Private deployment files stay local"]):::term
  b{"Which role?"}:::dec
  c["Sensor node<br/>APP_ROLE_SENSOR_NODE"]:::proc
  d["Gateway<br/>No sensor polling or local archive"]:::proc
  e{"Direct IP or LoRa uplink?"}:::dec
  f["WiFi or SIM modem<br/>One selected external modem"]:::proc
  g["LoRa node -&gt; gateway<br/>Use role-specific UART pins"]:::proc
  h["Select each sensor true / false<br/>Choose unique addresses 1..247"]:::proc
  i{"Compile-time guards<br/>Check modes, pins and buffers"}:::dec
  j(["Build the selected firmware"]):::term
  k["Reject invalid configuration<br/>Correct it before flashing"]:::bad
  a --> b
  b -->|Node| c
  b -->|Gateway| d
  c --> e
  c --> h
  e -->|Direct| f
  e -->|LoRa| g
  d -->|IP uplink + LoRa| f
  f --> i
  g --> i
  h --> i
  i -->|Valid| j
  i -->|Invalid| k
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- All four sensors can be enabled together. There is no longer a mandatory exclusive two-sensor project selection.
- Current public snapshot: node 2, Company_1 / Region_1, LoRa WOR with UART RX wake, all four sensors and SPI logging enabled.

Sources: Node/src/config/AppConfig.h:185; Node/src/config/AppConfig.h:426

## F03 Boot and reset initialization

Safety and the Standby handoff run before the IWDG; normal active initialization then selects the node or gateway path.

```mermaid
flowchart TD
  a(["Power / reset / RTC Standby exit"]):::term
  b["Safe valve pins when available<br/>Snapshot RCC / Standby cause"]:::proc
  c{"Valid pending sleep handoff?"}:::dec
  d["Enter / continue RTC Standby<br/>Before arming the IWDG [F21]"]:::ref
  e["Classify cause, update counters<br/>Arm hardware WDT [F18]"]:::proc
  f["Sensor node setup_Init<br/>RTC, ADC, transport and sensors"]:::proc
  g["Gateway setup<br/>LoRa and IP / MQTT only"]:::proc
  h["Begin archive recovery<br/>Initialize power manager"]:::proc
  i(["Install command-service hook<br/>Enter cooperative loop"]):::term
  a --> b
  b --> c
  c -->|Yes, deadline future| d
  d -->|RTC wake| a
  c -->|No / elapsed| e
  e -->|Node| f
  e -->|Gateway| g
  f --> h
  g --> h
  h --> i
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- The default RTC date is not proof of trusted time. STIME establishes validated UTC time for calendar totals and flash retention.
- The IWDG protects active startup calls as well as loop execution. A valid long Standby handoff deliberately occurs before it starts.

Sources: Node/IoT_Node_Encrypted.ino:189; Node/src/app/IoT_Node.cpp:441; Node/src/power/PowerManager.cpp:759

## F04 Sensor node cooperative main loop

Commands and replies precede sampling, routine uploads and bulk history. One enabled sensor is serviced per application pass.

```mermaid
flowchart TD
  a(["Loop progress checkpoint<br/>Remote idle gate if selected"]):::term
  b["Pump commands and replies<br/>MQTT or LoRa [F11 / F16]"]:::proc
  c["Advance flash state machine<br/>Check power / command priority"]:::proc
  d{"Sample due or cycle active?"}:::dec
  e["Poll one enabled sensor<br/>Finish all groups [F05-F09]"]:::proc
  f{"Complete snapshot?"}:::dec
  g["Queue canonical flash sample<br/>No half-finished sensor cycle"]:::proc
  h{"Routine transmit due and safe?<br/>No sensor / write / reply pending"}:::dec
  i["Publish latest stored Status<br/>Explicit live fallback [F10]"]:::proc
  j(["Bulk packet last, at most one<br/>Then power service / WDT / idle"]):::term
  a --> b
  b --> c
  c --> d
  d -->|Allowed / yes| e
  e --> f
  f -->|Yes| g
  f -->|Not yet| h
  d -->|No| h
  g --> h
  h -->|Yes| i
  h -->|No| j
  i --> j
  j -->|Next pass| a
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Priority is cooperative: an in-flight modem, sensor or logical LoRa send cannot be preempted instantly.
- Remote-wake schedule mode uses separate sample/send deadlines. WOR and timed Standby use their existing report-cycle policies [F20-F22].

Sources: Node/IoT_Node_Encrypted.ino:222; Node/src/app/SensorPollCycle.h:7

## F05 RS485 request response and failure path

All four drivers share one half-duplex bus. Each request is bounded and every returned group carries its own validity.

```mermaid
flowchart TD
  a(["Select enabled sensor<br/>Use its configured slave ID"]):::term
  b["Ensure silent interval<br/>DE HIGH, send Modbus request"]:::proc
  c["DE LOW and wait for response<br/>Service commands in idle gaps"]:::proc
  d{"Valid ID, function, length<br/>and CRC / response status?"}:::dec
  e["Decode this sensor map<br/>Check numeric validity"]:::proc
  f{"Transport retry allowed?"}:::dec
  g["Retry bounded TUF / Supmea<br/>At most two read attempts"]:::proc
  h["Replace failed group with zero<br/>Keep validity false"]:::bad
  i(["Update runtime snapshot<br/>Continue next sensor / loop"]):::term
  a --> b
  b --> c
  c --> d
  d -->|Success| e
  d -->|Failure| f
  e --> i
  f -->|Yes| g
  g -->|Next attempt| b
  f -->|No / exception| h
  h --> i
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Bus setting is 9600 baud, 8N1. TUF/Supmea retry transport errors; a valid Modbus exception is not retried. HNDA/Sondas reads use their current single-call path.
- The command idle hook pauses watchdog feeding so an endless Modbus wait cannot keep the controller alive forever.

Sources: Node/src/devices/Rs485Bus.cpp:36; Node/src/devices/Rs485Bus.cpp:26; Node/src/devices/TufSensor.cpp:58

## F06 TUF flow and native period totals

TUF supplies its own day/month/year volumes. Its 32-bit values use low-word-first register pairs, unlike Supmea.

```mermaid
flowchart TD
  a(["Begin TUF poll<br/>Zero a new result structure"]):::term
  b["FC03 at 0x0000, 6 registers<br/>Flow and velocity"]:::proc
  c{"Core reply / floats valid?"}:::dec
  d["Read day / month<br/>0x007C, 4 registers"]:::proc
  e["Read yearly integer + fraction<br/>0x0090, 4 registers"]:::proc
  f["Read optional error code<br/>0x0047, 1 register"]:::proc
  g["Publish zero invalid core<br/>Do not reuse last reading"]:::bad
  h(["Set independent live / period<br/>validity and TUF source"]):::term
  a --> b
  b --> c
  c -->|Yes| d
  c -->|No| g
  d --> e
  e --> f
  f --> h
  g --> h
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Modbus bytes within each 16-bit register retain standard bus order. The TUF driver combines the low register word first; it does not blindly reverse every byte.
- Day/month are float values. Year is signed integer part plus float fraction. Optional totalizer failures do not invalidate an otherwise good live group.

Sources: Node/src/devices/TufSensor.cpp:126; Node/src/app/FlowMeterManager.cpp:106

## F07 Supmea live data and cumulative totals

The FMC240 driver decodes high-word-first IEEE-754 floats and normalizes volumetric flow before updating RTC consumption.

```mermaid
flowchart TD
  a(["Begin Supmea poll<br/>Zero a new result structure"]):::term
  b["FC03 totals at decimal 90<br/>6 registers: forward / reverse / net"]:::proc
  c["FC03 live block at decimal 98<br/>10 registers: flow, velocity, alarms"]:::proc
  d{"Each group valid and finite?"}:::dec
  e["Normalize volume flow to m3/h<br/>Convert cumulative m3 to liters"]:::proc
  f["Zero only failed groups<br/>Mark them unavailable"]:::bad
  g["Valid forward total + trusted RTC<br/>Update accumulator [F09]"]:::ref
  h(["Map live / totals / periods<br/>with separate quality flags"]):::term
  a --> b
  b --> c
  c --> d
  d -->|For valid groups| e
  d -->|For failed groups| f
  e --> g
  f --> h
  g --> h
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Alarm bits include EPD and excitation-current alarm. A valid Modbus response does not by itself mean alarm-free physical measurement.
- L/h, L/min, L/s, m3/h, m3/min and m3/s are supported. Mass-flow units are not silently treated as volumetric flow.

Sources: Node/src/devices/SupmeaSensor.cpp:127; Node/src/app/FlowMeterManager.cpp:159

## F08 HNDA and Sondas soil measurements

The two soil probes have separate addresses, enable switches and payload fields even when both are on the same RS485 pair.

```mermaid
flowchart TD
  a(["Poll next enabled soil sensor"]):::term
  b["HNDA / Honde<br/>FC03 from 0x0000, 2 registers"]:::proc
  c["Sondas<br/>FC03 from 0x0000, 3 registers"]:::proc
  d{"Successful response?"}:::dec
  e{"Successful response?"}:::dec
  f["Signed temperature / 10<br/>Unsigned moisture / 10"]:::proc
  g["Temperature / 10, moisture / 10<br/>EC with configured scale"]:::proc
  h["Zero fields + validity false"]:::bad
  i(["HNDA -&gt; soil_* fields<br/>Sondas -&gt; ec_* fields"]):::term
  a -->|HNDA| b
  a -->|Sondas| c
  b --> d
  c --> e
  d -->|Yes| f
  e -->|Yes| g
  d -->|No| h
  e -->|No| h
  f --> i
  g --> i
  h --> i
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- HNDA is the Honde sensor called Honda in earlier project discussions. It is named HNDA in the current code.
- The Sondas register layout is configurable; the supplied family document did not establish a complete purchased-probe map. Confirm it on the actual probe.

Sources: Node/src/devices/HndaSensor.cpp:61; Node/src/devices/SondasSensor.cpp:61; Node/src/comm/SensorPayloadMapper.h:50

## F09 Supmea RTC day month and year consumption

Consumption comes from the accepted change in cumulative forward liters. RTC calendar keys decide the current day/month/year buckets.

```mermaid
flowchart TD
  a(["Forward total and sample UTC<br/>Load saved baseline if available"]):::term
  b{"RTC trusted and calendar valid?"}:::dec
  c{"No usable baseline?"}:::dec
  d["Set baseline, zero / partial totals<br/>Persist and wait for next sample"]:::proc
  e["Handle backward clock / counter<br/>Noise clamp, reset or anomaly"]:::proc
  f["Accepted delta liters<br/>Current minus previous total"]:::proc
  g{"Period boundary crossed?"}:::dec
  h["Add full delta to same buckets"]:::proc
  i["Allocate current-period share<br/>Proportional time, Estimated"]:::proc
  j["Return unavailable / uncertain<br/>Preserve internal history"]:::bad
  k(["Persist backup + checkpoints<br/>Publish m3 and quality"]):::term
  a --> b
  b -->|Yes| c
  b -->|No| j
  c -->|First sample| d
  c -->|Baseline exists| e
  e -->|Normal accepted change| f
  e -->|Reset / anomaly / time event| k
  f --> g
  g -->|No| h
  g -->|Yes| i
  h --> k
  i --> k
  d --> k
  j --> k
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- UTC RTC is converted using the configured UTC, fixed-offset or Africa/Cairo calendar policy. Cross-boundary allocation is an estimate, not a meter-provided daily register.
- The first partial period cannot recover water consumed before its baseline. Backup state and durable checkpoints reduce loss but do not invent missing history.

Sources: Node/src/app/SupmeaPeriodAccumulator.cpp:501; Node/src/devices/RTC.cpp:351

## F10 Build a truthful telemetry payload

Sensor validity, acquisition time and operational state remain explicit from runtime mapping through protobuf and the existing AES envelope.

```mermaid
flowchart TD
  a(["Complete runtime snapshot"]):::term
  b["Average battery ADC samples<br/>Apply divider and calibration"]:::proc
  c["TUF primary if both enabled<br/>Supmea -&gt; secondary_flow_meter"]:::proc
  d{"Routine Status or GOSTM?"}:::dec
  e["Routine: latest committed sample<br/>Else explicit live_fallback"]:::proc
  f["GOSTM: current runtime snapshot<br/>Attach requested ACK metadata"]:::proc
  g["Keep failed groups zero / invalid<br/>Refresh valve, reset and power state"]:::proc
  h["Encode nanopb + PKCS7 padding<br/>AES-128-CBC with 16-byte IV"]:::proc
  i(["Version + IV + ciphertext<br/>Publish on selected route"]):::term
  a --> b
  a --> c
  b --> d
  c --> d
  d -->|Routine Status| e
  d -->|GOSTM / reply| f
  e --> g
  f --> g
  g --> h
  h --> i
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Stored Status retains acquisition time/sequence, while commanded valve state and reset/power fields are current. HNDA and Sondas keep independent soil fields.
- The existing AES-CBC envelope has no authentication tag, and its runtime IV source is not cryptographically secure. No secret key is printed in this documentation.

Sources: Node/src/devices/BatteryMonitor.cpp:37; Node/src/comm/TelemetryPayload.cpp:18; Node/src/comm/PacketCodec.cpp:82

## F11 Direct MQTT receive and send priorities

TinyGSM owns AT transactions. Checked buffered sends and a bounded priority queue keep command replies ahead of routine status.

```mermaid
flowchart TD
  a(["Service IP transport<br/>Connect / MQTT loop if due"]):::term
  b["Incoming command callback<br/>Check topic / decode / target"]:::proc
  c{"Internal HISTORY_ACK 14?"}:::dec
  d["Advance archive cursor only<br/>No reply-to-ACK loop"]:::proc
  e["Handle operator command<br/>Discard queued stale routine Status"]:::proc
  f{"Reply requested / enabled?"}:::dec
  g["Queue correlated telemetry reply<br/>Before routine publish work"]:::proc
  h["Drain priority reply first<br/>Then eligible routine Status"]:::proc
  i(["Verified write / modem outcome<br/>Return result to power manager"]):::term
  a -->|RX callback| b
  b --> c
  c -->|Yes| d
  c -->|No| e
  e --> f
  f -->|Yes| g
  f -->|No| h
  g --> h
  d --> h
  a -->|No command| h
  h --> i
  i -->|Next pass| a
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- The application queue is bounded; this is not an unlimited offline mailbox. Returned write success is checked, including partial modem writes.
- Modem SEND OK or MQTT QoS 0 acceptance is not server execution or persistence. History uses its additional application ACK [F25].

Sources: Node/src/comm/MQTT.cpp:308; Node/src/comm/MQTT.cpp:666; Node/src/comm/PriorityPublishQueue.h:11

## F12 WiFi SIM connection and retry recovery

Physical network failures count separately from broker-only failures. Recovery has a modem-reset stage followed by a controller-reset stage.

```mermaid
flowchart TD
  a(["A physical connection attempt"]):::term
  b{"Selected modem?"}:::dec
  c["WiFi: firmware credentials<br/>Then saved / operator fallback"]:::proc
  d["SIM: registration then GPRS<br/>Use configured APN"]:::proc
  e{"Network connected?"}:::dec
  f(["Clear failure count / stage<br/>Continue MQTT connection"]):::term
  g["Count returned network failure"]:::proc
  h{"Reached 10 failures in stage?"}:::dec
  i["Keep bounded retry policy"]:::proc
  j["First set: reset modem RST<br/>Start second set of 10"]:::proc
  k["Second set: reset modem<br/>Request controller reset"]:::bad
  a --> b
  b -->|ESP8266| c
  b -->|SIM800| d
  c --> e
  d --> e
  e -->|Yes| f
  e -->|No| g
  g --> h
  h -->|Not yet| i
  i -->|Retry| a
  h -->|Stage 1 threshold| j
  j -->|Retry stage 2| a
  h -->|Stage 2 threshold| k
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- A call that never returns is handled by the 30 s IWDG, not the returned-failure counter. With IWDG armed, the deliberate controller reset is itself watchdog-driven.
- WiFi tries compiled settings first; saved flash credentials are fallback. A lengthy network outage can prevent sampling during startup/retries; continuous offline acquisition is not guaranteed.

Sources: Node/src/app/IoT_Node.cpp:330; Node/src/app/NetworkRetryPolicy.h:10; Node/src/comm/MQTT.cpp:234

## F13 LoRa wire transport and reassembly

Small physical frames carry a bounded encrypted logical message. CRC, fragment identity, retry and reassembly protect the radio transport.

```mermaid
flowchart TD
  a(["Encrypted logical payload<br/>At most 640 bytes buffer capacity"]):::term
  b["Split when required<br/>27 data bytes per fragment"]:::proc
  c["TX physical frame + CRC<br/>Wait for module AUX readiness"]:::proc
  d{"Required uplink fragment ACK?"}:::dec
  e["Receive / ACK or bounded retry<br/>No ACK -&gt; send failure"]:::proc
  f["RX: check wire version, network<br/>Length, source and CRC"]:::proc
  g["Reassemble by source / message<br/>32-bit received mask"]:::proc
  h{"Complete length + logical CRC?"}:::dec
  i(["Queue complete application frame"]):::term
  j["Discard / expire incomplete data<br/>Increment diagnostics"]:::bad
  a --> b
  b --> c
  c --> d
  d -->|Node uplink| e
  d -->|No transport ACK required| i
  e -->|Retry if allowed| c
  e -->|Accepted| i
  c -->|Radio peer| f
  f -->|Valid| g
  f -->|Invalid| j
  g --> h
  h -->|Yes| i
  h -->|Bad / timed out| j
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Physical wire maximum is 48 bytes; the current 640-byte capacity needs at most 24 fragments. Fragment ACKs confirm radio transport, not server record persistence.
- Use matched radio settings and unique node IDs on a shared channel. Traffic can collide. E32-TTL-100 UART RSSI is unsupported, so no invented fixed dBm is used.

Sources: Node/src/radio/LoraLink.cpp:1380; Node/src/radio/LoraLink.cpp:853; Node/src/radio/AS32_Config.h:78

## F14 Gateway bridge and downlink forwarding

The gateway gives an active radio fragment transaction priority, then bridges complete encrypted payloads using regional node topics.

```mermaid
flowchart TD
  a(["Gateway loop<br/>Drain LoRa UART first"]):::term
  b{"Fragment transaction active?"}:::dec
  c["Defer MQTT work<br/>Maintain fragment turnaround"]:::proc
  d["Service network / MQTT<br/>Receive command topics"]:::proc
  e{"Complete uplink frame available?"}:::dec
  f["Status -&gt; /status<br/>System telemetry -&gt; /data"]:::proc
  g["Build company / region / source<br/>Publish encrypted body unchanged"]:::proc
  h["Parse direct / broadcast topic<br/>Forward radio command [F16]"]:::proc
  i{"WOR configured at gateway?<br/>Mode-1 probe before command"}:::dec
  j(["Send command, restore Mode 0<br/>Then resume bridge / heartbeat"]):::term
  a --> b
  b -->|Yes| c
  b -->|No| d
  c --> e
  d --> e
  e -->|Supported uplink| f
  f --> g
  d -->|Downlink callback| h
  h --> i
  i -->|Probe or normal TX| j
  g --> j
  e -->|No frame| j
  j -->|Next pass| a
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Gateway role remains controller NORMAL. It does not poll the sensor bus or keep the leaf node SPI telemetry log.
- The new larger storage replies require an updated gateway as well as updated nodes. Delivery to MQTT is not a substitute for server application ACK.

Sources: Node/src/app/GatewayApp.cpp:54; Node/src/comm/MQTT.cpp:361

## F15 Server command intent and delivery lifecycle

Commands are durable, scoped operator intents. Broker receipt and matching node execution replies are separate events.

```mermaid
flowchart TD
  a(["Authenticated operator request<br/>Company / region / node / action"]):::term
  b{"Authorized scope and valid data?"}:::dec
  c[("Create command journal intent<br/>Request ID, actor and TTL")]:::db
  d{"Deliver now or next Status?"}:::dec
  e["Claim immediately when online"]:::proc
  f["Wait for matching node Status<br/>Then atomically claim"]:::proc
  g["Publish encrypted command<br/>Record broker receipt separately"]:::proc
  h{"Matching node reply?"}:::dec
  i(["Accepted / rejected by node<br/>Store execution receipt"]):::term
  j["Bounded rate retry or unknown<br/>Expiry / superseded intent retained"]:::bad
  k["Reject invalid / unauthorized request"]:::bad
  a --> b
  b -->|Yes| c
  b -->|No| k
  c --> d
  d -->|Now| e
  d -->|Next wake| f
  e --> g
  f --> g
  g --> h
  h -->|Correlated reply| i
  h -->|Timeout / no reply| j
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Only SRATE and STRAN have bounded automatic retries. Valve, STIME, counter clears and flash commands are not automatically repeated as uncertain actions.
- Broadcast replies describe individual nodes, never confirmed execution by an entire fleet. A sleeping node must be reachable or wait until its next report.

Sources: Server/server_web.py:1648; Server/command_queue.py:180; Server/command_queue.py:305

## F16 Node command dispatch replay and replies

The shared command policy covers direct MQTT and LoRa. Internal archive ACKs and explicit data requests have distinct behavior.

```mermaid
flowchart TD
  a(["Decoded command and topic class"]):::term
  b{"Direct target matches this node<br/>or permitted broadcast?"}:::dec
  c{"Storage CMD 9..14?"}:::dec
  d["Direct-only archive service<br/>14 advances transfer without reply"]:::ref
  e["WAKE / GOSTM special request<br/>Or ordinary replay-cache lookup"]:::proc
  f{"Fresh / legal ordinary intent?"}:::dec
  g["Apply rates / time / valve<br/>Or clear reset counter [catalog]"]:::proc
  h["Duplicate: reuse result<br/>Conflict / invalid: reject"]:::proc
  i{"Should telemetry reply be sent?"}:::dec
  j(["Correlated data / action ACK<br/>Queue ahead of routine Status"]):::term
  k(["No automatic reply<br/>Command effect may still apply"]):::term
  x["Ignore wrong target"]:::bad
  a --> b
  b -->|Yes| c
  b -->|No| x
  c -->|Yes| d
  c -->|No| e
  e --> f
  f -->|New / valid| g
  f -->|Duplicate / bad| h
  g --> i
  h --> i
  d -->|Except internal 14| i
  i -->|Enabled / explicit request| j
  i -->|Action ACK disabled| k
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- GOSTM plus FLASH_STATUS / LAST / TODAY explicitly request replies even when automatic action ACKs are off. CMD14 never creates a telemetry reply.
- Ordinary replay tracking is bounded RAM. Flash clear separately persists its most recent manual request ID; it is not an unlimited ledger of every past intent.

Sources: Node/src/comm/CommandHandler.cpp:39; Node/src/comm/CommandHandler.h:35; Node/src/comm/CommandReplayCache.h:11

## F17 Commissioned latching valve pulse

The TB6612FNG drives a polarity pulse and then turns the bridge off. Telemetry records commanded state, not physical position feedback.

```mermaid
flowchart TD
  a(["VALVE command<br/>0 close / 1 open"]):::term
  b{"Enabled, pins available, commissioned<br/>and not busy?"}:::dec
  c{"Already at commanded target?"}:::dec
  d["Check minimum interval<br/>Then persist Unknown / verify"]:::proc
  e["Arm TIM10 cutoff first<br/>PB9 / PB15 set polarity"]:::proc
  f["Enable bridge with PC13 STBY<br/>ISR or foreground cuts power"]:::proc
  g{"Pulse completed correctly?"}:::dec
  h(["Set commanded Open / Closed<br/>Persist and ACK completion"]):::term
  i["Reject / Fault; bridge stays OFF<br/>Interrupted state remains Unknown"]:::bad
  j(["Accept without another pulse"]):::term
  a --> b
  b -->|Yes| c
  b -->|No| i
  c -->|Yes| j
  c -->|No| d
  d -->|Verified| e
  d -->|Storage failure| i
  e --> f
  f --> g
  g -->|Yes| h
  g -->|No| i
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- LoRa uses PC13 for AUX, so the current profile inhibits the PC13 valve output. A new pin assignment needs an explicit wiring/configuration change.
- A completed pulse with a failed final durable save is still acknowledged as executed; RAM holds the target and reboot can recover Unknown. No WDT feeding is added inside the pulse wait.

Sources: Node/src/devices/ValveController.cpp:113; Node/src/devices/ValveController.cpp:96; Node/src/config/AppConfig.h:702

## F18 Watchdog reset causes and two counters

The hardware IWDG resets stalled active code. Only genuine power-on/brownout and IWDG causes increment their corresponding persistent counters.

```mermaid
flowchart TD
  a(["Boot: snapshot reset flags<br/>Preserve Standby classification"]):::term
  b{"IWDG flag set?"}:::dec
  c[("Increment WDT counter<br/>Recover last stored WDT stage")]:::db
  d{"Power-on / brownout only<br/>and not Standby / warm reset?"}:::dec
  e[("Increment power counter")]:::db
  f["Other reset: do not increment<br/>Power/WDT cause counter"]:::proc
  g["Arm nominal 30 s IWDG<br/>Feed only at progress checkpoints"]:::proc
  h{"Software keeps progressing?"}:::dec
  i(["Continue normal application"]):::term
  j["No feed -&gt; IWDG hardware reset<br/>Return through boot classification"]:::bad
  a --> b
  b -->|Yes| c
  b -->|No| d
  d -->|Yes| e
  d -->|No| f
  c --> g
  e --> g
  f --> g
  g --> h
  h -->|Yes| i
  h -->|Stuck| j
  j -->|Reset| a
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- RESET-button / ST-Link software reset / planned Standby wake do not count as power resets. Deliberate WDT-based network recovery still counts as an IWDG reset.
- Direct CMD7 clears the power count; CMD8 clears the WDT count. Readback verification, duplicate checks and ACK result expose storage failure. RTC alarms, not the WDT, schedule normal wakeups.

Sources: Node/src/platform/Watchdog.cpp:124; Node/src/platform/ResetCause.h:11; Node/src/platform/WatchdogResetCounter.cpp:77

## F19 Select a supported power policy

Controller state and selected-radio policy must form a supported pair. The compiler rejects unsupported combinations.

```mermaid
flowchart TD
  a(["Choose controller mode<br/>Then selected radio policy"]):::term
  b{"Gateway role?"}:::dec
  c["Controller NORMAL required<br/>Radio stays ready"]:::proc
  d["NORMAL<br/>Controller / selected radio normal"]:::proc
  e["REMOTE_WAKE<br/>CPU Sleep, radio NORMAL [F20]"]:::ref
  f["POWER_DOWN / QUEUED<br/>RTC Standby + sleeping radio [F21]"]:::ref
  g["LORA_WOR<br/>STM32 Stop + radio Mode 2 [F22]"]:::ref
  h{"Selected hardware and policies<br/>pass compile-time checks?"}:::dec
  i(["Run chosen policy"]):::term
  j["Reject configuration<br/>Fix role, pins or radio pairing"]:::bad
  a --> b
  b -->|Gateway| c
  b -->|Node normal| d
  b -->|Node remote| e
  b -->|Node periodic / queued| f
  b -->|Node WOR| g
  c --> h
  d --> h
  e --> h
  f --> h
  g --> h
  h -->|Yes| i
  h -->|No| j
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Direct SIM800 deep/queued Standby is rejected on this PCB: PWRKEY/DTR/RI are not routed. SIM may remain NORMAL while the controller uses REMOTE_WAKE.
- STM32 Stop reception is implemented through LoRa WOR Mode 2. This does not make an arbitrary normal modem able to wake the MCU from Standby. See the combination appendix.

Sources: Node/src/config/AppConfig.h:216; Node/src/power/PowerManager.cpp:1033

## F20 Remote wake with normal connected modem

The reachable-idle controller uses light CPU Sleep while the radio remains connected. The default policy responds to independent sampling and send deadlines.

```mermaid
flowchart TD
  a(["REMOTE_WAKE active / reachable idle"]):::term
  b{"UART command, app deadline,<br/>reply / flash work or WAKE lease?"}:::dec
  c["Resume foreground work<br/>Do not force unrelated deadlines"]:::proc
  d["Service commands first<br/>Then only due sample / send work"]:::proc
  e{"No due / busy work<br/>and no active WAKE lease?"}:::dec
  f["Reachable idle<br/>Normal modem, UART / SysTick alive"]:::proc
  g(["WFI light CPU Sleep<br/>Interrupt / periodic poll resumes"]):::term
  h["Keep application active<br/>Preserve pending operations"]:::proc
  a --> b
  b -->|Yes| c
  b -->|No| f
  c --> d
  d --> e
  e -->|Yes| f
  e -->|No| h
  h -->|Next pass| b
  f --> g
  g -->|UART / tick / deadline| b
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Default APP_REMOTE_WAKE_USE_APP_SCHEDULE=true uses SRATE and STRAN separately. false retains the older fixed-cycle remote policy.
- WAKE requests an active lease of 1..86400 s; data 0 uses the configured default. Flash work/transfer guards prevent inappropriate idling; this is not RTC Standby or a modem DTR sleep implementation.

Sources: Node/src/power/PowerManager.cpp:1172; Node/src/power/RemoteWakeCycle.h:72; Node/src/config/AppConfig.h:105

## F21 Periodic and queued RTC Standby

A successful report opens a command window. Standby is entered through a verified reset handoff so active work keeps watchdog protection.

```mermaid
flowchart TD
  a(["Fresh sample and successful report"]):::term
  b["Command window<br/>Periodic or longer queued policy"]:::proc
  c{"Window elapsed, no active lease<br/>transport / flash idle and RTC valid?"}:::dec
  d["Keep awake / retry preparation<br/>Queued command can hold WAKE lease"]:::proc
  e["Put radio into supported sleep<br/>Put idle flash into deep power-down"]:::proc
  f[("Store checked RTC sleep request<br/>Limit deadline by flash expiry")]:::db
  g["Software reset<br/>Early boot before IWDG [F03]"]:::proc
  h(["Enter Standby until RTC deadline<br/>Wake is a new startup"]):::term
  i["Abort failed handoff<br/>Restore active scheduling"]:::bad
  a --> b
  b --> c
  c -->|Not ready| d
  d -->|Later pass| c
  c -->|Ready| e
  e --> f
  f -->|Verified| g
  f -->|Failure| i
  g --> h
  h -->|RTC boot + work| a
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- ESP8266 or LoRa periodic/queued profiles require the matching radio POWER_DOWN policy. The present direct SIM800 hardware rejects this mode.
- Queued server commands wait for the next Status; this does not make a fully sleeping modem instantly reachable. Flash write/recovery/transfer work defers Standby.

Sources: Node/src/power/PowerManager.cpp:655; Node/src/power/PowerManager.cpp:759

## F22 LoRa wake on radio with STM32 Stop

The leaf radio listens in Mode 2 while STM32 RAM is retained in Stop. UART RX is the default wake interrupt; RTC handles heartbeat/report/retention deadlines.

```mermaid
flowchart TD
  a(["Report sent, command window elapsed<br/>No lease / busy transfer / write"]):::term
  b["Enter radio Mode 2<br/>M0 LOW, M1 HIGH; verify readiness"]:::proc
  c["Arm UART RX falling-edge wake<br/>Set nearest RTC alarm; flash sleeps"]:::proc
  d{"Safe to enter Stop?<br/>Check pending edge / UART / RTC"}:::dec
  e["STM32 Stop with RAM retained"]:::proc
  f{"Wake source?<br/>Restore clocks before UART work"}:::dec
  g["UART activity: return Mode 0<br/>Receive command; data not yet proven"]:::proc
  h["RTC heartbeat: service WDT<br/>If no deadline, return to Stop"]:::proc
  i(["Report / flash expiry due<br/>Return for scheduled work"]):::term
  j["Activity or setup failure<br/>Stay active / preserve received bytes"]:::bad
  a --> b
  b --> c
  c --> d
  d -->|Yes| e
  d -->|No| j
  e --> f
  f -->|RX| g
  f -->|Heartbeat| h
  f -->|Deadline| i
  h -->|Still waiting| c
  g -->|After work / window| a
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Gateway WOR TX sends a Mode-1 probe before the command. AUX remains a readiness signal; the optional legacy AUX wake selector is separate from the default UART RX path.
- Default heartbeat is 15 s under the nominal 30 s IWDG. APP_POWER_SLEEP_SECONDS sets the WOR report deadline; heartbeat alone does not force a new sample. WDT expiry resets rather than scheduling wake.

Sources: Node/src/power/PowerManager.cpp:160; Node/src/power/WorWakeInput.h:30; Node/src/radio/LoraLink.cpp:1340

## F23 Capture and commit a flash sample

The external S25FL064L stores one canonical complete sample per accepted acquisition, with CRC and commit-last recovery.

```mermaid
flowchart TD
  a(["All sensor groups completed"]):::term
  b{"Enabled, ready, trusted time<br/>and unexpired generation?"}:::dec
  c["Encode canonical Telemetry<br/>No command / history wrapper"]:::proc
  d{"Queue has room and log not full?"}:::dec
  e["Allocate / verify current sector<br/>Program two body pages"]:::proc
  f["Poll completion in later passes<br/>Read back body / CRC"]:::proc
  g[("Write commit marker last<br/>Update count / latest sequence")]:::db
  h["Count skipped / dropped sample<br/>Keep reporting with honest source"]:::bad
  i["I/O / status / timeout failure<br/>Latch Fault, no silent success"]:::bad
  a --> b
  b -->|Yes| c
  b -->|No| h
  c --> d
  d -->|Yes| e
  d -->|No| h
  e --> f
  f -->|Verified| g
  f -->|Failed| i
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- JEDEC 01 60 17 identifies the configured 8 MiB chip. Four RAM queue entries feed 512-byte slots with at most 472 canonical protobuf bytes each.
- Capacity is 14,322 records. Full means stop appending and count drops, not overwrite unexpired records. A return from append means queued, not yet durable.

Sources: Node/src/storage/TelemetryArchive.cpp:72; Node/src/storage/TelemetryJournal.cpp:100; Node/src/storage/S25Fl064l.cpp:40

## F24 Flash recovery retention and clearing

Two metadata copies choose a durable generation. Records recover cooperatively; retention changes the generation before background physical reclamation.

```mermaid
flowchart TD
  a(["Probe chip / read metadata copies"]):::term
  b{"Recognized chip + valid format?"}:::dec
  c["Recover valid committed records<br/>Skip torn / CRC-bad slots"]:::proc
  d["Missing: retry probe<br/>Unformatted: explicit clear required"]:::bad
  e{"Trusted 24-hour expiry<br/>or accepted CLEAR_FLASH?"}:::dec
  f[("Commit alternate metadata<br/>New generation / retention start")]:::db
  g["Old records no longer exposed<br/>Sweep old sectors cooperatively"]:::proc
  h{"Sector now owned by new log?"}:::dec
  i["Protect it; skip this sector"]:::proc
  j["Erase old sector if necessary<br/>Persist sweep completion"]:::proc
  k(["Ready / Full: normal archive use"]):::term
  a --> b
  b -->|Yes| c
  b -->|No| d
  d -->|Manual initialization| e
  c --> e
  e -->|Yes| f
  e -->|No| k
  f --> g
  g --> h
  h -->|Yes| i
  h -->|No| j
  i -->|Next sector| g
  j -->|Next sector| g
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Retention is 24 elapsed hours from the persisted batch start, not local midnight. Untrusted/backward time cannot trigger automatic erase.
- Ownership is rechecked on every sweep pass so newly allocated samples cannot be erased. Clear ACK is acceptance; physical erase progress may continue across active windows.

Sources: Node/src/storage/TelemetryJournal.cpp:26; Node/src/storage/TelemetryJournal.cpp:159; Node/src/storage/TelemetryJournal.cpp:78

## F25 Download retained history with persistence ACK

FLASH_TODAY freezes the node day and final sequence. The node sends one indexed row at a time and advances only after server storage acknowledgment.

```mermaid
flowchart TD
  a(["Direct FLASH_TODAY / resume<br/>Require retained trusted log"]):::term
  b["Freeze day, generation, final seq<br/>Count matching valid records"]:::proc
  c["Read next CRC-valid sample<br/>Attach request / index / total"]:::proc
  d["Send after priority work<br/>Server commits scoped row [F26]"]:::proc
  e{"Matching internal CMD14 received?"}:::dec
  f["Advance cursor<br/>Send next row or successful End"]:::proc
  g["Bounded retry same row<br/>Then ACK-timeout terminal result"]:::proc
  h{"Cancel / expiry / read error?"}:::dec
  i(["Send explicit terminal result<br/>Release after ACK / bounded timeout"]):::term
  a --> b
  b --> c
  b -->|Empty result| i
  c --> d
  d --> e
  e -->|Yes| f
  e -->|Timeout| g
  g -->|Attempts remain| d
  g -->|Exhausted| i
  f -->|More rows| c
  f -->|End| i
  b -->|During job| h
  h -->|Yes| i
  h -->|No| c
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- FLASH_LAST is a single original sample, not a new sensor poll. TODAY covers only the retained batch portion of the current node calendar day, not necessarily a complete day.
- New acquisition remains allowed while download keeps the controller awake; later records are excluded from the frozen job. Server history does not feed live charts or consumption.

Sources: Node/src/storage/TelemetryArchive.cpp:164; Server/flash_archive.py:74; Server/server_web.py:134

## F26 Server receive validate and store

Incoming MQTT frames are decrypted and checked against exact regional topic identity before any live update, command receipt or archive persistence.

```mermaid
flowchart TD
  a(["MQTT RX frame<br/>Bounded topic / payload size"]):::term
  b["Check envelope, decrypt AES<br/>Validate PKCS7 / parse protobuf"]:::proc
  c{"Topic, node ID, numbers<br/>and enum fields valid?"}:::dec
  d["Status / live Telemetry<br/>Select measured time / quality"]:::proc
  e["Flash metadata / history<br/>Separate archive transaction"]:::proc
  f["Command echo<br/>Internal ACK14 is not live history"]:::proc
  g[("Store live readings / periods<br/>Deduplicate flow samples")]:::db
  h[("Store archive row / transfer<br/>Only then send HISTORY_ACK")]:::db
  i(["Emit scoped dashboard events<br/>Dispatch queued command on Status"]):::term
  j["Drop and log invalid message<br/>No database / execution ACK effect"]:::bad
  a --> b
  b -->|Decoded| c
  b -->|Decode failed| j
  c -->|Valid live| d
  c -->|Valid archive| e
  c -->|Valid command| f
  c -->|Invalid| j
  d --> g
  e --> h
  g --> i
  h --> i
  f -->|Operator echo only| i
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Topics are wiot/company/region/node/status, /data, /cmd, plus regional /broadcast. Topic node and protobuf node must agree; a good AES decode alone is insufficient.
- Stored sample_time_valid is independent of the primary meter RTC flag. Original acquisition time is used when trusted, with explicit fallback provenance in live history.

Sources: Server/mqtt_impl.py:67; Server/server_web.py:987; Server/input_validation.py:50

## F27 Server users dashboard reports and isolation

The web application separates authenticated views, company scope and privileged infrastructure actions while displaying live and archived data.

```mermaid
flowchart TD
  a(["Start server / initialize databases<br/>Initial users require local secrets"]):::term
  b["Login and verify password hash<br/>Establish role / company session"]:::proc
  c{"User request authorized?"}:::dec
  d["Live dashboard / history / graphs<br/>Thresholds, map and node details"]:::proc
  e["Admin: commands, user / node config<br/>Supervisor: shared broker controls"]:::proc
  f["Flash archive status / progress<br/>Stored records and CSV export"]:::proc
  g["Scope every query / event<br/>Company + region + node"]:::proc
  h(["Return API / Socket.IO view<br/>Safe text rendering / bounded history"]):::term
  i["Reject unauthorized request<br/>No cross-company side effect"]:::bad
  a --> b
  b --> c
  c -->|Read view| d
  c -->|Permitted action| e
  c -->|Archive query| f
  c -->|Denied| i
  d --> g
  e --> g
  f --> g
  g --> h
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Live readings/periods, command intentions/receipts and external-flash downloads have different persistence paths. Clearing a node log does not delete already received server archive rows.
- Broker connection readiness includes subscription success. Ordinary company users do not receive shared infrastructure logs or control another company through a changed browser selector.

Sources: Server/server_web.py:1211; Server/server_web.py:1205; Server/static/js/flash_archive.js:32

## F28 Four sensor simulator on one shared bus

The multi-sensor lab hosts multiple virtual devices per sensor type, each with a unique address and independently configured signal behavior.

```mermaid
flowchart TD
  a(["Configure COM port / bus<br/>Add / clone / batch-add devices"]):::term
  b["Validate unique slave addresses<br/>Choose fixed / dynamic signal values"]:::proc
  c["Simulation tick updates devices<br/>Totals + local Supmea calendar oracle"]:::proc
  d{"Serial request with valid CRC?"}:::dec
  e["Route to enabled device address<br/>Validate function / register range"]:::proc
  f["Encode that sensor register map<br/>Apply selected fault / delay behavior"]:::proc
  g(["Reply with CRC / exception<br/>Or intentional silence / corruption"]):::term
  h["Ignore noise / unknown address<br/>Update traffic counters"]:::proc
  i["GUI readings / logs / oracle CSV<br/>Compare node and simulator totals"]:::proc
  a --> b
  b --> c
  c --> d
  d -->|Yes| e
  d -->|No / no device| h
  e --> f
  f --> g
  c --> i
  g -->|Next request| d
  h -->|Continue| d
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Several HNDA, TUF, Supmea and Sondas devices can share the simulator bus. The node still polls only its configured addresses; duplicate addresses on a physical bus are invalid.
- The independent Supmea day/month/year reference stays local to the simulator and is not injected into the RS485 meter map. Focused TUF/Supmea simulators remain available.

Sources: MultiSensor/multi_sensor_simulator.py:606; MultiSensor/multi_sensor_bus.py:51; MultiSensor/multi_sensor_core.py:866

## F29 Verify document and release the project

A release includes matched node/server schemas, behavioral regressions, firmware bounds, human documentation and a separate hardware acceptance step.

```mermaid
flowchart TD
  a(["Authorized project change<br/>Preserve deployment secrets"]):::term
  b["Regenerate matching schemas<br/>If the protocol changed"]:::proc
  c["Run native / server / simulator<br/>And cross-component regression suites"]:::proc
  d["Build firmware profiles<br/>Check flash load / RAM / EEPROM area"]:::proc
  e{"Checks pass?"}:::dec
  f["Update guides / Doxygen / flows<br/>Synchronize verified final folder"]:::proc
  g["Create new feature branch<br/>Publish complete change and verify ref"]:::proc
  h(["Run physical acceptance<br/>Supply, sensors, RF, power, flash soak"]):::term
  i["Fix defect and repeat<br/>Do not claim hardware validation"]:::bad
  a --> b
  b --> c
  c --> d
  d --> e
  e -->|Yes| f
  e -->|No| i
  i -->|Recheck| c
  f --> g
  g --> h
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- Internal firmware flash load is kept below the reserved EEPROM sector at 0x08020000. Source/docs delivery does not flash the board or prove physical operation.
- ESP32 and STM32CubeIDE do not automatically receive Arduino STM32 updates. Keep .env, AppSecrets, private AppConfig.cpp and runtime databases out of Git.

Sources: Validate-Release.ps1:14; regenerate_protocol.py:15; Node/SPI_FLASH_TEST_PLAN.md:1

## F30 Active release and separate firmware ports

The repository contains three firmware implementations. The detailed current flowcharts describe the Arduino STM32 release; alternate ports retain their own snapshots.

```mermaid
flowchart TD
  a(["Select project to build"]):::term
  b["Arduino STM32F401<br/>Active release documented here"]:::proc
  c["ESP32 Arduino port<br/>Separate architecture snapshot"]:::proc
  d["STM32CubeIDE HAL port<br/>Separate native implementation"]:::proc
  e["Current sensing / commands / WDT<br/>Power modes / RTC totals / SPI log"]:::proc
  f["Remapped three UART roles<br/>External ESP8266 / SIM retained"]:::proc
  g["SensorNode / LoRaGateway<br/>HAL startup, UART rings, drivers"]:::proc
  h(["Use this book F01-F29<br/>for active release behavior"]):::term
  i(["Inspect own config and schema<br/>Do not assume current feature parity"]):::term
  a --> b
  a --> c
  a --> d
  b --> e
  c --> f
  d --> g
  e --> h
  f --> i
  g --> i
  classDef term fill:#173E5B,color:white,stroke:#173E5B
  classDef proc fill:#EAF2F8,color:#163B55,stroke:#91A9BC
  classDef dec fill:#FFF1D2,color:#513F12,stroke:#C4A35E
  classDef db fill:#E1F2ED,color:#214B43,stroke:#7DA89B
  classDef bad fill:#FBE9E9,color:#733C3C,stroke:#C49393
  classDef ref fill:#EEEAF8,color:#4B416D,stroke:#A69BC7
```

- The ESP32 compatibility port uses external modems; it does not silently switch the project to ESP32 internal WiFi. Its UART mapping is role dependent.
- Neither alternate port has been updated by the recent active STM32 storage/power/command releases. Historical compatibility claims must be checked against that port's actual schema and code.

Sources: ESP32/ESP32_USER_GUIDE.md:3; CubeIDE/README.md:1; Node/README.md:1
