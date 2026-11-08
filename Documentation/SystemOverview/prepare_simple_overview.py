"""Verify editable audience overview and add arrowheads without flattening it."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from PIL import ImageFont

HERE = Path(__file__).resolve().parent
TMP = HERE / 'tmp/simple'
NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}


def patch():
    data = json.loads((TMP / 'manifest.json').read_text())
    for t in data['texts']:
        face = 'arialbd.ttf' if t['bold'] else 'arial.ttf'
        font = ImageFont.truetype('C:/Windows/Fonts/'+face, t['size'])
        for line in t['value'].split('\n'):
            assert font.getlength(line) <= t['w'], (t['name'], line)
        assert len(t['value'].split('\n')) * t['size'] * 1.22 <= t['h'], (t['name'], 'height')
        assert 0 <= t['x'] < t['x']+t['w'] <= data['width']
        assert 0 <= t['y'] < t['y']+t['h'] <= data['height']
    with ZipFile(TMP / 'draft.pptx') as source, ZipFile(TMP / 'candidate.pptx', 'w', ZIP_DEFLATED) as target:
        for entry in source.infolist():
            raw = source.read(entry.filename)
            if entry.filename == 'ppt/slides/slide1.xml':
                root = ET.fromstring(raw)
                shapes = {s.find('p:nvSpPr/p:cNvPr', NS).get('name'): s
                          for s in root.findall('p:cSld/p:spTree/p:sp', NS)}
                for name in data['arrows']:
                    line = shapes[name].find('p:spPr/a:ln', NS)
                    ET.SubElement(line, '{'+NS['a']+'}tailEnd', {'type': 'triangle', 'w': 'lg', 'len': 'lg'})
                raw = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            target.writestr(entry, raw)
    print('PASS: text fit and five native flow arrows')


def verify():
    final = HERE / 'output/WIOT_Software_Overview_Simple_v2.1.pptx'
    data = json.loads((TMP / 'manifest.json').read_text())
    assert (data['stages'], data['services'], len(data['arrows'])) == (5, 4, 5)
    with ZipFile(final) as package:
        root = ET.fromstring(package.read('ppt/slides/slide1.xml'))
        shapes = {s.find('p:nvSpPr/p:cNvPr', NS).get('name'): s
                  for s in root.findall('p:cSld/p:spTree/p:sp', NS)}
        assert not root.findall('.//p:pic', NS), 'Overview must remain native'
        for t in data['texts']:
            actual = '\n'.join(''.join(v.text or '' for v in paragraph.findall('.//a:t', NS))
                               for paragraph in shapes[t['name']].findall('p:txBody/a:p', NS))
            assert actual == t['value'], t['name']
        for name in data['blocks']:
            assert name in shapes, name
        for name in data['arrows']:
            assert shapes[name].find('p:spPr/a:custGeom/a:pathLst/a:path', NS) is not None
            assert shapes[name].find('p:spPr/a:ln/a:tailEnd', NS).get('type') == 'triangle'
        assert len(ET.fromstring(package.read('ppt/slides/slide2.xml')).findall('.//p:pic', NS)) == 1
    ET.parse(HERE / 'output/WIOT_Software_Overview_Simple_v2.1.svg')
    print(json.dumps({'sha256': hashlib.sha256(final.read_bytes()).hexdigest(),
                      'stages': 5, 'support_services': 4, 'arrows': 5, 'native_texts': len(data['texts'])}))


if __name__ == '__main__':
    {'patch': patch, 'verify': verify}[sys.argv[1]]()
