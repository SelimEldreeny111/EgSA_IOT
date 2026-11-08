/** Audience overview: five stages, one command-return path, four supporting services. */
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
const tmp=path.join(here,'tmp/simple'),out=path.join(here,'output');
await fs.mkdir(tmp,{recursive:true});await fs.mkdir(out,{recursive:true});
const final=path.resolve(process.env.WIOT_SIMPLE_PPTX || path.join(out,'WIOT_Software_Overview_Simple_v2.1.pptx'));
if(process.argv.includes('--finalize')){
 const r=await finalizePresentation({workspaceDir:here,candidatePath:path.join(tmp,'candidate.pptx'),finalPath:final,
   pythonExecutable:python,integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
   layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
   explicitTotalSlideCount:2,requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],
   layoutArgs:['--expected-slide-size-emu','30480000,17145000','--validate-bullet-geometry','--validate-heading-fit'],
   fontPolicy:{basis:'design',families:[FONT]},verifyArtifactToolImport:true,
   receiptPath:path.join(tmp,`validation-${Date.now()}.json`)});
 console.log(JSON.stringify({path:r.finalPath,sha256:r.finalSha256,findings:r.presentationLayout.findingCount,import:r.firstPartyImport.passed}));
 process.exit(0);
}
const C={ink:'#123B55',body:'#455F70',blue:'#167EAD',purple:'#8054A0',pale:'#EFF6FA',rule:'#D5E2EA',green:'#287D70'};
const p=Presentation.create({slideSize:{width:W,height:H}});
const s=p.slides.add();s.background.fill='#FFFFFF';
const svg=[`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><defs>`,
 `<marker id="blue" markerWidth="20" markerHeight="18" refX="17" refY="9" orient="auto" markerUnits="userSpaceOnUse"><path d="M0 0L18 9L0 18Z" fill="${C.blue}"/></marker>`,
 `<marker id="purple" markerWidth="20" markerHeight="18" refX="17" refY="9" orient="auto" markerUnits="userSpaceOnUse"><path d="M0 0L18 9L0 18Z" fill="${C.purple}"/></marker>`,
 '</defs><rect width="3200" height="1800" fill="white"/>'];
