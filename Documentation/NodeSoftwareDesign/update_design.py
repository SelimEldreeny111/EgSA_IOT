"""Revise the retained EgSA design template against the 30 October code release.

Run with bundled Python. Microsoft Word refreshes fields and exports a QA PDF
after this edit. The requested legacy filename is retained; internal revision
1.1 supersedes the 7 October 1.0 edition. No runtime configuration is opened.
"""
from pathlib import Path
from copy import deepcopy
from io import BytesIO
import json, re, subprocess
from docx import Document
from docx.table import Table
from docx.shared import Inches, Pt, RGBColor
from docx.enum.section import WD_SECTION_START, WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
PATH=HERE/'WIOT_STM32_Node_Software_Design_V1.0.docx'
BASE='104cf15cea0a90166538d8c3fa1af61be2580e4b'
CODE='f478b47ecedb108328b9befe762b24b85320c225'
raw=subprocess.check_output(['git','show',BASE+':Documentation/NodeSoftwareDesign/'+PATH.name],cwd=ROOT)
doc=Document(BytesIO(raw))
paras=list(doc.paragraphs); tables=list(doc.tables)
assert len(tables)==41 and len(paras)==719

def text(p,value):
    props=deepcopy(p.runs[0]._r.rPr) if p.runs and p.runs[0]._r.rPr is not None else None
    p.clear();r=p.add_run(value)
    if props is not None:r._r.insert(0,props)

def cell(c,value):
    text(c.paragraphs[0],str(value))
    for p in c.paragraphs[1:]:p._p.getparent().remove(p._p)

def row(t,values):
    el=deepcopy(t.rows[-1]._tr);t._tbl.append(el)
    for c,v in zip(t.rows[-1].cells,values):cell(c,v)

def setrow(index,number,values):
    for c,v in zip(tables[index].rows[number].cells,values):cell(c,v)

def before(anchor,value,style='Normal'):
    return anchor.insert_paragraph_before(value,style)

def newtable(anchor,caption,headers,rows,template):
    before(anchor,caption,'Caption')
    el=deepcopy(tables[template]._tbl)
    for tr in list(el.findall(qn('w:tr')))[2:]:el.remove(tr)
    anchor._p.addprevious(el)
    t=Table(el,doc._body)
    for c,v in zip(t.rows[0].cells,headers):cell(c,v)
    for c,v in zip(t.rows[1].cells,rows[0]):cell(c,v)
    for values in rows[1:]:row(t,values)
    before(anchor,'')
    return t

