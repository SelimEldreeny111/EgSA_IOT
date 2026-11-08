"""Build the operator manual from its reviewed Markdown source.

Run with the bundled Python runtime. Refresh the Word contents and page fields,
then render and inspect the document before publishing a revised edition.
"""

from pathlib import Path
import re

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "WIOT_STM32_Flashing_and_Test_Manual_V1.0.md"
OUTPUT = SOURCE.with_suffix(".docx")
TABLE_WIDTH = 6.8


def field(paragraph, instruction, fallback):
    element = OxmlElement("w:fldSimple")
    element.set(qn("w:instr"), instruction)
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = fallback
    run.append(text)
    element.append(run)
    paragraph._p.append(element)


def cell_text(cell, value, header):
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = 1.05
    run = paragraph.add_run(value)
    run.font.name = "Arial"
    run.font.size = Pt(9.5)
    run.font.bold = header
    run.font.color.rgb = RGBColor.from_string("FFFFFF" if header else "000000")
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def table(document, lines):
    values = [[value.strip() for value in line.strip().strip("|").split("|")]
              for line in lines]
    values = [values[0], *values[2:]]
    count = len(values[0])
    widths = {
        2: [2.0, 4.8],
        3: [1.25, 2.5, 3.05],
        4: [1.0, 1.5, 2.1, 2.2],
    }[count]
    if values[0][0] == "Setting":
        widths = [2.6, 2.1, 2.1]
    if values[0][0] == "Sensor and address":
        widths = [1.2, 2.4, 3.2]
    if values[0][0] == "Reference":
        widths = [1.8, 5.0]
    if values[0][0] == "File":
        widths = [2.5, 4.3]
    if values[0][0] == "Choice":
        widths = [0.65, 2.2, 1.45, 2.5]
    result = document.add_table(rows=0, cols=count)
    result.alignment = WD_TABLE_ALIGNMENT.CENTER
    result.autofit = False
    for column, width in zip(result.columns, widths):
        column.width = Inches(width)
    borders = OxmlElement("w:tblBorders")
    for name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        edge = OxmlElement("w:" + name)
        for key, value in {"val": "single", "sz": "4", "color": "D9D9D9"}.items():
            edge.set(qn("w:" + key), value)
        borders.append(edge)
    result._tbl.tblPr.append(borders)
    margins = OxmlElement("w:tblCellMar")
    for name, size in (("top", 90), ("bottom", 90), ("left", 90), ("right", 90)):
        side = OxmlElement("w:" + name)
        side.set(qn("w:w"), str(size))
        side.set(qn("w:type"), "dxa")
        margins.append(side)
    result._tbl.tblPr.append(margins)
    for number, row_values in enumerate(values):
        if len(row_values) != count:
            raise ValueError("Inconsistent table columns")
        row = result.add_row()
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        if number == 0:
            row._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
        for cell, width, value in zip(row.cells, widths, row_values):
            cell.width = Inches(width)
            cell_text(cell, value, number == 0)
            fill = "173E5B" if number == 0 else ("F1F5F8" if number % 2 == 0 else "FFFFFF")
            shade = OxmlElement("w:shd")
            shade.set(qn("w:fill"), fill)
            cell._tc.get_or_add_tcPr().append(shade)
    document.add_paragraph().paragraph_format.space_after = Pt(2)


def build():
    document = Document()
    section = document.sections[0]
    section.page_width = Inches(8.27)
    section.page_height = Inches(11.69)
    section.left_margin = section.right_margin = Inches(0.73)
    section.top_margin = section.bottom_margin = Inches(0.7)
    section.header_distance = section.footer_distance = Inches(0.3)
    for name in ("Normal", "Title", "Subtitle", "Heading 1", "Heading 2", "Heading 3"):
        style = document.styles[name]
        style.font.name = "Arial"
        style.font.color.rgb = RGBColor(0, 0, 0)
        for border in list(style.element.xpath("./w:pPr/w:pBdr")):
            border.getparent().remove(border)
    normal = document.styles["Normal"]
    normal.font.size = Pt(10.5)
    normal.paragraph_format.line_spacing = 1.08
    normal.paragraph_format.space_after = Pt(7)
    document.styles["Title"].font.size = Pt(27)
    document.styles["Heading 1"].font.size = Pt(16)
    document.styles["Heading 1"].paragraph_format.page_break_before = True
    document.styles["Heading 1"].paragraph_format.space_after = Pt(12)
    document.styles["Heading 2"].font.size = Pt(12)
    for name in ("Heading 1", "Heading 2"):
        document.styles[name].paragraph_format.keep_with_next = True
    header = section.header.paragraphs[0]
    header.add_run("WIOT STM32 operator manual").font.size = Pt(8)
    footer = section.footer.paragraphs[0]
    footer.paragraph_format.tab_stops.add_tab_stop(Inches(TABLE_WIDTH - 1))
    footer.add_run("V1.0   8 November 2026\tPage ").font.size = Pt(8)
    field(footer, "PAGE", "1")
    footer.add_run(" of ").font.size = Pt(8)
    field(footer, "NUMPAGES", "1")

    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    position = 0
    contents_added = False
    while position < len(lines):
        line = lines[position]
        if not line.strip():
            position += 1
            continue
        if line.startswith("# "):
            document.add_paragraph(line[2:], "Title")
        elif line.startswith("## "):
            if not contents_added:
                contents = document.add_paragraph("Contents")
                contents.paragraph_format.page_break_before = True
                contents.paragraph_format.keep_with_next = True
                contents.runs[0].font.size = Pt(16)
                contents.runs[0].font.bold = True
                paragraph = document.add_paragraph()
                field(paragraph, 'TOC \\o "1-1" \\h \\z \\u', "Update contents in Word")
                contents_added = True
            document.add_paragraph(line[3:], "Heading 1")
        elif line.startswith("### "):
            paragraph = document.add_paragraph(line[4:], "Heading 2")
            if line[4:] == "Test record":
                paragraph.paragraph_format.page_break_before = True
        elif line.startswith("```"):
            position += 1
            while position < len(lines) and not lines[position].startswith("```"):
                paragraph = document.add_paragraph()
                paragraph.paragraph_format.space_after = Pt(1)
                paragraph.paragraph_format.line_spacing = 1
                run = paragraph.add_run(lines[position])
                run.font.name = "Consolas"
                run.font.size = Pt(8.5)
                position += 1
            paragraph.paragraph_format.space_after = Pt(9)
        elif line.startswith("|"):
            rows = []
            while position < len(lines) and lines[position].startswith("|"):
                rows.append(lines[position])
                position += 1
            table(document, rows)
            continue
        elif re.match(r"\d+\. ", line):
            paragraph = document.add_paragraph(line)
            paragraph.paragraph_format.left_indent = Inches(0.18)
            paragraph.paragraph_format.first_line_indent = Inches(-0.18)
        else:
            paragraph = document.add_paragraph(line)
            if len(line) < 75 and position + 1 < len(lines) and not lines[position + 1].strip():
                paragraph.paragraph_format.keep_with_next = True
        position += 1
    document.core_properties.title = "WIOT STM32 flashing and test manual"
    document.core_properties.subject = "Configuration, SWD programming and bench acceptance for node and gateway profiles"
    document.core_properties.version = "1.0"
    document.core_properties.author = "EgSA WIOT"
    setting = OxmlElement("w:updateFields")
    setting.set(qn("w:val"), "true")
    document.settings.element.append(setting)
    document.save(OUTPUT)
    print("Built", OUTPUT)


if __name__ == "__main__":
    build()
