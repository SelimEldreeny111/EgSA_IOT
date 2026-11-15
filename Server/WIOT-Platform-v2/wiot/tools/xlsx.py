"""Minimal Office Open XML spreadsheet writer (no third-party dependency).

Enough for reports: several sheets, a bold header row with a fill, numbers and text (inline strings, so no
shared-string table), column widths, a frozen header and an auto-filter. Opens in Excel, LibreOffice,
Google Sheets and Power BI.
"""
from __future__ import annotations

import io
import math
import zipfile
from xml.sax.saxutils import escape

_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
{sheets}</Types>"""
_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/></numFmts>
<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font><font><b/><sz val="14"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F5FAD"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>
</styleSheet>"""


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, value, style: int | None = None) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return ""
    if isinstance(value, bool):
        value = "yes" if value else "no"
    if isinstance(value, (int, float)):
        st = style if style is not None else (4 if isinstance(value, int) else 2)
        return f'<c r="{ref}" s="{st}"><v>{value}</v></c>'
    text = escape(str(value)).replace("\n", "&#10;")
    st = f' s="{style}"' if style else ""
    return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{text}</t></is></c>'


class Sheet:
    def __init__(self, name: str):
        self.name = name[:31]
        self.rows: list[tuple[list, int | None]] = []
        self.widths: dict[int, float] = {}
        self.header_row: int | None = None

    def title(self, text: str) -> "Sheet":
        self.rows.append(([text], 3))
        return self

    def blank(self) -> "Sheet":
        self.rows.append(([], None))
        return self

    def header(self, cols: list[str]) -> "Sheet":
        self.header_row = len(self.rows)
        self.rows.append((cols, 1))
        for i, c in enumerate(cols):
            self.widths[i] = max(self.widths.get(i, 8), min(45, len(str(c)) + 3))
        return self

    def row(self, values: list) -> "Sheet":
        self.rows.append((values, None))
        for i, v in enumerate(values):
            self.widths[i] = max(self.widths.get(i, 8), min(45, len(str(v if v is not None else "")) + 2))
        return self

    def xml(self) -> str:
        cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w:.1f}" customWidth="1"/>'
                       for i, w in sorted(self.widths.items()))
        body = []
        for r, (values, style) in enumerate(self.rows, start=1):
            cells = "".join(_cell(f"{_col(c)}{r}", v, style) for c, v in enumerate(values))
            body.append(f'<row r="{r}">{cells}</row>')
        pane = ""
        if self.header_row is not None:
            top = self.header_row + 2
            pane = (f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{top - 1}" topLeftCell="A{top}" '
                    'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>')
        flt = ""
        if self.header_row is not None and len(self.rows) > self.header_row + 1:
            ncols = len(self.rows[self.header_row][0])
            flt = f'<autoFilter ref="A{self.header_row + 1}:{_col(ncols - 1)}{len(self.rows)}"/>'
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'{pane}{"<cols>" + cols + "</cols>" if cols else ""}<sheetData>{"".join(body)}</sheetData>{flt}</worksheet>')


class Workbook:
    def __init__(self, title: str = "WIOT report"):
        self.title = title
        self.sheets: list[Sheet] = []

    def sheet(self, name: str) -> Sheet:
        s = Sheet(name)
        self.sheets.append(s)
        return s

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            overrides = "".join(
                f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for i in range(1, len(self.sheets) + 1))
            z.writestr("[Content_Types].xml", _CT.format(sheets=overrides))
            z.writestr("_rels/.rels", _RELS)
            z.writestr("docProps/core.xml",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties '
                       'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                       'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>'
                       f'{escape(self.title)}</dc:title><dc:creator>WIOT Platform</dc:creator></cp:coreProperties>')
            z.writestr("xl/styles.xml", _STYLES)
            sheets = "".join(f'<sheet name="{escape(s.name)}" sheetId="{i}" r:id="rId{i}"/>'
                             for i, s in enumerate(self.sheets, start=1))
            z.writestr("xl/workbook.xml",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook '
                       'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                       f'<sheets>{sheets}</sheets></workbook>')
            rels = "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                           f'relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                           for i in range(1, len(self.sheets) + 1))
            n = len(self.sheets) + 1
            rels += (f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                     'relationships/styles" Target="styles.xml"/>')
            z.writestr("xl/_rels/workbook.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships '
                       f'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
            for i, s in enumerate(self.sheets, start=1):
                z.writestr(f"xl/worksheets/sheet{i}.xml", s.xml())
        return buf.getvalue()
