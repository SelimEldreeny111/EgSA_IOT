"""Build the printable reference from its editable Markdown source.

Requirements: reportlab. Sections separated by --- start on a new PDF page.
Table cells wrap; page header/footer includes the document revision.
"""
import argparse
import html
from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, PageBreak,
                               Table, TableStyle, Preformatted)

INK = colors.HexColor('#16364B')
TEAL = colors.HexColor('#087F8C')
MUTED = colors.HexColor('#526674')
PALE = colors.HexColor('#F0F5F7')
WIDTH = A4[0] - 36 * mm


def inline(value):
    value = html.escape(value)
    value = re.sub(r'`([^`]+)`', r'<font name="Courier">\1</font>', value)
    return re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).with_name('WIOT_Power_Modes_Reference.md'))
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'output' / 'pdf' / 'WIOT_Power_Modes_Reference.pdf')
    args = parser.parse_args()
    lines = args.source.read_text(encoding='utf-8').splitlines()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='BodyRef', fontName='Helvetica', fontSize=9.1,
                              leading=12.6, textColor=INK, spaceAfter=6))
    styles.add(ParagraphStyle(name='BulletRef', parent=styles['BodyRef'],
                              leftIndent=12, bulletIndent=0))
    styles.add(ParagraphStyle(name='TitleRef', fontName='Helvetica-Bold', fontSize=24,
                              leading=29, textColor=INK, spaceAfter=12))
    styles.add(ParagraphStyle(name='SectionRef', fontName='Helvetica-Bold', fontSize=18,
                              leading=22, textColor=TEAL, spaceBefore=6, spaceAfter=12))
    styles.add(ParagraphStyle(name='SubRef', fontName='Helvetica-Bold', fontSize=11.2,
                              leading=15, textColor=INK, spaceBefore=9, spaceAfter=6))
    styles.add(ParagraphStyle(name='CellRef', fontName='Helvetica', fontSize=8.1,
                              leading=10.8, textColor=INK))
    styles.add(ParagraphStyle(name='HeadRef', fontName='Helvetica-Bold', fontSize=8.2,
                              leading=10.9, textColor=colors.white))
    styles.add(ParagraphStyle(name='CodeRef', fontName='Courier', fontSize=7.9,
                              leading=11.1, textColor=INK, backColor=PALE,
                              borderPadding=8, spaceBefore=4, spaceAfter=9))
    story = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line == '---':
            story.append(PageBreak())
            i += 1
        elif line.startswith('```'):
            i += 1
            code = []
            while i < len(lines) and not lines[i].startswith('```'):
                code.append(lines[i])
                i += 1
            story.append(Preformatted('\n'.join(code), styles['CodeRef']))
            i += 1
        elif line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = [cell.strip() for cell in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r'[-: ]+', cell) for cell in cells):
                    rows.append(cells)
                i += 1
            n = len(rows[0])
            if n == 9:
                weights = [1.8, .65, .55, 1.35, .65, .4, .4, .4, .6]
            elif n == 5:
                weights = [1.5, 1.55, 1.25, 1.9, 1.1]
            elif n == 4 and rows[0][0] == 'Macro':
                weights = [2.7, .9, 1.15, 2.35]
            elif n == 4:
                weights = [1.6, 1.25, 1.4, 1.6]
            elif n == 3 and rows[0][0] == 'Test':
                weights = [1.2, 1.8, 3.0]
            elif n == 3 and rows[0][0] == 'Function':
                weights = [1.45, 1.25, 3.1]
            elif n == 3:
                weights = [2, 1.2, 1.2]
            else:
                weights = [2] + [1] * (n - 1)
            widths = [WIDTH * v / sum(weights) for v in weights]
            cells = [[Paragraph(inline(cell).replace('APP_LORA_WOR_WATCHDOG_WAKE_SECONDS',
                                  'APP_LORA_WOR_<br/>WATCHDOG_WAKE_SECONDS'),
                                  styles['HeadRef' if r == 0 else 'CellRef'])
                      for cell in row] for r, row in enumerate(rows)]
            table = Table(cells, colWidths=widths, repeatRows=1, hAlign='LEFT')
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), INK),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, PALE]),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LINEBELOW', (0, 0), (-1, 0), .6, TEAL),
                ('LINEBELOW', (0, -1), (-1, -1), .5, colors.HexColor('#CCD9E0')),
            ]))
            story.extend([table, Spacer(1, 7)])
        elif line.startswith('# '):
            story.append(Paragraph(inline(line[2:]), styles['TitleRef']))
            i += 1
        elif line.startswith('## '):
            story.append(Paragraph(inline(line[3:]), styles['SectionRef']))
            i += 1
        elif line.startswith('### '):
            story.append(Paragraph(inline(line[4:]), styles['SubRef']))
            i += 1
        elif line.startswith('- ') or re.match(r'^\d+\. ', line):
            label = '-' if line.startswith('- ') else line.split(' ', 1)[0]
            content = line[2:] if label == '-' else line.split(' ', 1)[1]
            story.append(Paragraph(inline(content), styles['BulletRef'], bulletText=label))
            i += 1
        else:
            text = [line]
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].startswith(('#', '|', '```', '- ')):
                text.append(lines[i].strip())
                i += 1
            story.append(Paragraph(inline(' '.join(text)), styles['BodyRef']))

    def chrome(canvas, doc):
        canvas.saveState()
        canvas.setTitle('WIOT Power Modes and Supported Combinations')
        canvas.setAuthor('WIOT Software Engineering')
        canvas.setStrokeColor(TEAL)
        canvas.setLineWidth(1)
        canvas.line(18 * mm, A4[1] - 17 * mm, A4[0] - 18 * mm, A4[1] - 17 * mm)
        canvas.setFont('Helvetica-Bold', 8)
        canvas.setFillColor(INK)
        canvas.drawString(18 * mm, A4[1] - 13 * mm, 'WIOT / ENGINEERING REFERENCE')
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(A4[0] - 18 * mm, A4[1] - 13 * mm, 'STM32F401 | v1.0 | 04 OCT 2026')
        canvas.setStrokeColor(colors.HexColor('#CCD9E0'))
        canvas.setLineWidth(.4)
        canvas.line(18 * mm, 17 * mm, A4[0] - 18 * mm, 17 * mm)
        canvas.setFont('Helvetica', 7.6)
        canvas.drawString(18 * mm, 12 * mm, 'Implemented modes | Firmware baseline 48e5e4b | Hardware tests required')
        canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f'{doc.page}')
        canvas.restoreState()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(args.output), pagesize=A4, leftMargin=18 * mm,
                            rightMargin=18 * mm, topMargin=23 * mm, bottomMargin=23 * mm,
                            title='WIOT Power Modes and Supported Combinations', author='WIOT Software Engineering')
    doc.build(story, onFirstPage=chrome, onLaterPages=chrome)
    print(f'Created {args.output}')


if __name__ == '__main__':
    main()