updates={
17:'Engineering review edition, revised 1 November 2026 against the 30 October active Arduino STM32 release. Revision 1.1 updates the retained 7 October design. Review/approval fields remain unassigned; physical acceptance evidence is identified separately from software verification.',
21:'Use Section 5 for implementation/configuration, Section 13 and Appendix A for acceptance steps, Appendix B for interfaces and Appendix D for key flowcharts. Source paths are node-relative unless a release-root prefix is stated. The full thirty-chart package covers the gateway, server and simulators in greater detail. Snapshot configuration values must be checked against the actual flashed image.',
12:'WIOT STM32 Node Software',
13:'Tracking No.: WIOT-NOD-DDS-07-001-V1.1',
117:'The WIOT node acquires water-flow and soil measurements, stores complete samples on external SPI flash, publishes the latest retained snapshot, accepts remote operating commands, controls a commissioned latching valve and recovers from network failures or software stalls. This revision defines the current implementation, its operating limits and the procedures needed to verify it.',
133:'N01-N12 are local design labels for navigation and test allocation. This revision adds the elapsed 24-hour external sample journal, independent power/WDT counters and acknowledged history download. Authenticated encryption, measured valve position and binary OTA firmware update remain outside the implemented capability set.',
135:'The reviewed public configuration selects sensor node 2, sensor ID 1, Company_1 / Region_1 and LoRa-to-gateway uplink. Controller LORA_WOR and radio WAKE_ON_RADIO use UART RX wake; SPI logging and all four sensors are enabled at TUF 1, SUPMEA 2, HNDA 3 and Sondas 4. Boot SRATE/STRAN are 10,000/15,000 ms; WOR uses its 120-s report-cycle policy, 15-s RTC watchdog heartbeat and 5-s command window. The gateway is built separately in NORMAL with WOR TX enabled. Each flashed device must have its own identity and matching scoped topics.',
141:'1. Apply valve safety pins only when available. Capture RCC/PWR reset flags before early power handling clears them. A valid pending Standby handoff enters Standby before IWDG arming; an invalid or expired request resumes normal startup.',
142:'2. Classify the captured cause, load/increment the independent WDT and power counters as appropriate, and arm the global hardware watchdog. Select sensor-node or gateway setup at compile time.',
144:'4. Initialize RS485 and the enabled drivers, restore SUPMEA accumulator state, then initialize the external telemetry archive and power policy. Journal recovery advances cooperatively; a missing or unformatted chip does not stop existing live reporting.',
145:'5. Service commands first, advance one archive step and start/continue one sensor group when allowed. Modbus idle callbacks can service commands without watchdog feeding. Capture one canonical archive sample only after the full sensor cycle completes.',
146:'6. When STRAN/report policy permits and no higher-priority work or pending archive write intervenes, build routine Status from the latest committed sample. Keep original acquisition time/sequence, refresh operational fields and mark explicit live fallback if a stored sample cannot be read. GOSTM uses current runtime measurements.',
147:'7. Drain priority replies before routine work. Send at most one ready history packet after commands and routine service, then update power/watchdog state. Flash writes, recovery and active history transfers defer inappropriate sleep; active transfers still permit scheduled sensing.',
150:'NORMAL and schedule-driven REMOTE_WAKE use independent elapsed-millis SRATE and STRAN deadlines. Sampling is measured from cycle start and transmission from its attempt; unsigned subtraction supports rollover. Timed Standby and LORA_WOR retain report-cycle scheduling rather than independently waking for every SRATE deadline. Command period changes are RAM settings that revert to compiled defaults after restart.',
158:'The reviewed source constructs SerialAT(PA12, PA11), using controller RX then TX. The current LoRa UART-RX wake path reuses LoRa TXD to controller PA12. Verify fitted PCB labels and variant mappings against the compiled role; old documentation with reversed RX/TX descriptions is superseded by the source-level allocation here.',
166:'Company, region, node ID, topic identity and server target must agree. The current topic builder derives scoped strings from public identity configuration; private files hold deployment connection strings and keys. Use distinct MQTT client IDs. Node, gateway and server require matching schemas and the same locally provisioned 16-byte key.',
202:'Battery voltage maps to Status tag 19 and Telemetry tag 5. An archived routine Status retains the voltage from that acquisition; GOSTM refreshes runtime voltage. Disabled measurement reports zero. Compare against a calibrated meter at several safe voltages. Divider tolerance, reference variation, noise and grounding determine practical accuracy; voltage alone does not measure modem current or remaining battery capacity.',
209:'The public test configuration uses TCP MQTT on port 1883 without TLS. Keepalive is 45 s, socket timeout 8 s and reconnect backoff 3 s. Direct nodes subscribe to their exact regional cmd and regional broadcast topics; gateways subscribe to the configured regional node-command wildcard and broadcast route.',
211:'Topics are lowercase and case-sensitive. The node checks subscription packet writes; the server separately waits for successful SUBACK before declaring its own receive readiness. Company/region/node and decoded payload identity are validated. A topic/payload mismatch is a routing configuration error, not a byte-order problem.',
215:'The same command-priority correction serves SIM and ESP8266. mqtt.loop guards prevent reentrant modem calls, and Modbus command servicing cannot feed a stalled outer operation indefinitely. QoS-0 write acceptance is not server persistence. The external sample journal now retains measurements, but it is separate from the volatile MQTT packet/reply queue and does not guarantee gap-free sampling during network startup.',
223:'E32-TTL-100 UART RSSI is unsupported; diagnostics report that explicitly. Enable an optional V3 query only on a confirmed compatible module. The 29 October UART-RX WOR bench report records approximately 9 mA for the tested assembly after earlier unsuccessful sleep attempts around 42 mA. It is an initial user-reported current result, not a complete RF/wake or energy qualification.',
229:'Codec payload buffers are 640 bytes and MQTT packet allocation is 1024 bytes. Generated maximum Status and Telemetry sizes are 333 and 546 plaintext bytes. A maximum Telemetry encrypts to 577 bytes including version/IV/padding. Canonical archive samples have a separate 472-byte payload bound; command/archive metadata is excluded before storing the sample.',
243:'APP_ENABLE_COMMAND_ACK_REPLIES controls automatic action replies for SIM, Wi-Fi and LoRa. GOSTM and explicit FLASH_STATUS/LAST/TODAY data requests still respond when it is false. Internal HISTORY_ACK never creates a response-to-ACK loop. Use nonzero request IDs for correlated results; execution and server confirmation remain separate when automatic replies are disabled.',
257:'5.12.2  Persistent reset counters',
258:'The existing 20-byte WDT record occupies EEPROM offsets 192..211. A separate 20-byte power record occupies 232..251; the valve record remains 212..231. Both use version/magic/checksum/inverted-count validation, saturate at UINT32_MAX and verify buffered commits. Only the classified cause increments once per boot. A failed commit can leave a RAM count with an unhealthy-storage warning.',
259:'IWDG resets, including deliberate network-recovery IWDG resets, increment WDT count. Genuine POR/BOR increments power count. NRST-only, software reset, planned Standby handoff/wake, Stop and light Sleep wake increment neither. Mixed flags honor Standby/warm-reset exclusions; POR+PIN may be a genuine power event. Status tags 35/36 and Telemetry tags 44/45 carry WDT/power counts. Direct CMD7/CMD8 clear and verify only the selected counter; they do not reset the MCU or meter totals.',
281:'LORA_WOR requires trusted RTC, a NORMAL gateway with APP_LORA_GATEWAY_WOR_TX=1 and matching radio timing. The leaf enters E32 Mode 2 with M0 LOW/M1 HIGH and STM32 Stop. The default falling-edge wake input is LoRa TXD to controller UART RX PA12, selected by APP_LORA_WOR_WAKE_SOURCE_UART_RX. AUX PC13 remains a readiness input; the older AUX wake option is explicitly selectable. A gateway Mode-1 probe precedes the actual command.',
282:'RTC Alarm A selects the earliest heartbeat, report deadline or retained-log expiry. The current 15-s heartbeat services IWDG in foreground, then returns to Stop if no work is due; it does not itself force a sample. The nominal WDT remains 30 s and resets hangs rather than scheduling normal wakeups. Interrupts set flags only. Stop exit restores clocks before UART/flash work, preserves received bytes and opens the command window. Pending UART/RTC activity or failed setup prevents Stop rather than discarding input.',
279:'APP_POWER_SLEEP_SECONDS is 120 s in this snapshot. It sets the periodic/queued sleep interval and WOR report cycle; sensing, reconnection and command windows add active time. Invalid requests fail open to awake scheduling. RTC_QUEUED requires trusted time. Flash busy/transfer guards defer sleep, while the retained-log expiry can request an earlier maintenance wake. Queued delivery waits for the next connected window.',
287:'The external S25FL064L now holds complete canonical samples in a commit-last journal. Internal EEPROM records, external sample storage and the transient MQTT queue have different failure/retention properties. Ordinary replay cache and changed sample/transmit periods remain volatile. The node does not persist every outgoing MQTT packet, and unchanged connection loops may still delay acquisition.',
296:'The Wi-Fi deep-sleep entry written as 7 retains an unresolved microamp/milliamp interpretation. SIM deep sleep remains unsupported on the present wiring. LoRa now has an initial 29 October observation around 9 mA with UART-RX WOR wake, compared with about 42 mA during an earlier failed sleep attempt; the measurement point, supply and averaging method were not fully recorded. A calibrated whole-node duty-cycle and command-wake study remains open.',
324:'RTC backup offers retained low-wear working state, while internal flash checkpoints survive backup loss within their checkpoint limits. Those records still share an erase sector. The separate 8-MiB external journal provides commit-last sample/metadata recovery and rotating 24-hour generations; it does not remove internal EEPROM wear or power-fail risks, nor does it provide encryption at rest.',
330:'The latest cited verification is SPI_FLASH_SOFTWARE_VERIFICATION_20261030.md: full release validation, 53 configuration cases, 65 production WOR scenarios, 16 RTC/SUPMEA cases, 10 cross-component contracts, 124 Python server tests and 65 simulator tests. It also records journal recovery/full/failure tests, 13 mutating power-cut transitions, nine SPI/archive scenarios and 17/22/24-fragment LoRa reassembly cases.',
331:'That report records eight successful ARM profiles with four sensors and core 2.12.0 / GCC 14.2.1. Maximum recorded flash load end is 0x08019908 and initialized data+BSS is 36,036 bytes; all loads stay below EEPROM sector 0x08020000. Doxygen completed with zero warnings. These are retained 30 October results; the present documentation update performs source/schema/layout checks rather than claiming a new firmware or hardware validation run.',
344:'Minimum acceptance covers identity/topic scope, four-sensor values and validity, RTC totals, Status/GOSTM, rate/time commands, valve commissioning, reset cause and both counters, 10+10 recovery, intended power wakes and ADC calibration. With SPI enabled also verify JEDEC, explicit format, sample commit/readback, elapsed retention, recovery from real power cuts and a complete acknowledged history download. Broker receipt alone cannot close these tests.',
355:'Use the current UART-RX WOR, reset-counter, regional topic and SPI guides with this edition. Dated AUX-only, single-reset-counter, old-topic and no-sample-log descriptions are superseded. This document retains the requested legacy filename, while internal revision 1.1 identifies the updated design. Vendor electrical ratings and controlled hardware acceptance remain applicable.',
651:'Common mapping for primary/secondary flow, independent soil data, battery, both reset counters, power and sample provenance; failed groups remain zero/invalid.',
510:'2. Verify default UART RX falling-edge wake, clock restore, Mode 0 and matching command reply. AUX remains the ready/busy signal.',
511:'3. Observe RTC report/retention deadline and 15-s WDT-maintenance heartbeat; inject pending UART/IRQ activity and a radio restoration failure.',
517:'3. Measure normal/remote/deep phases with instrument range, input voltage and powered components. Retest LoRa heartbeat/report/command wakes and extended current traces beyond the initial 9-mA observation.',
718:'End of node software design reference. The matching flowchart package provides the complete system workflows and editable sources. Approval and configuration-specific hardware acceptance remain controlled project activities.',
}
for i,value in updates.items():text(paras[i],value)

