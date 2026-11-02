/** Single-page architecture overview; shared coordinates produce SVG and native PPTX. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const skill=process.env.WIOT_PRESENTATION_SKILL_DIR || 'C:/Users/Selim/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations';
const python=process.env.WIOT_RUNTIME_PYTHON || 'C:/Users/Selim/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
const {importRuntimeModule}=await import(pathToFileURL(path.join(skill,'container_tools/runtime_helpers.mjs')).href);
const {Presentation,PresentationFile}=await importRuntimeModule('@oai/artifact-tool');
const {finalizePresentation,resolvePresentationFont}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')).href);
const FONT=resolvePresentationFont({fontFamily:'Arial'}),W=3200,H=1800;
const tmp=path.join(here,'tmp'),out=path.join(here,'output');
await fs.mkdir(tmp,{recursive:true});await fs.mkdir(out,{recursive:true});
const final=path.join(out,'WIOT_System_Architecture_Overview_v1.0.pptx');
if(process.argv.includes('--finalize')) {
  const result=await finalizePresentation({workspaceDir:here,candidatePath:path.join(tmp,'candidate.pptx'),finalPath:final,
    pythonExecutable:python,integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
    layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
    explicitTotalSlideCount:2,requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],
    layoutArgs:['--expected-slide-size-emu','30480000,17145000','--validate-bullet-geometry','--validate-heading-fit'],
    fontPolicy:{basis:'design',families:[FONT]},verifyArtifactToolImport:true,
    receiptPath:path.join(tmp,`validation-${Date.now()}.json`)});
  console.log(JSON.stringify({path:result.finalPath,sha256:result.finalSha256,bytes:result.byteCount,
    findings:result.presentationLayout.findingCount,import:result.firstPartyImport.passed}));
  process.exit(0);
}
const ink='#153A55',muted='#526A7D',blue='#1478BA',purple='#80549B',green='#257865';
const nodes=[
  ['power',60,280,580,115,'Power and battery monitor',['Controller + converters + selected radio','ADC voltage with calibrated divider'],'support'],
  ['sensors',60,450,580,360,'Four independently enabled sensors',[
    'TUF: flow / velocity; native day, month, year',
    'Supmea: flow / cumulative forward totals',
    'HNDA (Honde): moisture / temperature',
    'Sondas: moisture / temperature / EC',
    'Each type has its own enable and slave ID',
    'All four can share the same RS485 bus'],'field'],
  ['bus',60,890,580,125,'Shared RS485 / Modbus RTU',[
    '9600 baud, 8N1; direction control',
    'CRC / address checks; bounded timeout / retries'],'field'],
  ['valve',60,1160,580,160,'Latching solenoid control',[
    'TB6612FNG polarity pulse; bridge then OFF',
    'Commissioned pulse times and pin checks',
    'Telemetry is commanded state; no position sensor'],'control'],
  ['sim',60,1435,580,160,'Bench sensor simulator',[
    'Multiple virtual sensors; unique bus addresses',
    'Fixed / changing values; fault testing',
    'Independent Supmea RTC comparison totals'],'support'],
  ['config',700,280,940,115,'Build configuration and boot',[
    'Role / uplink; four sensor enables + addresses; pins; power modes; ACK policy',
    'Private deployment settings and AES key remain local'],'core'],
  ['init',700,435,940,120,'Initialize and recover',[
    'Safe valve output; classify reset; recover persistent reset counters',
    'RTC, ADC, bus, selected radio, flash recovery; arm IWDG'],'core'],
  ['loop',700,605,940,120,'Cooperative application loop - COMMANDS FIRST',[
    'Pump LoRa / MQTT; validate target and request; dispatch command',
    'Prioritize replies; advance storage; then sample / report / history / power'],'core'],
  ['sample',700,805,400,120,'Sampling cycle when due',[
    'Poll one enabled sensor per pass',
    'Service command traffic in idle gaps'],'core'],
  ['snapshot',700,975,400,140,'Complete sensor snapshot',[
    'Zero unavailable sensor groups',
    'Attach validity, RTC, voltage, valve',
    'and persistent reset counters'],'core'],
  ['store',700,1155,400,150,'Commit sample to SPI flash',[
    'S25FL064L: 8 MiB NOR journal',
    'CRC, commit marker, recovery',
    'Retention: 24 elapsed hours'],'storage'],
  ['report',1200,1155,440,150,'Transmission cycle when due',[
    'Read latest committed sample',
    'Explicitly marked live fallback',
    'Keep original acquisition timestamp'],'core'],
  ['codec',1200,975,440,140,'Protobuf + AES-CBC envelope',[
    'Periodic Status; requested Telemetry',
    'Command result; flash metadata',
    'Stored samples / history progress'],'core'],
  ['execute',1200,805,440,120,'Execute accepted command',[
    'Rates / time / valve / wake / counters',
    'Flash clear, status, last, today, cancel'],'control'],
  ['rtc',700,1355,400,150,'RTC consumption service',[
    'Supmea forward-total differences',
    'Day / month / year boundaries',
    'Persist baseline / quality; TUF native'],'support'],
  ['wdt',1200,1355,440,150,'Watchdog / reset recovery',[
    '30 s IWDG; foreground progress',
    'Stall -> reset; retained reset counters',
    '10 retries: modem; next 10: full reset'],'support'],
  ['sleep',700,1555,940,115,'Idle / power manager',[
    'NORMAL; REMOTE_WAKE; RTC periodic / queued Standby; LoRa WOR Stop',
    'Wake for work / commands; RTC heartbeat feeds IWDG; storage guards sleep'],'support'],
  ['select',1690,605,590,120,'Select the compiled uplink',[
    'Direct WiFi / SIM MQTT, or LoRa to a gateway',
    'One route is active in a node build'],'core'],
  ['radio',1690,805,590,120,'E32 / AS32 LoRa transport',[
    'Logical frame, CRC, fragments, retries / ACKs',
    'Network ID / source node; UART RX wake'],'core'],
  ['gateway',1690,995,590,180,'STM32 LoRa gateway',[
    'Reassemble node payload -> MQTT publish',
    'Server CMD -> Mode-1 wake probe -> command',
    'Gateway NORMAL; sleeping nodes need WOR_TX=1',
    'Fragment handling takes priority over MQTT work'],'core'],
  ['ip',1690,1235,590,145,'Selected external IP modem',[
    'ESP8266 WiFi OR SIM800L GSM / GPRS',
    'MQTT connection / publish / receive callback',
    'Bounded network retries and reset recovery'],'core'],
  ['linknote',1690,1470,590,175,'Radio / MQTT contract',[
    'Telemetry upstream; commands downstream',
    'Gateway forwards the encrypted node payload',
    'LoRa ACK != broker receipt != node execution',
    'Execution requires a matching application reply'],'support'],
  ['broker',2330,280,810,115,'MQTT broker - company / region / node topics',[
    'wiot/{company}/{region}/{node}/data | status | cmd',
    'wiot/{company}/{region}/broadcast'],'core'],
  ['ingress',2330,450,810,120,'Python server: decrypt and validate',[
    'Envelope / padding; protobuf; topic-to-payload node identity',
    'Company / region access scope; validity and message classification'],'core'],
  ['classify',2330,620,810,120,'Route the decoded message',[
    'Status / live telemetry / command acknowledgement / flash reply',
    'Archived readings remain separate from live consumption / charts'],'core'],
  ['livedb',2330,815,380,165,'Live SQLite storage',[
    'Measurements + validity',
    'Consumption / reset counts',
    'Power and valve metadata'],'storage'],
  ['flashdb',2760,815,380,165,'Flash archive SQLite',[
    'Memory status + indexed samples',
    'History progress / generation',
    'History ACK only after commit'],'storage'],
  ['web',2330,1060,810,115,'Web dashboard, downloads and reports',[
    'Accounts / roles; company -> region -> node selection',
    'Live readings, charts, consumption, flash archive and CSV'],'core'],
  ['intent',2330,1250,810,120,'Operator command and execution tracking',[
    'Validate scope / arguments; allocate request ID; queue and retry',
    'Track broker receipt separately from node execution / rejection'],'control'],
  ['publish',2330,1450,810,145,'Encode / encrypt and publish CMD',[
    'SRATE, STRAN, STIME, telemetry, valve, WAKE, reset-counter clears',
    'Flash: clear / status / last / today / cancel',
    'History persistence acknowledgement advances the node transfer'],'control'],
];
const arrows=[];
function edge(id,pts,kind='data',both=false,label=null){arrows.push({id,pts,kind,both,label});}
edge('boot',[[1170,395],[1170,435]]);
edge('start-loop',[[1170,555],[1170,605]]);
edge('sampling',[[900,725],[900,805]]);
edge('poll-snapshot',[[900,925],[900,975]]);
edge('capture',[[900,1115],[900,1155]]);
edge('stored-read',[[1100,1217],[1200,1217]]);
edge('encode-report',[[1420,1155],[1420,1115]]);
edge('command-execute',[[1420,725],[1420,805]],'control');
edge('command-reply',[[1420,925],[1420,975]],'control',false,{text:'Result / explicit query reply',x:1220,y:936,w:405});
edge('sensor-wire',[[350,810],[350,890]]);
edge('bus-read',[[640,952],[665,952],[665,860],[700,860]]);
edge('bench-source',[[60,1507],[30,1507],[30,952],[60,952]],'service',false,{text:'Alternative test bus',x:65,y:1350,w:500});
edge('valve-command',[[700,675],[680,675],[680,1232],[640,1232]],'control');
edge('rtc-calculation',[[900,1095],[1120,1095],[1120,1422],[1100,1422]],'service');
edge('power-return',[[700,1607],[688,1607],[688,700],[700,700]],'service');
edge('loop-power',[[1640,700],[1652,700],[1652,1607],[1640,1607]],'service');
edge('uplink',[[1640,1035],[1668,1035],[1668,665],[1690,665]]);
edge('lora-route',[[1985,725],[1985,805]]);
edge('lora-gateway',[[1985,925],[1985,995]],'data',true);
edge('gateway-modem',[[1985,1175],[1985,1235]],'data',true);
edge('direct-route',[[2280,665],[2293,665],[2293,1297],[2280,1297]],'data',true,
  {text:'Direct MQTT bypasses gateway',x:1705,y:1390,w:555});
edge('node-command',[[1690,865],[1678,865],[1678,640],[1640,640]],'control');
edge('internet',[[2280,1320],[2310,1320],[2310,332],[2330,332]],'data',true);
edge('server-ingress',[[2735,395],[2735,450]]);
edge('server-route',[[2735,570],[2735,620]]);
edge('live-persist',[[2515,740],[2515,815]]);
edge('flash-persist',[[2950,740],[2950,815]]);
edge('live-view',[[2515,980],[2515,1060]]);
edge('flash-view',[[2950,980],[2950,1060]]);
edge('operator-intent',[[2735,1175],[2735,1250]],'control');
edge('command-publish',[[2735,1370],[2735,1450]],'control');
edge('broker-command',[[3140,1512],[3170,1512],[3170,332],[3140,332]],'control');
const presentation=Presentation.create({slideSize:{width:W,height:H}});
const slide=presentation.slides.add();slide.background.fill='#FFFFFF';
const svg=[];
function esc(s){return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');}
svg.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><defs>`);
for(const [id,col] of [['data',blue],['control',purple],['service',muted]])svg.push(`<marker id="${id}" markerWidth="12" markerHeight="10" refX="10" refY="5" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M 0 0 L 10 5 L 0 10 z" fill="${col}"/></marker>`);
svg.push('</defs><rect width="3200" height="1800" fill="white"/>');
function text(name,value,x,y,w,h,size=26,color=ink,bold=false,align='left'){
  const s=slide.shapes.add({name,geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  s.text=value;s.text.style={typeface:FONT,fontSize:size,color,bold,alignment:align,verticalAlignment:'middle',autoFit:'none',wrap:'none',insets:0,lineSpacing:1.1};
  const lines=value.split('\n');
  for(let i=0;i<lines.length;i++)svg.push(`<text x="${align==='center'?x+w/2:x}" y="${y+h/2+(i-(lines.length-1)/2)*size*1.18+size*.34}" font-family="Arial,sans-serif" font-size="${size}" fill="${color}" font-weight="${bold?700:400}" text-anchor="${align==='center'?'middle':'start'}">${esc(lines[i])}</text>`);
  return s;
}
text('Title','WIOT SOFTWARE ARCHITECTURE',60,45,3080,78,58,ink,true);
text('Scope','One overview of the active Arduino STM32 node, LoRa gateway, Python server and sensor simulator',60,130,3080,52,31,muted);
for(const [label,x,w] of [['FIELD INTERFACES',60,580],['ARDUINO STM32 SENSOR NODE',700,940],['COMMUNICATIONS / GATEWAY',1690,590],['MQTT BROKER / PYTHON WEB SERVER',2330,810]]){
 text('Lane '+label,label,x,205,w,45,29,ink,true);
 slide.shapes.add({name:'Lane rule '+label,geometry:'rect',position:{left:x,top:258,width:w,height:3},fill:ink,line:{fill:'none',width:0}});
 svg.push(`<path d="M${x} 258H${x+w}" stroke="${ink}" stroke-width="3"/>`);
}
const edgeNames=[];
for(const a of arrows){
 const col=a.kind==='control'?purple:a.kind==='service'?muted:blue;
 const left=Math.min(...a.pts.map(p=>p[0])),top=Math.min(...a.pts.map(p=>p[1]));
 const width=Math.max(1,Math.max(...a.pts.map(p=>p[0]))-left),height=Math.max(1,Math.max(...a.pts.map(p=>p[1]))-top);
 const commands=a.pts.map((p,i)=>i?{lineTo:{x:p[0]-left,y:p[1]-top}}:{moveTo:{x:p[0]-left,y:p[1]-top}});
 slide.shapes.add({name:'Arrow '+a.id,geometry:'custom',position:{left,top,width,height},fill:'none',
   line:{fill:col,width:3,style:a.kind==='service'?'dashed':'solid'},customPaths:[{width,height,commands}]});
 edgeNames.push({name:'Arrow '+a.id,both:a.both});
 svg.push(`<polyline points="${a.pts.map(p=>p.join(',')).join(' ')}" fill="none" stroke="${col}" stroke-width="3" ${a.kind==='service'?'stroke-dasharray="9 7"':''} marker-end="url(#${a.kind})" ${a.both?`marker-start="url(#${a.kind})"`:''}/>`);
}
const fills={field:'#EFF6FA',core:'#EAF2F8',storage:'#E7F3ED',control:'#F2EDF8',support:'#F4F6F8'};
for(const [id,x,y,w,h,title,body,kind] of nodes){
 const fill=fills[kind],border=kind==='storage'?green:kind==='control'?purple:'#9AB0C0';
 const shape=slide.shapes.add({name:'Block '+id,geometry:'roundRect',position:{left:x,top:y,width:w,height:h},fill,line:{fill:border,width:1.8}});
 // Identical SVG is deliberately kept simple so labels remain editable vector text.
 svg.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="13" fill="${fill}" stroke="${border}" stroke-width="1.8"/>`);
 text('Heading '+id,title,x+18,y+12,w-36,36,27,ink,true);
 const size=id==='sensors'?27:22;
 text('Body '+id,body.join('\n'),x+18,y+53,w-36,h-61,size,muted);
}
for(const a of arrows)if(a.label){const l=a.label;text('Label '+a.id,l.text,l.x,l.y,l.w,34,23,a.kind==='control'?purple:muted,false,'center');}
text('Legend','BLUE: measurements / transport     PURPLE: commands / replies     GREEN: stored data     DASHED: test or supporting service',60,1690,3080,40,25,muted);
text('Timing caveat','RTC schedules wakeups; IWDG expiry resets. WOR report timing uses APP_POWER_SLEEP_SECONDS; independent SRATE / STRAN applies to schedule-driven REMOTE_WAKE.',60,1740,3080,38,24,muted);
svg.push('</svg>');
await fs.writeFile(path.join(out,'WIOT_Software_Architecture.svg'),svg.join('\n'));
const sources=[
 'Node/IoT_Node_Encrypted/IoT_Node_Encrypted.ino',
 'Node/IoT_Node_Encrypted/src/config/AppConfig.h',
 'Node/IoT_Node_Encrypted/src/app/GatewayApp.cpp',
 'Node/IoT_Node_Encrypted/src/app/FlowMeterManager.cpp',
 'Node/IoT_Node_Encrypted/src/comm/MQTT.cpp',
 'Node/IoT_Node_Encrypted/src/radio/LoraLink.cpp',
 'Node/IoT_Node_Encrypted/src/power/PowerManager.cpp',
 'Node/IoT_Node_Encrypted/src/platform/Watchdog.cpp',
 'Node/IoT_Node_Encrypted/src/storage/TelemetryArchive.cpp',
 'Node/IoT_Node_Encrypted/src/storage/TelemetryJournal.cpp',
 'Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard/server_web.py',
 'Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard/flash_archive.py',
 'Documentation/Flowcharts/charts.py'];
slide.speakerNotes.text='Reviewed against final Arduino STM32 architecture, 2 November 2026. Functional architecture, not a wiring diagram or call graph. Native editable text, boxes and freeform arrows; use Selection Pane and Edit Points. Arrow endpoints must be adjusted after moving boxes.\n\nImportant distinctions: firmware roles are compiled separately. A node uses direct IP OR LoRa, not both simultaneously. The gateway has no local sensor polling/archive. RTC, not watchdog expiry, schedules normal wake. LoRa WOR uses UART RX falling-edge wake; AUX is radio readiness. Mode-1 probe may be truncated intentionally; the following command is preserved. Flash reset is 24 elapsed hours, not midnight; FLASH_TODAY filters the retained batch. TUF period totals are native; Supmea periods derive from cumulative forward-total changes. Valve ACK confirms software pulse, not physical position. Optional action ACK policy does not suppress explicit storage query responses. Sondas register map must match the purchased sensor. ESP32/CubeIDE ports are outside this active release overview.\n\nCode references:\n'+sources.join('\n');
const image=await fs.readFile(path.join(out,'WIOT_Node_Gateway_Server_Illustration.png'));
const scene=presentation.slides.add();scene.background.fill='#FFFFFF';
scene.images.add({blob:image.buffer.slice(image.byteOffset,image.byteOffset+image.byteLength),contentType:'image/png',alt:'Generated conceptual illustration: two RS485 field sensor nodes use LoRa to a gateway, then MQTT broker, Python web server and browser dashboard. Hardware appearance is representative.',fit:'contain',position:{left:0,top:0,width:W,height:H}});
scene.speakerNotes.text='Concept illustration generated with the built-in Image Generation tool. It represents the actual system topology, but PCB/enclosure appearance is illustrative and is not a photograph or as-built wiring reference. Each node has one selected uplink. The depicted gateway uses an external WiFi uplink; GSM is an alternative build. A server command returns through broker and gateway to the addressed node. See image_prompt.txt for the complete prompt and output provenance.';
await (await PresentationFile.exportPptx(presentation)).save(path.join(tmp,'draft.pptx'));
await fs.writeFile(path.join(tmp,'arrows.json'),JSON.stringify(edgeNames,null,2));
await fs.writeFile(path.join(tmp,'layout.json'),JSON.stringify({width:W,height:H,nodes,arrows,sources},null,2));
console.log(JSON.stringify({slides:2,blocks:nodes.length,arrows:arrows.length,font:FONT}));
