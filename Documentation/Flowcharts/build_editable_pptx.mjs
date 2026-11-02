/** Editable WIOT flowcharts. Requires the supplied @oai/artifact-tool runtime. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const workspaceDir = path.dirname(fileURLToPath(import.meta.url));
const buildDir = path.join(workspaceDir, 'tmp/pptx');
const SKILL_DIR = process.env.WIOT_PRESENTATION_SKILL_DIR || 'C:/Users/Selim/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations';
const RUNTIME_PYTHON = process.env.WIOT_RUNTIME_PYTHON || 'C:/Users/Selim/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
const {importRuntimeModule} = await import(pathToFileURL(path.join(SKILL_DIR,'container_tools/runtime_helpers.mjs')).href);
const {Presentation, PresentationFile, FileBlob} = await importRuntimeModule('@oai/artifact-tool');
const {finalizePresentation,resolvePresentationFont} = await import(pathToFileURL(path.join(SKILL_DIR,'container_tools/artifact_tool_utils.mjs')).href);
const FONT=resolvePresentationFont({fontFamily:'Arial'});
const W=1920, H=1080;
const FINAL_PPTX=path.resolve(process.env.WIOT_FINAL_PPTX || path.join(workspaceDir,'output/pptx/WIOT_Project_Flowcharts_Editable.pptx'));
const C={ink:'#173E5B',muted:'#526B7C',rule:'#CAD8E1',white:'#FFFFFF'};
const PALETTE={
  term:{geometry:'roundRect',fill:'#173E5B',color:'#FFFFFF',stroke:'#173E5B'},
  proc:{geometry:'roundRect',fill:'#EAF2F8',color:'#163B55',stroke:'#91A9BC'},
  dec:{geometry:'diamond',fill:'#FFF1D2',color:'#513F12',stroke:'#C4A35E'},
  db:{geometry:'can',fill:'#E1F2ED',color:'#214B43',stroke:'#7DA89B'},
  bad:{geometry:'roundRect',fill:'#FBE9E9',color:'#733C3C',stroke:'#C49393'},
  ref:{geometry:'roundRect',fill:'#EEEAF8',color:'#4B416D',stroke:'#A69BC7'},
};
await fs.mkdir(buildDir,{recursive:true});

if(process.argv.includes('--finalize')) {
  await fs.mkdir(path.dirname(FINAL_PPTX),{recursive:true});
  const nativeTables=[35,36,37,38];
  const result=await finalizePresentation({
    workspaceDir,candidatePath:path.join(buildDir,'candidate.pptx'),finalPath:FINAL_PPTX,
    pythonExecutable:RUNTIME_PYTHON,
    integrityValidatorPath:path.join(SKILL_DIR,'container_tools/inspect_presentation_package_integrity.py'),
    layoutValidatorPath:path.join(SKILL_DIR,'container_tools/inspect_presentation_layout_geometry.py'),
    explicitTotalSlideCount:38,
    requiredNativeTableOwnerSlides:nativeTables,requiredNativeChartOwnerSlides:[],
    layoutArgs:['--expected-slide-size-emu','18288000,10287000','--validate-bullet-geometry','--validate-heading-fit',
      ...nativeTables.flatMap(n=>['--require-native-table-slide',String(n)])],
    fontPolicy:{basis:'design',families:[FONT]},verifyArtifactToolImport:true,
    receiptPath:path.join(buildDir,path.basename(FINAL_PPTX)+'.'+Date.now()+'.validation.json')
  });
  console.log(JSON.stringify({finalPath:result.finalPath,sha256:result.finalSha256,bytes:result.byteCount,
    slides:result.presentationLayout.slide_count,findings:result.presentationLayout.findingCount,
    firstPartyImportPassed:result.firstPartyImport.passed}));
} else if(process.argv.includes('--render')) {
  const deck=await PresentationFile.importPptx(await FileBlob.load(FINAL_PPTX));
  const renderDir=path.join(buildDir,'renders');await fs.mkdir(renderDir,{recursive:true});
  for(const [i,slide] of deck.slides.items.entries()) {
    const blob=await deck.export({slide,format:'png',scale:1});
    await fs.writeFile(path.join(renderDir,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
    console.log('Rendered slide',i+1);
  }
} else {
  const data=JSON.parse(await fs.readFile(path.join(buildDir,'flowchart-layouts.json'),'utf8'));
  const presentation=Presentation.create({slideSize:{width:W,height:H}});
  const bindings={};
  function text(slide,name,value,x,y,w,h,size=26,color=C.ink,bold=false,align='left') {
    const shape=slide.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
    shape.text=value;shape.text.style={typeface:FONT,fontSize:size,color,bold,alignment:align,verticalAlignment:'middle',autoFit:'none',wrap:'none',insets:0};
    return shape;
  }
  function base(title,subtitle,tag) {
    const slide=presentation.slides.add();slide.background.fill=C.white;
    text(slide,'Slide title',title,72,44,1776,62,42,C.ink,true);
    if(subtitle)text(slide,'Purpose',subtitle,72,112,1776,62,23,C.muted).text.wrap='square';
    text(slide,'Page',`${tag}   ${presentation.slides.items.length}`,72,1032,1776,28,18,C.muted,false,'right');
    return slide;
  }
  function notes(slide,body) {slide.speakerNotes.text=body;}
  function block(slide,name,label,x,y,w,h,kind='proc',fontSize=27) {
    const p=PALETTE[kind];
    const shape=slide.shapes.add({geometry:p.geometry,name,position:{left:x,top:y,width:w,height:h},fill:p.fill,line:{fill:p.stroke,width:1.5}});
    shape.text=label;
    shape.text.style={typeface:FONT,fontSize,color:p.color,alignment:'center',verticalAlignment:'middle',wrap:'none',autoFit:'none',insets:0,lineSpacing:1.04};
    return shape;
  }
  function cover() {
    const slide=presentation.slides.add();slide.background.fill=C.white;
    text(slide,'Organization','EgSA  /  WIOT',100,85,1500,52,28,C.muted);
    text(slide,'Cover title','WIOT software\nflowcharts',100,210,1690,238,92,C.ink,true);
    text(slide,'Scope','Arduino STM32 node, LoRa gateway, Python server and sensor simulator',105,515,1700,60,31,C.muted);
    const stages=[['Sensors','Four RS485 interfaces'],['STM32 node','Acquisition and control'],['MQTT / LoRa','Selected transport'],['Server','Storage and commands']];
    const shapes=stages.map((s,i)=>block(slide,'Cover '+s[0],s.join('\n'),105+i*449,700,363,116,i===0?'proc':i===3?'db':'term',27));
    for(let i=0;i<3;i++)slide.shapes.connect(shapes[i],shapes[i+1],{fromSide:'right',toSide:'left',kind:'straight',line:{fill:'#587083',width:2},tail:{type:'triangle'}});
    text(slide,'Edition','30 flowcharts with editable shapes, text and arrows',105,910,1700,45,28,C.ink);
    text(slide,'Date',data.date,105,980,1700,36,23,C.muted);
    notes(slide,`Editable conversion of the existing WIOT flowchart reference. Source baseline ${data.baseline}.\nAll 30 chart definitions, notes and source anchors are preserved. Firmware/server behavior was not changed.\nUse PowerPoint Selection Pane to select named nodes and arrows. Each process node contains its own editable text. Each routed arrow is a native editable freeform object. When moving boxes, adjust arrow endpoints separately using Edit Points. Notes contain the original detailed caveats and source paths.`);
  }
  function catalog(start,end) {
    const slide=base('Flowchart index',start===0?'System, acquisition and communication':'Commands, power, storage and server',`Index ${start===0?1:2}`);
    data.charts.slice(start,end).forEach((chart,i)=>{
      const y=205+i*52;
      text(slide,`Index ${chart.id}`,chart.id,78,y,100,46,27,C.ink,true);
      text(slide,`Index title ${chart.id}`,chart.title,188,y,1530,46,27,C.ink);
      text(slide,`Index page ${chart.id}`,String(start+i+5),1730,y,110,46,25,C.muted,false,'right');
    });
    notes(slide,'Slide numbers refer to this editable PowerPoint. The F01-F30 identifiers match the existing HTML/PDF reference.');
  }
  function legend() {
    const slide=base('Flowchart symbols and editing','Each diagram uses native PowerPoint objects','Guide');
    const items=[['term','Entry or result'],['proc','Process or action'],['dec','Decision'],['db','Stored data'],['bad','Failure or rejection'],['ref','Related flow or feature']];
    items.forEach(([kind,label],i)=>{
      const col=i%2,row=Math.floor(i/2),x=85+col*920,y=220+row*222;
      block(slide,'Legend '+kind,kind==='dec'?'Decision?':label,x,y,390,148,kind,26);
      text(slide,'Meaning '+kind,label,x+422,y+31,470,88,29,C.ink);
    });
    text(slide,'Edit instructions','Edit text inside shapes. Select named objects in the Selection Pane. Use Edit Points for arrow routes and adjust endpoints after moving boxes. Speaker Notes contain caveats and code references.',85,920,1750,75,25,C.muted).text.wrap='square';
    notes(slide,'Each routed arrow is a native editable freeform object. Use Shape Format > Edit Shape > Edit Points to adjust its route. When moving a node, adjust its incoming/outgoing arrow endpoints separately. The simple cover links use attached straight connectors. Dashed arrows retain the reference meaning: return/cross-path links, not background threads.');
  }
  function diagram(chart) {
    const slide=base(`${chart.id}  ${chart.title}`,chart.purpose,chart.id);
    const [x0,y0,x1,y1]=chart.bb;
    const area={x:65,y:195,w:1790,h:805};
    const scale=Math.min(area.w/(x1-x0+30),area.h/(y1-y0+24));
    const ox=area.x+(area.w-(x1-x0)*scale)/2,oy=area.y+(area.h-(y1-y0)*scale)/2;
    const xy=p=>({x:ox+(p[0]-x0)*scale,y:oy+(y1-p[1])*scale});
    const nodes={};
    for(const n of chart.nodes) {
      const p=xy([n.x-n.w/2,n.y+n.h/2]);
      const shape=block(slide,`${chart.id} node ${n.id}`,n.label,p.x,p.y,n.w*scale,n.h*scale,n.kind,17*scale);
      nodes[n.id]={data:n,shape};
    }
    const page=String(presentation.slides.items.length);bindings[page]=[];
    for(const e of chart.edges) {
      const points=e.points.map(p=>xy(p));const tip=xy(e.tip);
      const all=[...points,tip];
      const left=Math.min(...all.map(p=>p.x)),top=Math.min(...all.map(p=>p.y));
      const width=Math.max(1,Math.max(...all.map(p=>p.x))-left),height=Math.max(1,Math.max(...all.map(p=>p.y))-top);
      const commands=[{moveTo:{x:points[0].x-left,y:points[0].y-top}}];
      for(let i=1;i<points.length;i+=3)commands.push({cubicBezTo:{x1:points[i].x-left,y1:points[i].y-top,x2:points[i+1].x-left,y2:points[i+1].y-top,x:points[i+2].x-left,y:points[i+2].y-top}});
      commands.push({lineTo:{x:tip.x-left,y:tip.y-top}});
      const edge=slide.shapes.add({geometry:'custom',name:e.name,position:{left,top,width,height},fill:'none',line:{fill:'#587083',width:Math.max(1.8,1.15*scale),style:e.dashed?'dashed':'solid'},customPaths:[{width,height,commands}]});
      edge.sendToBack();
      bindings[page].push({name:e.name,source:e.source,target:e.target});
      e.labels.forEach((label,i)=>{
        const p=xy([label.x,label.y]);
        // Separate near-adjacent branch labels while retaining the routed graph.
        const offsets={
          'F01:r:g:Radio':[-14,-4], 'F01:g:r:Commands':[22,0],
          'F17:d:i:Storage failure':[260,0], 'F21:c:e:Ready':[-40,0],
          'F24:i:g:Next sector':[-20,-8], 'F24:j:g:Next sector':[15,12],
          'F28:d:h:No / no device':[-15,0], 'F28:h:d:Continue':[60,-26]
        };
        const [dx,baseDy]=offsets[`${chart.id}:${e.source}:${e.target}:${label.text}`]||[0,0];
        const dy=baseDy+i*4*scale; // Keep separate lines' white text frames clear.
        const shape=text(slide,`${e.name} label ${i+1}`,label.text,p.x-(label.w*scale+14)/2+dx,p.y-14*scale+dy,label.w*scale+14,19*scale,14*scale,'#405C70',false,'center');
        shape.fill=C.white;
      });
    }
    notes(slide,`${chart.purpose}\n\nImplementation notes\n${chart.notes.map(n=>'- '+n).join('\n')}\n\nCode references\n${chart.sources.map(s=>s.path+':'+s.line+'\n'+s.anchor).join('\n\n')}\n\nReference source baseline ${data.baseline}. Diagram ${chart.id}.\nNative editable nodes and routed freeform arrows. Select objects by name in PowerPoint Selection Pane. Adjust arrow endpoints separately after moving nodes.`);
  }
  function nativeTable(title,subtitle,headers,rows,widths,tag,note) {
    const slide=base(title,subtitle,tag);
    const values=[headers,...rows];
    const table=slide.tables.add({rows:values.length,columns:headers.length,left:72,top:205,width:1776,height:720,columnWidths:widths,values});
    table.borders.assign({fill:'#CAD8E1',width:1,style:'solid'});
    for(let r=0;r<values.length;r++) {
      table.rows[r].height=720/values.length;
      for(let c=0;c<headers.length;c++) {
        const cell=table.getCell(r,c);cell.fill=r===0?C.ink:r%2?'#F1F6FA':C.white;
        cell.text.style={typeface:FONT,fontSize:22,color:r===0?C.white:C.ink,bold:r===0,alignment:'left',verticalAlignment:'middle',autoFit:'none',wrap:'square',insets:12};
      }
    }
    text(slide,'Table note',note,76,946,1768,70,23,C.muted).text.wrap='square';
    notes(slide,`Editable native PowerPoint table. Source: Documentation/Flowcharts/build_flowcharts.py (${tag}).\n${note}\nReference baseline ${data.baseline}.`);
  }
  if(process.argv.includes('--sample')) diagram(data.charts[21]);
  else {
    cover();catalog(0,15);catalog(15,30);legend();
    data.charts.forEach(diagram);
    const widths=[65,300,330,300,781];
    const cmdNote='Command data uses seconds for SRATE/STRAN. Node validation is authoritative. Automatic action replies follow APP_ENABLE_COMMAND_ACK_REPLIES.';
    nativeTable('Command catalog 1–7','Configuration, telemetry, valve control and reset counters',['ID','Command','Data','Scope','Behavior'],data.commands.slice(0,7),widths,'Commands 1-7',cmdNote);
    nativeTable('Command catalog 8–14','Reset counter, flash queries and acknowledged history',['ID','Command','Data','Scope','Behavior'],data.commands.slice(7),widths,'Commands 8-14','Explicit storage queries still respond. HISTORY_ACK confirms server persistence and advances one transfer item.');
    const powerWidths=[140,180,260,280,430,486];
    nativeTable('Supported power combinations','Controller and selected-radio selectors',['Role','Transport','Controller','Active radio','Wake or work source','Behavior'],data.power.slice(0,6),powerWidths,'Power 1','Unselected modules may still draw current unless hardware disables or disconnects them.');
    nativeTable('WOR, gateway and unsupported combinations','Supported combinations and build-time restrictions',['Role','Transport','Controller','Active radio','Wake or work source','Behavior'],data.power.slice(6),powerWidths,'Power 2','Protocol mode IDs differ from compile-time selectors. RTC schedules wakeups. Watchdog expiry resets the controller.');
  }
  await (await PresentationFile.exportPptx(presentation)).save(path.join(buildDir,'draft.pptx'));
  await fs.writeFile(path.join(buildDir,'edge-manifest.json'),JSON.stringify(bindings,null,2));
  await fs.writeFile(path.join(buildDir,'authoring-manifest.json'),JSON.stringify({slides:presentation.slides.items.length,font:FONT,slideSize:{width:W,height:H},baseline:data.baseline},null,2));
  console.log('Exported native draft:',presentation.slides.items.length,'slides');
}