# Revision and source tables retain the supplied cover/header layout.
cell(tables[0].rows[4].cells[1],'V1.1 - 1 November 2026')
row(tables[1],['01/11/2026','1.1','Current topics; two counters; UART-RX WOR; SPI sample journal/history commands; expanded schema, tests and flowcharts.'])
setrow(2,1,['Document identifier','WIOT-NOD-DDS-07-001-V1.1; legacy V1.0 filename retained for existing references'])
setrow(2,3,['Software baseline',CODE+'; 30 October runtime release. Flowchart reference: '+BASE[:7]+', 1 November 2026.'])
row(tables[4],['R11','SPI_FLASH_TELEMETRY_GUIDE.md; SPI_FLASH_TEST_PLAN.md; src/storage/','Journal geometry, recovery, commands and physical acceptance'])
row(tables[4],['R12','Release Documentation/Flowcharts/README.md; source_manifest.json','30 source-verified system flows; offline viewer, vector PDF and editable sources'])
cell(tables[4].rows[9].cells[2],'Integrated release and historical remote-scheduler verification')
setrow(6,8,['N08','Classify and retain independent WDT/power counts; direct verified clear commands','ResetCause, Watchdog, WatchdogResetCounter, PowerResetCounter'])
row(tables[6],['N12','Retain complete samples for 24 elapsed hours and download scoped history','TelemetryArchive, TelemetryJournal, S25Fl064L; matching server archive'])
setrow(7,3,['Publication','Latest committed sample -> Status mapper -> encrypted selected route; explicit live fallback','Original sample identity; operational valve/reset/power refreshed'])
row(tables[7],['Archive','Complete cycle -> canonical Telemetry -> four-slot queue -> CRC/commit-last -> stored history','CMD14 advances export only after server database persistence'])
row(tables[8],['External storage','Probe/recover; capture/commit; elapsed retention; memory queries; paced acknowledged history'])
row(tables[9],['External SPI1 flash','CS PA4 / SCK PA5 / MISO PA6 / MOSI PA7; 3.3 V','S25FL064L JEDEC 01 60 17; common GND, local decoupling and inactive control pulls'])
setrow(10,5,['power/','Controller sleep FSM and selectable wake input','PowerManager, RemoteWakeCycle, WorWakeInput'])
setrow(10,6,['platform/','Captured reset classification, progress WDT and independent counters','Watchdog, ResetCause, WatchdogResetCounter, PowerResetCounter'])
row(tables[10],['storage/','SPI NOR adapter, commit-last journal and paced archive service','NorFlash, S25Fl064L, TelemetryJournal, TelemetryArchive'])
setrow(11,1,['USE_SIM800 / USE_ESP8266','ESP8266 fallback selection in header; inactive in LoRa leaf','Select one for direct/gateway IP images; no automatic failover'])
setrow(11,3,['APP_UPLINK','APP_UPLINK_LORA_TO_GATEWAY','LoRa leaf uses no direct IP modem; gateway selects its own uplink'])
setrow(11,4,['APP_NODE_ID / APP_SENSOR_ID','2 / 1','Assign unique node identity; topic builder and payload must agree'])
setrow(11,8,['kDefaultSamplingPeriodMs / kDefaultTransmissionPeriodMs','10000 / 15000','Independent in NORMAL/scheduled REMOTE_WAKE; WOR uses report cycle'])
row(tables[11],['APP_MQTT_COMPANY / APP_MQTT_REGION','Company_1 / Region_1','Topic path scope; rebuild for a deployment change'])
topics=[['Routine Status','wiot/{company}/{region}/{node}/status'],['Telemetry / command reply','wiot/{company}/{region}/{node}/data'],['Direct command','wiot/{company}/{region}/{node}/cmd'],['Regional broadcast','wiot/{company}/{region}/broadcast'],['Gateway command wildcard','wiot/{company}/{region}/+/cmd']]
cell(tables[24].rows[2].cells[3],'Command identifier, 1..14; ID14 is internal persistence ACK')
for j,r in enumerate(topics,1):setrow(18,j,r)
row(tables[20],['Application payload / fragment data','640 / 27 bytes','At most 24 fragments; 32-bit received mask'])
setrow(28,5,['LORA_WOR_STOP / 5','STM32 Stop + E32 Mode 2','Default UART RX falling-edge wake; RTC report/expiry/heartbeat; RAM retained'])
setrow(30,6,['LORA_WOR with SIM/ESP route or LoRa NORMAL','Stop wake policy requires the matching LoRa WOR hardware/protocol pairing'])
setrow(31,1,['APP_POWER_SLEEP_SECONDS','120 s','Timed Standby interval / WOR report-cycle deadline; legacy remote interval'])
setrow(31,7,['APP_LORA_WOR_WATCHDOG_WAKE_SECONDS','15 s; accepted range 2..15','Foreground WDT maintenance; compile guard also requires timeout margin'])
row(tables[31],['APP_LORA_WOR_WAKE_SOURCE','UART_RX','AUX remains readiness input; legacy AUX is an explicit alternative'])
row(tables[32],['Offset 232..251','Power-on/brownout counter, 20 bytes','Verified clear/count commits; distinct from WDT and valve records'])
row(tables[32],['External SPI flash','2 metadata sectors + 2,046 data sectors','8 MiB; 14,322 slots; elapsed 24-hour retained batches'])
setrow(33,1,['Codec / MQTT / TinyGSM RX','640 / 1024 / 1024 bytes','Maximum Telemetry 546 plaintext / 577 encrypted bytes'])
setrow(33,3,['Largest recorded ARM load endpoint','0x08019908, WOR LoRa','30 October report; below 0x08020000 EEPROM sector'])
setrow(33,4,['Recorded flash margin before EEPROM','26,360 bytes at that endpoint','Recompute after runtime/library/configuration changes'])
setrow(33,5,['Largest recorded static RAM','36,036 bytes; nominal 29,500 bytes remain','ELF data+BSS; runtime stack/heap peak is not measured'])
setrow(33,6,['Recorded compilation','8 current SPI-release ARM profiles','Prior 16-profile remote report remains historical evidence'])
row(tables[33],['External log capacity','14,322 samples; 472-byte canonical payload per slot','Full stops append/drop count; no overwrite of unexpired data'])
setrow(34,2,['First-party source','src/app, devices, comm, power, platform, radio, storage, config'])
setrow(34,11,['Latest software verification','Release Documentation/Validation/SPI_FLASH_SOFTWARE_VERIFICATION_20261030.md'])
row(tables[34],['Whole-project flowcharts','Release Documentation/Flowcharts/; offline HTML, 34-page PDF, editable DOT/Mermaid/SVG'])
setrow(35,2,['One state mapper','Consistent fields plus sample sequence/time provenance across routes','No independent acquisition timestamp for each individual sensor'])
row(tables[35],['External commit-last journal','Retain samples across resets and recover torn writes','Finite RAM queue, no at-rest encryption and possible network-startup sampling gaps'])
setrow(36,5,['Node health','Battery voltage, global 30-s IWDG, independent WDT/power counters and verified clear commands'])
row(tables[36],['Scoped routing','Lowercase company/region/node status/data/cmd and regional broadcast; strict identity checks'])
row(tables[36],['Stored history','S25FL064L retained samples, 24-hour generations, memory commands and server-persistence ACK'])
row(tables[37],['N12','A31-A34 flash and history','JEDEC/status, generation/sequence, acquisition time, commit/ACK and power-cut logs'])
cell(tables[37].rows[2].cells[1],'A07-A08 RTC and consumption; A28 independent reference')
cell(tables[37].rows[4].cells[1],'A10-A12 transport/LoRa; A29 regional routing')
cell(tables[37].rows[7].cells[1],'A18-A20 recovery; A27 counters and clear')
cell(tables[37].rows[8].cells[1],'A21-A25 power modes; A30 UART RX WOR')
setrow(38,6,['Medium','Per-sensor freshness','Sample sequence/time validity now exists; each individual sensor still lacks its own acquisition timestamp'])
setrow(38,7,['Medium','Calibrated whole-node energy study','Retain initial LoRa 9-mA observation; measure inputs, powered population and duty-cycle traces'])
setrow(38,8,['Medium','External-log endurance/soak and future binary OTA','SPI sample storage is implemented; qualify retention/wear/real interruption. OTA remains future work'])
row(tables[39],['Two reset counters and independent simulator reference','RESET_COUNTERS_AND_SUPMEA_REFERENCE_GUIDE.md'])
row(tables[39],['Regional MQTT routes','REGIONAL_MQTT_TOPICS_GUIDE.md'])
row(tables[39],['UART-RX WOR wake','LORA_WOR_RX_WAKE_GUIDE.md; release Documentation/Validation/LORA_WOR_9MA_BENCH_RESULT_20261029.md'])
row(tables[39],['External journal and acceptance','SPI_FLASH_TELEMETRY_GUIDE.md; SPI_FLASH_TEST_PLAN.md'])
row(tables[39],['Complete system flows','Release Documentation/Flowcharts/README.md'])
row(tables[40],['Repeated AUX wake before Stop','Selected wake source, pending IRQs, UART RX idle HIGH and correct pin','Use current UART_RX path; AUX remains ready/busy. Retest commands and RTC separately'])
row(tables[40],['Power count unchanged after RESET','Captured RCC/PWR flags and actual reset method','NRST/ST-Link/software reset is not power-on; remove/reapply supply for a power-count test'])
row(tables[40],['Flash empty or no stored sample','JEDEC, trusted STIME, explicit CLEAR_FLASH, Ready and full-cycle capture','Check drops/queue and stored_sample/live_fallback; do not assume accepted append is durable'])
row(tables[40],['History stalls or appears incomplete','Same scope/request ID, server commit/ACK14, timeout, terminal result','A successful download needs all frozen records plus successful End; live ingestion stays separate'])