const texts=[],arrows=[],blocks=[];
const esc=x=>String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
function text(name,value,x,y,w,h,size=32,color=C.body,bold=false,align='left'){
 const sh=s.shapes.add({name,geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 sh.text=value;sh.text.style={typeface:FONT,fontSize:size,color,bold,alignment:align,verticalAlignment:'middle',autoFit:'none',wrap:'none',insets:0,lineSpacing:1.14};
 texts.push({name,value,x,y,w,h,size,bold});
 const lines=value.split('\n');
 lines.forEach((line,i)=>svg.push(`<text x="${align==='center'?x+w/2:x}" y="${y+h/2+(i-(lines.length-1)/2)*size*1.22+size*.34}" font-family="Arial,sans-serif" font-size="${size}" fill="${color}" font-weight="${bold?700:400}" text-anchor="${align==='center'?'middle':'start'}">${esc(line)}</text>`));
}
function rect(name,x,y,w,h,fill='none',stroke=C.rule,radius=true,width=2){
 s.shapes.add({name,geometry:radius?'roundRect':'rect',position:{left:x,top:y,width:w,height:h},fill,line:{fill:stroke,width}});
 svg.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${radius?14:0}" fill="${fill}" stroke="${stroke}" stroke-width="${width}"/>`);
}
function circle(name,x,y,d,fill=C.blue){
 s.shapes.add({name,geometry:'ellipse',position:{left:x,top:y,width:d,height:d},fill,line:{fill:'none',width:0}});
 svg.push(`<circle cx="${x+d/2}" cy="${y+d/2}" r="${d/2}" fill="${fill}"/>`);
}
function line(name,pts,color=C.blue,width=5,arrow=false){
 const left=Math.min(...pts.map(p=>p[0])),top=Math.min(...pts.map(p=>p[1]));
 const w=Math.max(1,Math.max(...pts.map(p=>p[0]))-left),h=Math.max(1,Math.max(...pts.map(p=>p[1]))-top);
 const commands=pts.map((v,i)=>i?{lineTo:{x:v[0]-left,y:v[1]-top}}:{moveTo:{x:v[0]-left,y:v[1]-top}});
 s.shapes.add({name,geometry:'custom',position:{left,top,width:w,height:h},fill:'none',line:{fill:color,width},customPaths:[{width:w,height:h,commands}]});
 svg.push(`<polyline points="${pts.map(p=>p.join(',')).join(' ')}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" ${arrow?`marker-end="url(#${color===C.purple?'purple':'blue'})"`:''}/>`);
 if(arrow)arrows.push(name);
}
function icon(kind,cx,cy){
 if(kind==='sensors'){
  line('Icon sensor bus',[[cx-75,cy+28],[cx+75,cy+28]],C.blue,5);
  for(const [i,dx] of [-60,0,60].entries()){
   line('Icon sensor stem '+i,[[cx+dx,cy-10],[cx+dx,cy+28]],C.blue,5);
   circle('Icon sensor probe '+i,cx+dx-10,cy-28,20);
  }
 }else if(kind==='node'){
  rect('Icon MCU',cx-48,cy-43,96,86,'#FFFFFF',C.blue,true,5);
  rect('Icon MCU core',cx-21,cy-19,42,38,C.pale,C.blue,false,3);
  for(const [i,dy] of [-25,0,25].entries()){
   line('Icon MCU left '+i,[[cx-68,cy+dy],[cx-48,cy+dy]],C.blue,5);
   line('Icon MCU right '+i,[[cx+48,cy+dy],[cx+68,cy+dy]],C.blue,5);
  }
 }else if(kind==='link'){
  line('Icon connection shaft',[[cx,cy+40],[cx,cy-3]],C.blue,5);
  circle('Icon connection origin',cx-8,cy-13,16);
  line('Icon radio left',[[cx-34,cy+12],[cx-48,cy-10],[cx-48,cy-32]],C.blue,5);
  line('Icon radio right',[[cx+34,cy+12],[cx+48,cy-10],[cx+48,cy-32]],C.blue,5);
  line('Icon radio far left',[[cx-67,cy+24],[cx-84,cy-5],[cx-84,cy-43]],C.blue,5);
  line('Icon radio far right',[[cx+67,cy+24],[cx+84,cy-5],[cx+84,cy-43]],C.blue,5);
 }else if(kind==='server'){
  for(const [i,dy] of [-31,21].entries()){
   rect('Icon server rack '+i,cx-66,cy+dy-15,132,40,'#FFFFFF',C.blue,true,5);
   circle('Icon server light '+i,cx-45,cy+dy-2,13);
   line('Icon server slot '+i,[[cx-12,cy+dy+4],[cx+43,cy+dy+4]],C.blue,4);
  }
 }else{
  rect('Icon monitor',cx-75,cy-45,150,90,'#FFFFFF',C.blue,true,5);
  line('Icon monitor stand',[[cx,cy+45],[cx,cy+65],[cx-40,cy+65],[cx+40,cy+65]],C.blue,5);
  line('Icon monitor readings',[[cx-48,cy+15],[cx-20,cy-5],[cx+6,cy+5],[cx+45,cy-25]],C.blue,5);
 }
}
text('Title','How WIOT software works',100,60,3000,100,68,C.ink,true);
text('Subtitle','Measurements go to the dashboard. Commands return to the node.',100,180,3000,70,39,C.body);
text('Data direction','MEASUREMENTS AND REPLIES',100,315,3000,48,28,C.blue,true);
const stages=[
 {id:'sensors',title:'Sensors',x:100,body:'TUF / Supmea\nFlow and water volume\n\nHNDA / Sondas\nSoil measurements'},
 {id:'node',title:'STM32 node',x:725,body:'Read the sensors\nCalculate water totals\nSave the sample\nSend when due'},
 {id:'link',title:'Connection',x:1350,body:'LoRa via a gateway\nor WiFi / SIM directly\n\nMQTT message exchange'},
 {id:'server',title:'Python server',x:1975,body:'Validate the message\nStore readings + history\nHandle commands'},
 {id:'dashboard',title:'Dashboard',x:2600,body:'See live readings\nReview stored samples\nControl the node'},
];
for(let i=0;i<stages.length-1;i++)line('Flow measurements '+(i+1),[[stages[i].x+480,660],[stages[i+1].x-8,660]],C.blue,5,true);
line('Flow commands return',[[2840,910],[2840,1040],[965,1040],[965,918]],C.purple,5,true);
for(const [i,a] of stages.entries()){
 blocks.push('Stage '+a.id);
 rect('Stage '+a.id,a.x,420,480,490,i===1||i===3?C.pale:'#FFFFFF',C.rule,true,2);
 text('Step '+a.id,String(i+1).padStart(2,'0'),a.x+27,441,90,36,23,C.body);
 icon(a.id,a.x+240,515);
 text('Heading '+a.id,a.title,a.x+24,605,432,56,40,C.ink,true,'center');
 text('Body '+a.id,a.body,a.x+25,685,430,195,31,C.body,false,'center');
}
text('Return path','Commands return through the server to the node',1060,1080,1780,54,36,C.purple,true,'center');
text('Command examples','Settings  /  valve control  /  wake-up  /  flash requests',1060,1140,1780,44,29,C.body,false,'center');
text('Supporting heading','Supporting services inside the node',100,1260,3000,65,39,C.ink,true);
const services=[
 {id:'quality',title:'Measurements and time',x:100,w:690,body:'Validate readings. Use RTC time\nfor day, month and year totals.'},
 {id:'flash',title:'Local storage',x:880,w:690,body:'Save samples to SPI flash.\nKeep a 24-hour batch.'},
 {id:'recovery',title:'Automatic recovery',x:1660,w:690,body:'Watchdog and modem retry recovery.\nTrack watchdog and power resets.'},
 {id:'sleep',title:'Power management',x:2440,w:640,body:'Sleep between scheduled work.\nRadio wake when supported.'},
];
for(const a of services){
 blocks.push('Service '+a.id);
 rect('Service '+a.id,a.x,1360,a.w,235,'#F7F9FA','none',true,0);
 rect('Service accent '+a.id,a.x,1360,62,5,C.green,'none',false,0);
 text('Heading '+a.id,a.title,a.x+24,1390,a.w-48,52,34,C.ink,true);
 text('Body '+a.id,a.body,a.x+24,1470,a.w-48,92,29,C.body);
}
text('Priority note','The node handles commands before routine sampling and reporting.',100,1670,3000,65,34,C.green,true);
s.speakerNotes.text='Simple audience overview. Source baseline c604aa6a5a49c61f86bada826a329dc600dac9f6, Arduino STM32 release.\n\nRead the five main stages left to right. The purple return path is a conceptual route through server and the same connection, not a direct dashboard-to-radio physical link. The connection block summarizes two alternative compiled routes: node -> LoRa -> STM32 gateway -> WiFi/SIM MQTT -> broker -> Python server, OR node -> WiFi/SIM MQTT -> broker -> server. The broker is included within the connection stage to avoid a separate technical hop on this audience overview.\n\nAll four RS485 sensors are individually enabled/addressed. TUF supplies native period totals; Supmea periods derive from cumulative forward-volume changes with trusted RTC. Failed sensor groups are zeroed with invalid quality. Complete samples are committed to external S25FL064L before stored reporting when available; live fallback is explicitly marked. Flash retention is 24 elapsed hours, not midnight. Explicit flash queries return metadata or retained samples.\n\nCommands have cooperative priority, not instantaneous preemption of in-flight operations. Automatic action ACKs are configurable. Valve replies confirm software pulse, without position feedback. LoRa WOR uses UART RX wake with a gateway Mode-1 probe; AUX remains readiness. RTC alarms schedule wake; hardware watchdog expiry resets. Timed Standby cannot receive immediate radio commands. Independent SRATE and STRAN deadlines apply in scheduled REMOTE_WAKE and default LORA_WOR. APP_LORA_WOR_USE_APP_SCHEDULE=false selects legacy WOR using APP_POWER_SLEEP_SECONDS. Stop residence ages the task clocks using RTC time. A completed sensor cycle yields to an overdue Status even when sensors failed. The gateway subscribes to direct commands and regional broadcasts. OFF, LITE and FULL diagnostics are build choices. Reviewed 7 November 2026.\n\nSources: Node/IoT_Node_Encrypted/IoT_Node_Encrypted.ino; src/config/AppConfig.h; src/app/FlowMeterManager.cpp; src/comm/MQTT.cpp; src/radio/LoraLink.cpp; src/power/PowerManager.cpp; src/platform/Watchdog.cpp; src/storage/TelemetryArchive.cpp; Server/WIOT-Server-Web v1.31 - Fixed Sensor Readings in Dashboard/server_web.py and flash_archive.py. Detailed workflows remain in Documentation/Flowcharts. Native editable text, blocks, icons and routed arrows; adjust endpoints after moving blocks.';
const scene=p.slides.add();scene.background.fill='#FFFFFF';
const illustration=await fs.readFile(path.join(out,'WIOT_Node_Gateway_Server_Illustration.png'));
scene.images.add({blob:illustration.buffer.slice(illustration.byteOffset,illustration.byteOffset+illustration.byteLength),contentType:'image/png',fit:'contain',position:{left:0,top:0,width:W,height:H},alt:'Representative illustration of two field sensor nodes, LoRa gateway, MQTT broker, Python server and dashboard.'});
scene.speakerNotes.text='Existing system illustration preserved from v1.0, generated with the built-in Image Generation tool. It is representative, not an as-built photograph. Complete prompt: Documentation/SystemOverview/image_prompt.txt. The flowchart on slide 1 has been simplified; software and hardware behavior are unchanged.';
svg.push('</svg>');
await fs.writeFile(path.join(out,'WIOT_Software_Overview_Simple_v2.1.svg'),svg.join('\n'));
await fs.writeFile(path.join(tmp,'manifest.json'),JSON.stringify({texts,arrows,blocks,stages:stages.length,services:services.length,width:W,height:H},null,2));
await (await PresentationFile.exportPptx(p)).save(path.join(tmp,'draft.pptx'));
console.log(JSON.stringify({slides:2,mainStages:stages.length,supportServices:services.length,arrows:arrows.length}));
