"""Build the editable WIOT system report from the handover sources."""

from pathlib import Path
import json
import re
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "FlashingAndTesting"))
from build_manual import field, table as add_manual_table

NAME = "WIOT_System_Design_Implementation_and_Test_Report"


def table(doc, rows):
    add_manual_table(doc, rows)
    first = rows[0].strip("| ").split("|")[0].strip()
    widths = {
        "Requirement": (1.65, 4.0, 1.15),
        "Component": (1.38, 2.35, 3.07),
        "Policy": (1.45, 1.65, 3.7),
        "Layer": (1.2, 1.45, 4.15),
    }.get(first)
    if widths:
        result = doc.tables[-1]
        for column, width in zip(result.columns, widths):
            column.width = Inches(width)
        for row in result.rows:
            for cell, width in zip(row.cells, widths):
                cell.width = Inches(width)


def verification(doc):
    results = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    table(doc, [
        "| Layer | Result | Coverage |",
        "| --- | --- | --- |",
        f"| Node host | {results['node_suites']} suites passed | Control, sensor, RTC, storage, radio and power behavior |",
        f"| Python tests | {results['python_total']} tests passed | Server, three simulators and cross-component contract |",
        f"| Dashboard | {results['dashboard_suites']} scripts passed | Display, scoping, commands and history |",
        f"| STM32 builds | {len(results['firmware'])} profiles passed | Flash sections remained below 0x08020000 |",
        "| Bench | Record per deployment | Radio delivery, wake, power, valve and 48-hour soak |",
    ])
    doc.add_paragraph("Software checks ran on 9 November 2026 using the release validation script and the factory valve test fixture. See the handover verification record for build profiles, counts and reproduction steps.")


def build():
    doc = Document()
    section = doc.sections[0]
    section.page_width = Inches(8.27)
    section.page_height = Inches(11.69)
    section.left_margin = section.right_margin = Inches(0.73)
    section.top_margin = section.bottom_margin = Inches(0.67)
    section.header_distance = section.footer_distance = Inches(0.29)
    for name, size in (("Normal", 10.5), ("Title", 27), ("Heading 1", 16), ("Heading 2", 12)):
        style = doc.styles[name]
        style.font.name = "Arial"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(0, 0, 0)
        for border in list(style.element.xpath("./w:pPr/w:pBdr")):
            border.getparent().remove(border)
    normal = doc.styles["Normal"].paragraph_format
    normal.space_after = Pt(7)
    normal.line_spacing = 1.08
    heading = doc.styles["Heading 1"].paragraph_format
    heading.page_break_before = True
    heading.keep_with_next = True
    heading.space_after = Pt(12)
    header = section.header.paragraphs[0]
    header.add_run("EgSA WIOT system report").font.size = Pt(8)
    footer = section.footer.paragraphs[0]
    footer.paragraph_format.tab_stops.add_tab_stop(Inches(5.7))
    footer.add_run("V1.0   9 November 2026\tPage ").font.size = Pt(8)
    field(footer, "PAGE", "1")
    footer.add_run(" of ").font.size = Pt(8)
    field(footer, "NUMPAGES", "1")

    lines = (HERE / f"{NAME}.md").read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("|"):
            rows = []
            while index < len(lines) and lines[index].startswith("|"):
                rows.append(lines[index])
                index += 1
            table(doc, rows)
            continue
        if line.startswith("# "):
            doc.add_paragraph(line[2:], "Title")
        elif line.startswith("## "):
            doc.add_paragraph(line[3:], "Heading 1")
        elif line.startswith("### "):
            doc.add_paragraph(line[4:], "Heading 2")
        elif line.startswith("![System architecture]("):
            asset = HERE.parent / "SystemOverview/output/WIOT_Software_Overview_Simple_v2.1.png"
            doc.add_picture(str(asset), width=Inches(6.8))
            picture = doc.paragraphs[-1]
            picture.alignment = WD_ALIGN_PARAGRAPH.CENTER
            picture.paragraph_format.keep_with_next = True
        elif line == "[Software verification results](VERIFICATION.md)":
            verification(doc)
        elif line:
            p = doc.add_paragraph(line)
            if re.match(r"\d+\. ", line):
                p.paragraph_format.left_indent = Inches(0.19)
                p.paragraph_format.first_line_indent = Inches(-0.19)
            if line.startswith("Figure "):
                p.runs[0].italic = True
                p.runs[0].font.size = Pt(9)
        index += 1
    doc.core_properties.title = "WIOT system design and implementation"
    doc.core_properties.subject = "Project handover for the active STM32 WIOT system"
    doc.core_properties.author = "EgSA WIOT"
    doc.core_properties.version = "1.0"
    target = HERE / f"{NAME}.docx"
    doc.save(target)
    print("Built", target)


if __name__ == "__main__":
    build()