# Extend existing schema tables directly from authoritative field definitions.
proto=(ROOT/'Node/IoT_Node_Encrypted/src/generated/sensor.proto').read_text(encoding='utf-8')
messages={}
for name,body in re.findall(r'message\s+(\w+)\s*\{(.*?)\}',proto,re.S):
    messages[name]=[(int(tag),field,kind) for kind,field,tag in re.findall(r'^\s*(\w+)\s+(\w+)\s*=\s*(\d+)\s*;',body,re.M)]
meaning={
 'power_reset_count':'Persistent power-on/brownout count; excludes Standby/software reset',
 'sample_sequence':'Generation-relative acquisition sequence; gaps may occur',
 'sample_time_valid':'Acquisition timestamp was trusted; independent of meter period RTC validity',
 'stored_sample':'Measurements read from retained committed storage',
 'live_fallback':'Runtime measurements used because stored Status was unavailable',
 'flash_log':'Optional FlashLogInfo memory status record',
 'history':'Optional HistoryInfo transfer identity, progress and result',
}
for ti,name in [(23,'Status_Message'),(25,'Telemetry')]:
    seen={r.cells[1].text for r in tables[ti].rows[1:]}
    for tag,field,kind in sorted(messages[name]):
        if field not in seen:row(tables[ti],[str(tag),field,kind,meaning[field]])
    actual={(int(r.cells[0].text),r.cells[1].text,r.cells[2].text) for r in tables[ti].rows[1:]}
    assert actual==set(messages[name]),'Schema table mismatch: '+name
