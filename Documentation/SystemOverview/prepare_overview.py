"""Add native arrowheads, validate text fit and verify editable overview content."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from PIL import ImageFont

HERE = Path(__file__).resolve().parent
NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}


def patch():
    data = json.loads((HERE / 'tmp/layout.json').read_text())
    regular = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 22)
    bold = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', 27)
    for ident, x, y, w, h, title, body, kind in data['nodes']:
        assert bold.getlength(title) <= w - 36, (ident, title)
        font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 27) if ident == 'sensors' else regular
        for line in body:
            assert font.getlength(line) <= w - 36, (ident, line)
        assert len(body) * font.size * 1.18 <= h - 61, (ident, 'body height')
        assert 0 <= x < x+w <= data['width'] and 0 <= y < y+h <= data['height']
    manifest = json.loads((HERE / 'tmp/arrows.json').read_text())
    with ZipFile(HERE / 'tmp/draft.pptx') as source, ZipFile(HERE / 'tmp/candidate.pptx', 'w', ZIP_DEFLATED) as target:
        for entry in source.infolist():
            raw = source.read(entry.filename)
            if entry.filename == 'ppt/slides/slide1.xml':
                root = ET.fromstring(raw)
                shapes = {s.find('p:nvSpPr/p:cNvPr', NS).get('name'): s
                          for s in root.findall('p:cSld/p:spTree/p:sp', NS)}
                for edge in manifest:
                    line = shapes[edge['name']].find('p:spPr/a:ln', NS)
                    ET.SubElement(line, '{'+NS['a']+'}tailEnd', {'type': 'triangle', 'w': 'med', 'len': 'med'})
                    if edge['both']:
                        ET.SubElement(line, '{'+NS['a']+'}headEnd', {'type': 'triangle', 'w': 'med', 'len': 'med'})
                raw = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            target.writestr(entry, raw)
    print(f"PASS: text widths/heights; {len(manifest)} native routed arrows")


def verify():
    final = HERE / 'output/WIOT_System_Architecture_Overview_v1.0.pptx'
    data = json.loads((HERE / 'tmp/layout.json').read_text())
    with ZipFile(final) as package:
        root = ET.fromstring(package.read('ppt/slides/slide1.xml'))
        shapes = {s.find('p:nvSpPr/p:cNvPr', NS).get('name'): s
                  for s in root.findall('p:cSld/p:spTree/p:sp', NS)}
        assert not root.findall('.//p:pic', NS), 'Architecture must remain native, not a screenshot'
        for ident, x, y, w, h, title, body, kind in data['nodes']:
            assert 'Block '+ident in shapes
            for name, value in [('Heading '+ident, title), ('Body '+ident, '\n'.join(body))]:
                actual = '\n'.join(''.join(t.text or '' for t in p.findall('.//a:t', NS))
                                   for p in shapes[name].findall('p:txBody/a:p', NS))
                assert actual == value, (name, actual)
        for edge in json.loads((HERE / 'tmp/arrows.json').read_text()):
            s = shapes[edge['name']]
            assert s.find('p:spPr/a:custGeom/a:pathLst/a:path', NS) is not None
            assert s.find('p:spPr/a:ln/a:tailEnd', NS).get('type') == 'triangle'
        assert len(ET.fromstring(package.read('ppt/slides/slide2.xml')).findall('.//p:pic', NS)) == 1
    print(json.dumps(dict(sha256=hashlib.sha256(final.read_bytes()).hexdigest(),
                         editable_blocks=len(data['nodes']), editable_arrows=len(data['arrows']),
                         slides=2, architecture_pictures=0, illustration_pictures=1)))


if __name__ == '__main__':
    {'patch': patch, 'verify': verify}[sys.argv[1]]()
