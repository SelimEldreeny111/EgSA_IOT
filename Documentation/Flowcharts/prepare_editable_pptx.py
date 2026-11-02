"""Prepare Graphviz layouts and preserve editable routed arrows in the PPTX.

No firmware/private configuration is read. Python standard library only for
layout/package work; PowerPoint authoring itself uses @oai/artifact-tool.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

HERE = Path(__file__).resolve().parent
NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
for key, uri in NS.items(): ET.register_namespace(key, uri)
def q(prefix, name): return '{' + NS[prefix] + '}' + name

def prepare(build, dot):
    from charts import CHARTS
    from build_flowcharts import COMMANDS, POWER, BASELINE, DATE, slug
    manifest = json.loads((HERE/'source_manifest.json').read_text(encoding='utf-8'))
    def layout(chart):
        graph = json.loads(subprocess.check_output([dot, '-Tjson', str(HERE/'source'/(slug(chart)+'.dot'))], timeout=120))
        native = {n['_gvid']: n for n in graph['objects'] if 'pos' in n}
        by_name = {n['name']: n for n in native.values()}
        nodes = []
        for node in chart['nodes']:
            n = by_name[node['id']]
            x,y = map(float,n['pos'].split(','))
            nodes.append(dict(node, x=x, y=y, w=float(n['width'])*72, h=float(n['height'])*72))
        edges = []
        for index,e in enumerate(graph['edges']):
            paths = [op['points'] for op in e.get('_draw_',[]) if op['op'] == 'b']
            if len(paths)!=1: raise ValueError('Unexpected edge path '+chart['id'])
            tip = re.search(r'(?:^|\s)e,([-\d.]+),([-\d.]+)', e['pos'])
            if not tip: raise ValueError('Missing arrow endpoint')
            labels = []
            for op in e.get('_ldraw_',[]):
                if op['op']=='T': labels.append(dict(x=op['pt'][0],y=op['pt'][1],w=op['width'],text=op['text']))
            edges.append(dict(source=native[e['tail']]['name'], target=native[e['head']]['name'],
                name=f'{chart["id"]} edge {index+1:02}', points=paths[0],
                tip=[float(tip[1]),float(tip[2])], labels=labels, dashed='dashed' in e.get('style','')))
        refs=[]
        for source in chart['sources']:
            path=source['path']
            text=(HERE.parents[1]/path).read_text(encoding='utf-8-sig')
            anchor=text.find(source['anchor'])
            if anchor<0: raise ValueError('Missing reference '+path)
            refs.append(dict(source,line=text[:anchor].count('\n')+1))
        return dict(chart, nodes=nodes, edges=edges, sources=refs, bb=list(map(float,graph['bb'].split(','))))
    build.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=6) as pool: charts=list(pool.map(layout, CHARTS))
    payload=dict(charts=charts, commands=COMMANDS, power=POWER, baseline=BASELINE, date=DATE,
        source_manifest_sha256=hashlib.sha256((HERE/'source_manifest.json').read_bytes()).hexdigest())
    (build/'flowchart-layouts.json').write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    print('Prepared',len(charts),'charts,',sum(len(c['nodes']) for c in charts),'nodes,',sum(len(c['edges']) for c in charts),'edges',flush=True)

def patch(build):
    """Add target arrowheads to editable freeform paths, preserving their routes.

    PowerPoint does not support these custom routes as attached connector
    geometries. Keep each logical edge as one native editable freeform arrow.
    No diagram is flattened to a picture.
    """
    bindings=json.loads((build/'edge-manifest.json').read_text(encoding='utf-8'))
    candidate=build/'candidate.pptx'
    count=0
    with ZipFile(build/'draft.pptx') as source, ZipFile(candidate,'w',ZIP_DEFLATED) as dest:
        for entry in source.infolist():
            data=source.read(entry.filename)
            match=re.fullmatch(r'ppt/slides/slide(\d+)\.xml',entry.filename)
            edges=bindings.get(match[1],[]) if match else []
            if edges:
                root=ET.fromstring(data)
                tree=root.find('p:cSld/p:spTree',NS)
                shapes={s.find('p:nvSpPr/p:cNvPr',NS).get('name'):s for s in tree.findall('p:sp',NS)}
                for edge in edges:
                    line=shapes[edge['name']].find('p:spPr/a:ln',NS)
                    ET.SubElement(line,q('a','tailEnd'),{'type':'triangle','w':'med','len':'med'})
                    count+=1
                data=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            dest.writestr(entry,data)
    print('Editable routed arrows:',count,flush=True)

def verify(build, pptx):
    payload=json.loads((build/'flowchart-layouts.json').read_text(encoding='utf-8'))
    report=dict(slides=[],native_nodes=0,editable_arrows=0,edge_labels=0,embedded_pictures=0,tables=0,verified_table_cells=0)
    table_values={
        35:[['ID','Command','Data','Scope','Behavior'],*payload['commands'][:7]],
        36:[['ID','Command','Data','Scope','Behavior'],*payload['commands'][7:]],
        37:[['Role','Transport','Controller','Active radio','Wake or work source','Behavior'],*payload['power'][:6]],
        38:[['Role','Transport','Controller','Active radio','Wake or work source','Behavior'],*payload['power'][6:]],
    }
    with ZipFile(pptx) as package:
        slides=sorted((p for p in package.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml',p)),key=lambda p:int(re.search(r'(\d+)\.xml',p)[1]))
        assert len(slides)==38, len(slides)
        for number,path in enumerate(slides,1):
            root=ET.fromstring(package.read(path))
            shapes=root.findall('.//p:sp',NS)
            edges=root.findall('.//p:cxnSp',NS)
            pics=root.findall('.//p:pic',NS)
            tables=root.findall('.//a:tbl',NS)
            report['embedded_pictures']+=len(pics);report['tables']+=len(tables)
            if number in table_values:
                actual_rows=tables[0].findall('a:tr',NS)
                assert len(actual_rows)==len(table_values[number])
                for actual_row,expected_row in zip(actual_rows,table_values[number]):
                    actual_cells=actual_row.findall('a:tc',NS)
                    assert len(actual_cells)==len(expected_row)
                    for actual_cell,expected in zip(actual_cells,expected_row):
                        actual=''.join(t.text or '' for t in actual_cell.findall('.//a:t',NS))
                        assert actual==expected,(number,actual,expected)
                        report['verified_table_cells']+=1
            if 5<=number<=34:
                chart=payload['charts'][number-5]
                by_name={s.find('p:nvSpPr/p:cNvPr',NS).get('name'):s for s in shapes}
                for node in chart['nodes']:
                    s=by_name[chart['id']+' node '+node['id']]
                    actual='\n'.join(''.join(t.text or '' for t in p.findall('.//a:t',NS))
                                     for p in s.findall('p:txBody/a:p',NS))
                    assert actual==node['label'], (chart['id'],node['id'],actual,node['label'])
                    report['native_nodes']+=1
                for edge in chart['edges']:
                    arrow=by_name[edge['name']]
                    assert arrow.find('p:spPr/a:custGeom/a:pathLst/a:path',NS) is not None
                    assert arrow.find('p:spPr/a:ln/a:tailEnd',NS).get('type')=='triangle'
                    report['editable_arrows']+=1
                    for index,label in enumerate(edge['labels'],1):
                        shape=by_name[edge['name']+' label '+str(index)]
                        actual=''.join(t.text or '' for t in shape.findall('.//a:t',NS))
                        assert actual==label['text'],(chart['id'],edge['name'],actual,label['text'])
                        report['edge_labels']+=1
                notes=package.read('ppt/notesSlides/notesSlide'+str(number)+'.xml').decode('utf-8')
                for source in chart['sources']: assert source['path'].replace('&','&amp;') in notes
            report['slides'].append(dict(number=number,shapes=len(shapes),connectors=len(edges),pictures=len(pics),tables=len(tables)))
        assert report['embedded_pictures']==0,'Diagram content must stay native'
        assert report['tables']==4
    report['sha256']=hashlib.sha256(pptx.read_bytes()).hexdigest()
    (build/'editability-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='slides'}),flush=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','patch','verify'])
    parser.add_argument('--build',type=Path,default=HERE/'tmp/pptx')
    parser.add_argument('--dot',default='C:/Program Files/Graphviz/bin/dot.exe')
    parser.add_argument('--pptx',type=Path)
    args=parser.parse_args()
    if args.action=='prepare':prepare(args.build,args.dot)
    elif args.action=='patch':patch(args.build)
    else:verify(args.build,args.pptx)
if __name__=='__main__':main()