flash_meanings=['0 disabled / 1 missing / 2 unformatted / 3 recovering / 4 ready / 5 full / 6 fault','JEDEC manufacturer/device ID','Physical bytes','Data capacity after reserved metadata','Occupied slot bytes, including unusable/torn slots','Remaining slot bytes','Valid committed current-generation records','Maximum sample slots','Retained batch identity','Newest committed sample sequence','Persisted UTC batch start','Batch start + 86400 s','Old sectors remaining to reclaim','Skipped/failed appends since runtime accounting','Rejected corrupt records','Archive work is pending','Clock may drive capture and retention']
history_meanings=['Original server command/transfer ID','Retained batch identity','Original sample sequence','Transfer row index','Frozen matching record count','Node calendar YYYYMMDD at acceptance','1 last / 2 today','1 preparing / 2 record / 3 end','0 OK / 1 empty / 2 not ready / 3 untrusted / 4 cancelled / 5 retention changed / 6 ACK timeout / 7 read-encode failure / 8 busy','Server must commit before sending CMD14']
anchor=paras[238]
before(anchor,'5.9.5  Memory and history metadata','Heading 3')
newtable(anchor,'Table 41. FlashLogInfo deployed fields',['Tag','Name','Type','Unit / meaning'],[[str(tag),field,kind,flash_meanings[tag-1]] for tag,field,kind in sorted(messages['FlashLogInfo'])],25)
newtable(anchor,'Table 42. HistoryInfo deployed fields',['Tag','Name','Type','Unit / meaning'],[[str(tag),field,kind,history_meanings[tag-1]] for tag,field,kind in sorted(messages['HistoryInfo'])],25)
for r in [
 ['7 / CLEAR_POWER_RESETS','0 + nonzero request ID','Direct node only; persist/read back power count zero; WDT unchanged'],
 ['8 / CLEAR_WDT_RESETS','0 + nonzero request ID','Direct node only; persist/read back WDT zero; power unchanged'],
 ['9 / CLEAR_FLASH','0 + nonzero request ID','Direct + trusted RTC; accept new durable batch; reclaim old sectors asynchronously'],
 ['10 / FLASH_STATUS','0','Explicit memory state/capacity/count/progress response'],
 ['11 / FLASH_LAST','0','Original last retained sample; no new sensor poll'],
 ['12 / FLASH_TODAY','0 or packed generation/sequence','Frozen retained current calendar day; paced records plus explicit terminal result'],
 ['13 / FLASH_CANCEL','0','Cancel active export; retain samples'],
 ['14 / HISTORY_ACK','(phase << 32) | index','Internal same-request persistence ACK; direct only; no automatic response'],
]:row(tables[26],r)

