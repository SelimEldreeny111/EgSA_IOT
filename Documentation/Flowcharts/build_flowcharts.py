"""Build the reviewed WIOT flowchart reference and offline viewer.

Requires Python with ReportLab/pypdf and a Graphviz dot executable. No firmware
build, live server, broker, hardware port or private credential file is opened.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import textwrap
import xml.etree.ElementTree as ET

from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.lib.colors import HexColor, Color, white
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

from charts import CHARTS, N, S, M, E, C

HERE=Path(__file__).resolve().parent
BASELINE='c604aa6a5a49c61f86bada826a329dc600dac9f6'
DATE='7 November 2026'
W,H=landscape(A3)
MARGIN=43
PLOT=(43,211,W-86,493)
INK='#173E5B'
PALETTE={
    'term':dict(shape='box',style='rounded,filled',fillcolor=INK,fontcolor='white',color=INK),
    'proc':dict(shape='box',style='rounded,filled',fillcolor='#EAF2F8',fontcolor='#163B55',color='#91A9BC'),
    'dec':dict(shape='diamond',style='filled',fillcolor='#FFF1D2',fontcolor='#513F12',color='#C4A35E'),
    'db':dict(shape='cylinder',style='filled',fillcolor='#E1F2ED',fontcolor='#214B43',color='#7DA89B'),
    'bad':dict(shape='box',style='rounded,filled',fillcolor='#FBE9E9',fontcolor='#733C3C',color='#C49393'),
    'ref':dict(shape='box',style='rounded,filled',fillcolor='#EEEAF8',fontcolor='#4B416D',color='#A69BC7'),
}

COMMANDS=[
 ['1','SRATE','10..86400 seconds','Ordinary / scoped','Set the node sampling period; node bounds are authoritative.'],
 ['2','STRAN','10..86400 seconds','Ordinary / scoped','Set the node routine transmission period.'],
 ['3','STIME','Server UTC epoch','Ordinary / scoped','Validate and synchronize RTC; establish trusted time.'],
 ['4','GOSTM','No useful data','Data request','Return current runtime Telemetry; explicit reply remains enabled.'],
 ['5','VALVE','0 close; 1 open','Ordinary / scoped','Commissioned polarity pulse; state is commanded, not measured.'],
 ['6','WAKE','0 default; 1..86400 s','Supported power modes','Hold an active lease in REMOTE_WAKE, RTC_QUEUED or LORA_WOR.'],
 ['7','CLEAR_POWER_RESETS','0 + nonzero request ID','Direct node only','Persist and verify power counter zero; MCU is not reset.'],
 ['8','CLEAR_WDT_RESETS','0 + nonzero request ID','Direct node only','Persist and verify IWDG counter zero; MCU is not reset.'],
 ['9','CLEAR_FLASH','0 + nonzero request ID','Direct; trusted RTC','Accept a new log generation; physical reclamation is asynchronous.'],
 ['10','FLASH_STATUS','0','Direct data request','Return state, capacity, used/free slots, frame count and progress.'],
 ['11','FLASH_LAST','0','Direct data request','Return last retained committed sample with original acquisition time.'],
 ['12','FLASH_TODAY','0 or packed resume cursor','Direct data request','Freeze day/generation/final sequence and stream retained rows.'],
 ['13','FLASH_CANCEL','0','Direct node only','Cancel active export; does not erase the stored log.'],
 ['14','HISTORY_ACK','(phase << 32) | index','Internal; same job ID','Confirm server persistence; advance the transfer without an ACK loop.'],
]
POWER=[
 ['Sensor node','WiFi / SIM / LoRa','NORMAL (0)','NORMAL (0)','Continuous active operation','No automatic controller deep sleep.'],
 ['Sensor node','WiFi / SIM / LoRa','REMOTE_WAKE (2)','NORMAL (0)','UART/server command + app schedule','Light CPU Sleep; modem remains connected.'],
 ['Sensor node','ESP8266','POWER_DOWN (1)','POWER_DOWN (1)','RTC report-cycle deadline','ESP deep sleep/reset path; STM32 Standby.'],
 ['Sensor node','LoRa','POWER_DOWN (1)','POWER_DOWN (1)','RTC report-cycle deadline','Radio sleeps; no immediate downlink during Standby.'],
 ['Sensor node','ESP8266','QUEUED (4)','POWER_DOWN (1)','RTC + queued command after Status','Longer command window, optional active lease.'],
 ['Sensor node','LoRa','QUEUED (4)','POWER_DOWN (1)','RTC + queued command after Status','Gateway queues do not instantly wake a fully sleeping radio.'],
 ['Sensor node','LoRa','LORA_WOR (3)','WAKE_ON_RADIO (2)','UART RX / RTC heartbeat or deadline','STM32 Stop; E32 Mode 2 receive policy.'],
 ['Gateway','WiFi / SIM uplink','NORMAL (0)','Selected modem NORMAL','Always services LoRa and MQTT','LoRa is normal except temporary Mode-1 command wake TX.'],
 ['Rejected','Direct SIM800','POWER_DOWN / QUEUED','Any deep-sleep selection','Not supported on current PCB','Required PWRKEY/DTR/RI routing is absent.'],
 ['Rejected','Any selected modem','REMOTE_WAKE','POWER_DOWN / WOR radio','Cannot receive as this policy expects','Use NORMAL selected radio with reachable CPU Sleep.'],
 ['Rejected','Gateway','Any non-NORMAL','Any','Gateway service must stay available','Build-time guard rejects the combination.'],
]


def quote(value):
    return json.dumps(str(value),ensure_ascii=False)


def slug(chart):
    return chart['id']+'_'+re.sub(r'[^a-z0-9]+','_',chart['title'].lower()).strip('_')


def locate_sources(repo, charts):
    manifest={}
    for chart in charts:
        ids=[n['id'] for n in chart['nodes']]
        if len(set(ids))!=len(ids):raise ValueError('Duplicate nodes in '+chart['id'])
        for e in chart['edges']:
            if e['source'] not in ids or e['target'] not in ids:raise ValueError('Dangling edge in '+chart['id'])
        for node in chart['nodes']:
            if node['kind'] not in PALETTE:raise ValueError('Unknown shape')
        for ref in chart['sources']:
            path=(repo/ref['path']).resolve()
            path.relative_to(repo)
            if path.name in ('AppSecrets.h','AppConfig.cpp','.env','node_config.json'):raise ValueError('Private source requested')
            content=path.read_text(encoding='utf-8-sig')
            index=content.find(ref['anchor'])
            if index<0:raise ValueError(f'{chart["id"]} missing source anchor: {ref}')
            ref['line']=content[:index].count('\n')+1
            ref['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            manifest[ref['path']]=ref['sha256']
        chart['slug']=slug(chart)
    return manifest


def dot_source(chart, direction):
    lines=[f'// {chart["id"]} {chart["title"]}',f'digraph {chart["id"]} {{',
        f'graph [rankdir={direction}, bgcolor="transparent", pad="0.18", nodesep="0.25", ranksep="0.25", splines=polyline, outputorder=edgesfirst];',
        'node [fontname="Arial", fontsize=17, margin="0.13,0.09", penwidth=1.05];',
        'edge [fontname="Arial", fontsize=14, color="#587083", fontcolor="#405C70", arrowsize=0.72, penwidth=1.15];']
    stages={n['id']:n['stage'] for n in chart['nodes']}
    for node in chart['nodes']:
        attrs=PALETTE[node['kind']].copy();attrs['label']=node['label']
        lines.append(quote(node['id'])+' ['+', '.join(k+'='+quote(v) for k,v in attrs.items())+'];')
    for stage in sorted(set(stages.values())):
        lines.append('{rank=same; '+'; '.join(quote(k) for k,v in stages.items() if v==stage)+';}')
    for e in chart['edges']:
        attrs={}
        if e['label']:attrs['label']='\n'.join(textwrap.wrap(e['label'],23))
        if stages[e['target']]<=stages[e['source']]:attrs.update(constraint='false',color='#8195A4',style='dashed')
        lines.append(quote(e['source'])+' -> '+quote(e['target'])+' ['+', '.join(k+'='+quote(v) for k,v in attrs.items())+'];')
    return '\n'.join(lines+['}'])+'\n'


def mermaid_source(chart):
    lines=['flowchart TD']
    for n in chart['nodes']:
        label=html.escape(n['label'],quote=True).replace('\n','<br/>')
        if n['kind']=='dec':shape='{'+quote(label)+'}'
        elif n['kind']=='db':shape='[('+quote(label)+')]'
        elif n['kind']=='term':shape='(['+quote(label)+'])'
        else:shape='['+quote(label)+']'
        lines.append('  '+n['id']+shape+':::'+n['kind'])
    for e in chart['edges']:
        label=html.escape(e['label'].replace('|','/'),quote=True)
        lines.append('  '+e['source']+' -->'+('|'+label+'|' if label else '')+' '+e['target'])
    for kind,style in PALETTE.items():
        lines.append(f'  classDef {kind} fill:{style["fillcolor"]},color:{style["fontcolor"]},stroke:{style["color"]}')
    return '\n'.join(lines)+'\n'


def render_graphs(dot, output, temp, charts):
    reports=[]
    for chart in charts:
        choices=[]
        for direction in ('TB','LR'):
            path=temp/(chart['id']+'_'+direction+'.dot')
            path.write_text(dot_source(chart,direction),encoding='utf-8')
            svg=path.with_suffix('.svg');pdf=path.with_suffix('.pdf')
            for fmt,target in [('svg',svg),('pdf',pdf)]:
                result=subprocess.run([dot,'-T'+fmt,str(path),'-o',str(target)],capture_output=True,text=True)
                if result.returncode:raise RuntimeError(result.stderr)
            page=PdfReader(pdf).pages[0]
            w,h=float(page.mediabox.width),float(page.mediabox.height)
            scale=min(PLOT[2]/w,PLOT[3]/h,1.35)
            choices.append((scale,direction,path,svg,pdf,w,h))
        scale,direction,path,svg,pdf,w,h=max(choices,key=lambda v:v[0])
        chart.update(direction=direction,scale=scale,native_width=w,native_height=h,pdf=str(pdf))
        chart['svg']=svg.read_text(encoding='utf-8')
        chart['svg']=chart['svg'][chart['svg'].index('<svg'):]
        (output/'svg'/f'{chart["slug"]}.svg').write_text(chart['svg'],encoding='utf-8')
        shutil.copyfile(path,output/'source'/f'{chart["slug"]}.dot')
        (output/'source'/f'{chart["slug"]}.mmd').write_text(mermaid_source(chart),encoding='utf-8')
        reports.append(dict(id=chart['id'],direction=direction,width=round(w,1),height=round(h,1),
            node_font_pt=round(17*scale,2),edge_font_pt=round(14*scale,2),scale=round(scale,4)))
    return reports


def fonts():
    regular=Path('C:/Windows/Fonts/arial.ttf');bold=Path('C:/Windows/Fonts/arialbd.ttf')
    if regular.exists() and bold.exists():
        pdfmetrics.registerFont(TTFont('WIOT',str(regular)))
        pdfmetrics.registerFont(TTFont('WIOTBold',str(bold)))
        return 'WIOT','WIOTBold'
    return 'Helvetica','Helvetica-Bold'


REGULAR,BOLD=fonts()
BODY=ParagraphStyle('body',fontName=REGULAR,fontSize=11,leading=15,textColor=HexColor('#3B5365'))
SMALL=ParagraphStyle('small',fontName=REGULAR,fontSize=9.6,leading=12.6,textColor=HexColor('#425B6E'))


def paragraph(c,text,x,top,width,style=BODY):
    p=Paragraph(html.escape(text).replace('\n','<br/>'),style)
    _,height=p.wrap(width,1000)
    p.drawOn(c,x,top-height)
    return height


def frame(c, page, total, label):
    c.setFillColor(HexColor('#566E80'));c.setFont(REGULAR,9)
    c.drawString(MARGIN,H-30,'EgSA WIOT  |  Software flowcharts')
    c.drawRightString(W-MARGIN,H-30,label)
    c.setFont(REGULAR,8.8)
    c.drawString(MARGIN,29,'Source baseline '+BASELINE[:7]+'  |  '+DATE+'  |  Code-derived functional reference')
    c.drawRightString(W-MARGIN,29,f'{page:02} / {total:02}')


def title(c,text,subtitle=''):
    c.setFont(BOLD,24);c.setFillColor(HexColor('#172C3D'));c.drawString(MARGIN,H-70,text)
    if subtitle:paragraph(c,subtitle,MARGIN,H-89,W-2*MARGIN)


def cover(c,total):
    frame(c,1,total,'Read this first')
    c.bookmarkPage('cover');c.addOutlineEntry('Read this first','cover',0)
    c.setFillColor(HexColor('#000000'));c.setFont(BOLD,35);c.drawString(MARGIN,H-110,'WIOT software flowcharts')
    paragraph(c,'A complete functional map of the sensor node, LoRa gateway, Python server and test tools.',MARGIN,H-137,W-2*MARGIN)
    paragraph(c,'This reference follows the active Arduino STM32 release, including four-sensor acquisition, RTC consumption, modem recovery, valve control, power policies and the external telemetry log. The alternate ESP32 and native CubeIDE ports have a separate boundary in F30.',MARGIN,H-177,1030)
    labels=['RS485 sensors','STM32 node','Direct IP or LoRa gateway','Server and browser']
    x=MARGIN;y=H-330;boxw=245;gap=29
    for i,label in enumerate(labels):
        c.setFillColor(HexColor('#EAF2F8'));c.setStrokeColor(HexColor('#9AB2C4'));c.roundRect(x,y,boxw,64,7,stroke=1,fill=1)
        c.setFillColor(HexColor(INK));c.setFont(BOLD,14);c.drawCentredString(x+boxw/2,y+26,label)
        if i<3:
            c.setStrokeColor(HexColor('#53738A'));c.line(x+boxw+4,y+32,x+boxw+gap-4,y+32)
            p=c.beginPath();p.moveTo(x+boxw+gap-4,y+32);p.lineTo(x+boxw+gap-10,y+36);p.lineTo(x+boxw+gap-10,y+28);p.close();c.setFillColor(HexColor('#53738A'));c.drawPath(p,stroke=0,fill=1)
        x+=boxw+gap
    c.setFillColor(HexColor('#172C3D'));c.setFont(BOLD,17);c.drawString(MARGIN,H-384,'How to use the reference')
    items=[
      ('Start with the system','F01 whole system, F02 configuration, F03 startup and F04 scheduler.'),
      ('Follow one feature','F05-F10 sensing and payloads; F11-F18 communications, commands and recovery.'),
      ('Understand sleep and storage','F19-F25 cover supported power combinations, wake behavior and flash history.'),
      ('Trace the server and tools','F26-F30 cover ingestion, access, simulators, release checks and alternate ports.'),
    ]
    top=H-410
    for heading,body in items:
        c.setFillColor(HexColor(INK));c.setFont(BOLD,12);c.drawString(MARGIN,top,heading)
        paragraph(c,body,MARGIN+265,top+4,W-2*MARGIN-265);top-=44
    paragraph(c,'Read each arrow in its indicated direction. Dashed arrows return to an earlier phase or cross an already placed peer; they do not mean a background thread. Process blocks may summarize a bounded function or state-machine phase.',MARGIN,top-2,W-2*MARGIN)
    paragraph(c,'The PDF uses A3 landscape for legible engineering charts. The HTML viewer is offline, searchable and zoomable. Editable DOT and Mermaid sources accompany every diagram.',MARGIN,top-53,W-2*MARGIN)
    paragraph(c,'Reading a software flowchart does not prove hardware qualification. No private credentials or AES key values are included.',MARGIN,top-101,W-2*MARGIN,SMALL)
    c.linkRect('', 'contents', (MARGIN,48,MARGIN+180,72),relative=0,thickness=0)
    c.setFont(BOLD,12);c.setFillColor(HexColor('#176B99'));c.drawString(MARGIN,57,'Open chart index >')
    c.showPage()


def contents(c,total):
    frame(c,2,total,'Chart index')
    c.bookmarkPage('contents');c.addOutlineEntry('Chart index','contents',0)
    title(c,'Chart index','Choose an ID to jump to the full chart. The command catalog and power combination matrix follow the thirty flowcharts.')
    colw=(W-2*MARGIN-36)/2
    for i,chart in enumerate(CHARTS):
        col=0 if i<15 else 1;row=i%15;x=MARGIN+col*(colw+36);y=H-161-row*37
        c.setFillColor(HexColor('#EDF3F8'));c.roundRect(x,y-10,43,26,4,stroke=0,fill=1)
        c.setFont(BOLD,11);c.setFillColor(HexColor(INK));c.drawCentredString(x+21.5,y-1,chart['id'])
        c.setFont(REGULAR,11.2);c.drawString(x+55,y,chart['title'])
        c.setFont(REGULAR,9);c.setFillColor(HexColor('#698091'));c.drawRightString(x+colw,y,str(i+3))
        c.linkRect('',chart['id'],(x,y-11,x+colw,y+18),relative=0,thickness=0)
    c.setFont(BOLD,11);c.setFillColor(HexColor('#176B99'))
    c.drawString(MARGIN,75,'A1  Command catalog (IDs 1-14)');c.linkRect('','commands',(MARGIN,67,430,94),relative=0,thickness=0)
    c.drawString(W/2+18,75,'A2  Supported power combinations');c.linkRect('','power',(W/2+18,67,W-MARGIN,94),relative=0,thickness=0)
    c.showPage()


def short_ref(ref):
    p=ref['path']
    for prefix,alias in [(N,'Node/'),(S,'Server/'),(M,'MultiSensor/'),(E,'ESP32/'),(C,'CubeIDE/')]:
        if p.startswith(prefix):p=alias+p[len(prefix):];break
    return p+':'+str(ref['line'])


def chart_page(c,chart,index,total):
    frame(c,index+3,total,chart['section']+'  /  '+chart['id'])
    c.bookmarkPage(chart['id']);c.addOutlineEntry(chart['id']+' '+chart['title'],chart['id'],0)
    title(c,chart['title'],chart['purpose'])
    top=187
    for note in chart['notes']:
        height=paragraph(c,'- '+note,MARGIN,top,W-2*MARGIN)
        top-=height+9
    c.setFont(BOLD,9.4);c.setFillColor(HexColor('#405B6E'));c.drawString(MARGIN,105,'Source locations')
    for i,ref in enumerate(chart['sources']):
        c.setFont(REGULAR,9.1);c.drawString(MARGIN,89-i*12,short_ref(ref))
    c.setFont(REGULAR,8.7);c.setFillColor(HexColor('#5F7384'));c.drawRightString(W-MARGIN,55,'Index >')
    c.linkRect('','contents',(W-110,48,W-MARGIN,69),relative=0,thickness=0)
    c.showPage()


def table(c,headers,rows,widths,top,font=11):
    style=ParagraphStyle('table',fontName=REGULAR,fontSize=font,leading=font+3,textColor=HexColor('#213D51'))
    head=ParagraphStyle('head',parent=style,fontName=BOLD,textColor=white)
    cells=[[Paragraph(html.escape(x),head) for x in headers]]+[[Paragraph(html.escape(x),style) for x in row] for row in rows]
    tab=Table(cells,colWidths=widths,hAlign='LEFT')
    tab.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),HexColor('#173E5B')),('ROWBACKGROUNDS',(0,1),(-1,-1),[white,HexColor('#F0F5F9')]),
        ('GRID',(0,0),(-1,-1),.55,HexColor('#D4DFE7')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),
        ('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9),
    ]))
    _,height=tab.wrap(W-2*MARGIN,H)
    if top-height<105:raise ValueError(f'Table overflows page: {height}')
    tab.drawOn(c,MARGIN,top-height)
    return top-height


def appendices(c,total):
    frame(c,33,total,'A1 / Commands');c.bookmarkPage('commands');c.addOutlineEntry('A1 Command catalog','commands',0)
    title(c,'Command catalog','Use matching topic identity and a server-generated request ID. Explicit data requests and internal protocol ACKs differ from optional automatic action replies.')
    bottom=table(c,['ID','Name','Data','Scope','Behavior'],COMMANDS,[37,163,197,178,W-2*MARGIN-575],H-137,10.8)
    paragraph(c,'SRATE/STRAN are seconds in CMD data and milliseconds in Telemetry. The active node minimum is 10 s; broader server API input can still be rejected by the node. Automatic action replies follow APP_ENABLE_COMMAND_ACK_REPLIES; GOSTM and explicit storage queries still respond.',MARGIN,bottom-19,W-2*MARGIN,SMALL)
    c.showPage()
    frame(c,34,total,'A2 / Power combinations');c.bookmarkPage('power');c.addOutlineEntry('A2 Power combinations','power',0)
    title(c,'Supported power combinations','Values refer to controller and selected-radio macros in the active Arduino STM32 project. Policies for physically absent, unselected modules do not create independent power switches.')
    bottom=table(c,['Role','Transport','Controller selector','Active radio selector','Wake or work source','Behavior / constraint'],POWER,
        [95,127,162,171,244,W-2*MARGIN-799],H-137,10.5)
    paragraph(c,'Power protocol telemetry uses 1 NORMAL, 2 RTC_PERIODIC, 3 REMOTE_WAKE, 4 RTC_QUEUED and 5 LORA_WOR_STOP, which are not the same numbers as the compile-time controller selectors. Standby restarts startup; light Sleep and Stop retain their respective runtime state.',MARGIN,bottom-20,W-2*MARGIN,SMALL)
    c.showPage()


def build_pdf(output,temp,charts):
    base=temp/'reference_base.pdf';c=canvas.Canvas(str(base),pagesize=(W,H),pageCompression=1)
    c.setTitle('WIOT software flowcharts');c.setAuthor('EgSA WIOT');c.setSubject('Code-derived complete project workflows')
    total=34;cover(c,total);contents(c,total)
    for i,chart in enumerate(charts):chart_page(c,chart,i,total)
    appendices(c,total);c.save()
    writer=PdfWriter();writer.clone_document_from_reader(PdfReader(base))
    for i,chart in enumerate(charts):
        pg=PdfReader(chart['pdf']).pages[0]
        x=PLOT[0]+(PLOT[2]-chart['native_width']*chart['scale'])/2
        y=PLOT[1]+(PLOT[3]-chart['native_height']*chart['scale'])/2
        writer.pages[i+2].merge_transformed_page(pg,Transformation().scale(chart['scale']).translate(x,y))
    writer.compress_identical_objects(remove_duplicates=True,remove_unreferenced=True)
    path=output/'output/pdf/WIOT_Project_Flowcharts.pdf'
    with path.open('wb') as stream:writer.write(stream)
    check=PdfReader(path)
    if len(check.pages)!=34:raise ValueError('Unexpected PDF page count')
    for i,chart in enumerate(charts):
        text=check.pages[i+2].extract_text()
        if chart['title'] not in text:raise ValueError('Chart heading absent from PDF')
        for node in chart['nodes']:
            if node['label'].split('\n')[0] not in text:raise ValueError(f'Missing PDF node {chart["id"]} {node["id"]}')
    return path


def write_reader(output,charts,manifest,reports,dot):
    export=[]
    md=['# WIOT software flowcharts','',f'Reviewed {DATE}. Active source baseline `{BASELINE}`.','',
        'The HTML viewer and printable PDF contain the same thirty graphs. Source locations are verified against the code.','']
    for chart in charts:
        export.append({k:v for k,v in chart.items() if k not in ('pdf','scale','native_width','native_height')})
        export[-1]['baseline']=BASELINE
        md.extend([f'## {chart["id"]} {chart["title"]}','',chart['purpose'],'','```mermaid',mermaid_source(chart).rstrip(),'```',''])
        md.extend('- '+note for note in chart['notes']);md+=['','Sources: '+ '; '.join(short_ref(ref) for ref in chart['sources']), '']
    data=json.dumps(export,ensure_ascii=True).replace('</',r'<\/')
    viewer=(HERE/'viewer_template.html').read_text(encoding='utf-8').replace('__CHART_DATA__',data).replace('__EDITION_DATE__',DATE)
    (output/'WIOT_Project_Flowcharts.html').write_text(viewer,encoding='utf-8')
    (output/'WIOT_Project_Flowcharts.md').write_text('\n'.join(md),encoding='utf-8')
    (output/'source_manifest.json').write_text(json.dumps(dict(date=DATE,baseline=BASELINE,files=manifest,
        versions={key:importlib.metadata.version(key) for key in ('reportlab','pypdf')},
        graphviz=subprocess.run([dot,'-V'],capture_output=True,text=True).stderr.strip()),indent=2),encoding='utf-8')
    (output/'layout_report.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=HERE.parents[1])
    parser.add_argument('--output',type=Path,default=HERE)
    parser.add_argument('--dot',default=shutil.which('dot') or 'C:/Program Files/Graphviz/bin/dot.exe')
    args=parser.parse_args();repo=args.repo.resolve();output=args.output.resolve();temp=output/'tmp/pdfs'
    for sub in ('svg','source','output/pdf','tmp/pdfs'):(output/sub).mkdir(parents=True,exist_ok=True)
    manifest=locate_sources(repo,CHARTS)
    reports=render_graphs(args.dot,output,temp,CHARTS)
    for report in reports:
        if report['node_font_pt']<10 or report['edge_font_pt']<8.2:
            raise ValueError('Revise chart layout before delivery: '+json.dumps(report))
    pdf=build_pdf(output,temp,CHARTS)
    write_reader(output,CHARTS,manifest,reports,args.dot)
    print('Built',len(CHARTS),'charts and 34-page PDF:',pdf)
    print('Minimum effective node font:',min(x['node_font_pt'] for x in reports))
    print('Minimum effective edge font:',min(x['edge_font_pt'] for x in reports))


if __name__=='__main__':main()