anchor=paras[288]
before(anchor,'5.15  External telemetry journal and history','Heading 2')
for heading,body in [
 ('5.15.1  Device and sample format','The node uses S25FL064L, 64 Mbit or 8 MiB, JEDEC 01 60 17. SPI1 is dedicated at 4 MHz initially: PA4 CS, PA5 SCK, PA6 MISO and PA7 MOSI. Use 3.3-V supply/logic and required inactive pulls/decoupling. The driver refuses writes to an unexpected identity; it does not guess a compatible geometry or issue whole-chip erase.'),
 ('5.15.2  Capture and publication','After every complete sensor cycle, capture canonical Telemetry with the original trusted UTC acquisition time and node calendar day. Remove command/history metadata, check the 472-byte bound and copy into one of four RAM queue entries. A successful append means queued, not durable. Poll program/erase progress in step(), verify the body/CRC, then write the commit marker last. Full/queue/unready/I/O failures count drops instead of overwriting retained records.'),
 ('5.15.3  Boot recovery and elapsed retention','Two alternating metadata sectors carry generation/identity/geometry/CRC/commit state. Recovery selects the newest valid copy and scans bounded data steps. Torn slots are consumed rather than reused. Blank/unknown format requires direct CLEAR_FLASH with trusted RTC. Every batch expires after 86400 elapsed UTC seconds from its persisted start, not at midnight or after each reboot. Untrusted/backward time prevents automatic time-based erase. A generation change hides old records before background physical reclamation; every sweep rechecks sector ownership so it cannot erase newly allocated samples.'),
 ('5.15.4  Memory requests and acknowledged export','FLASH_STATUS returns geometry, records, free/used and erase progress. FLASH_LAST returns the most recent retained committed acquisition. FLASH_TODAY freezes node calendar day, generation and final sequence, then sends one row at a time after higher-priority work. It covers only the currently retained part of today. The server stores each scoped row in a separate SQLite archive transaction before CMD14; matching request/phase/index advances the node. Retries include the first send and are bounded by the configured attempts and timeout. Completion requires all declared records and a successful End; empty, cancel, expiry, busy, read failure and ACK timeout have explicit outcomes.'),
 ('5.15.5  Power coordination and limits','Archive recovery/write/clear/transfer guards defer sleep. A download keeps the node active while permitting new acquisition; its frozen set excludes later samples. Idle flash enters deep power-down and resumes after clocks return. RTC sleep planning includes retained-log expiry. Clearing the sample log leaves reset counters, valve state and SUPMEA period records intact; server archives already persisted are separate. Missing/faulted/disabled flash allows marked live fallback. Internal EEPROM remains shared and vulnerable to interruption; external NOR is not encrypted at rest, and connectivity startup may still leave acquisition gaps.'),
]:
    before(anchor,heading,'Heading 3');before(anchor,body)
newtable(anchor,'Table 43. External journal geometry',['Item','Value','Interpretation'],[
 ['Physical capacity','8,388,608 bytes','2 x 4096-byte metadata sectors plus 2046 data sectors'],
 ['Data sector','512-byte header area + 7 x 512-byte slots','14,322 maximum records; fixed stable layout'],
 ['Canonical sample','At most 472 protobuf bytes','Record CRC and commit metadata occupy the remainder'],
 ['Queue','4 samples','RAM-only until commit-last completes'],
 ['Retention','86,400 elapsed seconds','Calendar TODAY filtering is a different operation'],
 ['Media policy','Stop appending when full','Expose drops; no overwrite of unexpired records'],
],20)
newtable(anchor,'Table 44. SPI logging controls',['Macro','Current value','Bounds / meaning'],[
 ['APP_ENABLE_SPI_FLASH','true','false preserves live-only reporting; disabled path does not open SPI'],
 ['APP_FLASH_SPI_HZ','4000000','100000..12000000 Hz'],
 ['APP_FLASH_HISTORY_ACK_TIMEOUT_MS','60000','10000..300000 ms; tune for low-rate LoRa'],
 ['APP_FLASH_HISTORY_MAX_ATTEMPTS','3','1..5 total attempts, including first send'],
],31)

# Add independent acceptance procedures before the API appendix.
anchor=paras[519]
tests=[
 ('A27  Power and watchdog counters','Record both counts and cause. Press NRST or use software reset: neither increments. Remove/reapply power: only power increments. Inject a controlled IWDG stall: only WDT increments. Send direct CMD7 then CMD8 with data 0 and fresh IDs; verify durable zero and the unaffected other count. Repeat rejected broadcast/nonzero-data/duplicate cases. Expected: verified selected clear, no MCU reset and no change to meter or valve records.'),
 ('A28  Independent SUPMEA reference','Use NORMAL first, auto-totalizers enabled, volumetric unit 3 and real-time x1. Synchronize node UTC and the simulator calendar/session, establish the node baseline, then compare deltas after a known interval. At 36 m3/h, 60 s corresponds to 0.600 m3 before display/float rounding. The simulator integrates flow independently; the node subtracts cumulative forward totals. Export reference and node results. No new day/month/year registers may appear on the bus.'),
 ('A29  Regional MQTT identity','Use Company_1 / Region_1 and the actual selected node. Observe lowercase status/data/cmd plus regional broadcast. Send direct GOSTM and verify matching node/region. Try a mismatched payload ID and a command from another region. Expected: matched scope succeeds; invalid scope/identity is rejected; histories and command receipts stay isolated.'),
 ('A30  UART RX LoRa WOR','Build leaf LORA_WOR plus radio WAKE_ON_RADIO and UART_RX wake; gateway NORMAL with WOR TX=1. Match channel, network and IDs. Capture idle RX HIGH, no pending IRQ and Stop request. Observe low current, multiple 15-s maintenance heartbeats, two report cycles and a gateway GOSTM wake/reply. Expected: clock restore precedes work; AUX-only activity does not claim a command; normal Stop wakes do not increment reset counters. Log command latency and a two-node shared-channel run.'),
 ('A31  SPI probe and explicit initialization','Fit the documented 3.3-V S25FL064L. Check JEDEC 01 60 17 and FLASH_STATUS. Blank media is Unformatted without silent erase. Set trusted STIME, send direct CLEAR_FLASH data 0, then wait for Ready and completed clear progress. Repeat with wrong ID/missing/protected media in controlled fixtures. Expected: no unknown-device writes and explicit live fallback when storage cannot be used.'),
 ('A32  Sample commit and retention','Run distinct samples and verify record count/sequence and FLASH_LAST acquisition time. Compare routine Status stored_sample to the last committed record while current operational counters remain fresh. Exercise queue/full/time-untrusted and elapsed 24-hour expiry, including reboot and backward-time cases. Keep old-batch allocation/reclamation interleaved. Expected: drops exposed, no premature midnight clear or new-sector erasure, retained valid commits recovered after real bench power cuts.'),
 ('A33  History download and server ACK','Download TODAY using a fresh request ID; compare frozen total and every indexed scoped server row. Add new samples during transfer, drop/delay one ACK, duplicate a row and confirm bounded resend/dedup. Cancel and separately expire the batch. Expected: no missing/duplicate stored rows, later samples excluded from that job, explicit terminal result and no injection into live charts/consumption.'),
 ('A34  Storage with each transport and power policy','Repeat STATUS/LAST/TODAY over SIM, Wi-Fi and updated LoRa gateway, then normal/remote/periodic/queued/WOR supported combinations. Test automatic action ACK disabled: explicit storage data queries still respond and ACK14 never loops. Expected: commands precede bulk traffic, sampling remains possible during export, pending archive work prevents premature sleep and retention maintenance does not reset sensor totals.'),
]
for heading,body in tests:before(anchor,heading,'Heading 2');before(anchor,body)

# Updated public interfaces and scoped-storage API reference.
anchor=paras[697]
before(anchor,'PowerResetCounter.h','Heading 3')
before(anchor,'Independent saturating POR/BOR counter. initialize(bool), value(), clear(), storageHealthy() and recoveredInvalidRecord() follow the same verified-storage contract as the WDT counter.')
before(anchor,'ResetCause.h','Heading 3');before(anchor,'Capture RCC/PWR flags before clearing them; classify IWDG, genuine power and excluded warm/Standby events. The snapshot is consumed by both counters and early power handoff.')
before(paras[675],'WorWakeInput.h','Heading 3');before(paras[675],'Attach/detach UART RX or optional AUX wake without discarding the first serial byte. Snapshot and validate selected EXTI pending state before Stop; restore the normal UART configuration after clock recovery.')
before(anchor,'B.storage  Storage modules','Heading 2')
for heading,body in [
 ('NorFlash and S25Fl064L','Bounded SPI NOR operations, known JEDEC guard, explicit 4-byte-address read/program/erase, status polling, timeouts and deep power-down/resume.'),
 ('TelemetryJournal','begin(), step(epoch,trusted), append(), requestClear(), readRecord(), latest(), info(), busy(), ready(), expiry() and occupiedSlots() implement fixed-memory queueing, recovery, generation changes and commit-last record access.'),
 ('TelemetryArchive','begin(), step(), capture(), storedStatus(), handle(), reply(), packet() and published() connect sampling and commands to the journal. blocking(), transferring(), writePending(), maintenanceDue(), expiry(), prepareSleep() and resume() coordinate application priorities and sleep.'),
]:before(anchor,heading,'Heading 3');before(anchor,body)
before(paras[694],'bool clear();  // Persist/read back WDT zero without resetting the MCU')

# Selected full-size engineering flows; the complete package remains the system map.
before(paras[718],'The complete thirty-chart index is in Documentation/Flowcharts/README.md. Appendix D embeds the core node/time/recovery/power/storage flows; the offline viewer also covers server internals, gateway routing and simulator operation.')
section=doc.add_section(WD_SECTION_START.NEW_PAGE)
section.different_first_page_header_footer=False
numbering=section._sectPr.find(qn('w:pgNumType'))
if numbering is not None:numbering.attrib.pop(qn('w:start'),None)
section.orientation=WD_ORIENT.LANDSCAPE
section.page_width=Inches(16.5354);section.page_height=Inches(11.6929)
section.left_margin=doc.sections[0].left_margin
section.right_margin=doc.sections[0].right_margin
section.top_margin=Inches(.74);section.bottom_margin=Inches(.70)
chart_folder=ROOT/'Documentation/Flowcharts'
defs={c['id']:c for c in json.loads(re.search(r'const charts=(.*);\nlet current=',(chart_folder/'WIOT_Project_Flowcharts.html').read_text(encoding='utf-8'),re.S).group(1))}
layouts={r['id']:r for r in json.loads((chart_folder/'layout_report.json').read_text())}
tmp=HERE/'tmp/design';tmp.mkdir(parents=True,exist_ok=True)
selected=['F01','F03','F04','F09','F18','F20','F22','F23','F24','F25']
for i,key in enumerate(selected):
    if i:doc.add_page_break()
    chart=defs[key];layout=layouts[key]
    heading=doc.add_paragraph(('Appendix D  Node flowcharts' if i==0 else 'D'+str(i+1)+'  '+chart['title']),'Heading 1' if i==0 else 'Heading 2')
    heading.paragraph_format.page_break_before=False
    if i==0:doc.add_paragraph(key+' '+chart['title'],'Heading 2')
    doc.add_paragraph(chart['purpose'])
    png=tmp/(key+'.png')
    subprocess.run(['C:/Program Files/Graphviz/bin/dot.exe','-Tpng','-Gdpi=200',str(chart_folder/'source'/f'{chart["slug"]}.dot'),'-o',str(png)],check=True)
    scale=min((14.3*72)/layout['width'],(6.8*72)/layout['height'],1.35)
    p=doc.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before=Pt(3);p.paragraph_format.space_after=Pt(5)
    p.add_run().add_picture(str(png),width=Inches(layout['width']*scale/72))
    for note in chart['notes']:doc.add_paragraph(note)
    p=doc.add_paragraph('Source chart '+key+'; full verified paths and editable sources in Documentation/Flowcharts.');p.style='Caption'

# Renumber table captions in body order; preserve original fields and template package.
counter=0
for p in doc.paragraphs:
    if p._p not in {original._p for original in paras} and p.style.name in ('Normal','Caption'):
        sample=paras[117] if p.style.name=='Normal' else paras[122]
        for run in p.runs:
            if sample.runs and sample.runs[0]._r.rPr is not None:
                if run._r.rPr is not None:run._r.remove(run._r.rPr)
                run._r.insert(0,deepcopy(sample.runs[0]._r.rPr))
    if p.style.name.startswith('Heading'):
        p.paragraph_format.keep_with_next=True
        props=p._p.get_or_add_pPr()
        num=props.find(qn('w:numPr'))
        if num is None:num=OxmlElement('w:numPr');props.append(num)
        numid=num.find(qn('w:numId'))
        if numid is None:numid=OxmlElement('w:numId');num.append(numid)
        numid.set(qn('w:val'),'0')
    if re.match(r'Table \d+\.',p.text):
        counter+=1;text(p,re.sub(r'^Table \d+\.',f'Table {counter}.',p.text))
for section in doc.sections:
    for part in (section.header,section.footer,section.first_page_header,section.first_page_footer):
        for node in part._element.iter(qn('w:t')):
            if node.text:node.text=node.text.replace('WIOT-NOD-DDS-07-001-V1.0','WIOT-NOD-DDS-07-001-V1.1')
for name in ('Title','Subtitle','Heading 1','Heading 2','Heading 3'):
    if name in doc.styles:doc.styles[name].font.color.rgb=RGBColor(0,0,0)
settings=doc.settings.element
update=settings.find(qn('w:updateFields'))
if update is None:update=OxmlElement('w:updateFields');settings.append(update)
update.set(qn('w:val'),'true')
doc.core_properties.version='1.1'
doc.core_properties.title='WIOT STM32 Node Software Design'
doc.core_properties.subject='Revision 1.1 - current Arduino STM32 design and verification'
doc.save(PATH)
print('Updated',PATH,'tables',counter,'embedded flows',len(selected))
