"""Minimal PDF writer for reports (no third-party dependency).

A4 pages, the standard Helvetica fonts (WinAnsi text: Latin script; Arabic names are transliterated by the
caller or shown as "?"), filled rectangles and lines, simple tables with automatic page breaks. Output is a
valid PDF 1.4 file that opens in every viewer and prints.
"""
from __future__ import annotations

PAGE_W, PAGE_H = 595.28, 841.89
MARGIN = 42

# Helvetica glyph widths (1/1000 em) for ASCII 32..126, from the AFM metrics.
_W = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556,
      556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667,
      556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556,
      556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722,
      500, 500, 500, 334, 260, 334, 584]


def text_width(text: str, size: float, bold: bool = False) -> float:
    w = sum(_W[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in text)
    return w * size / 1000 * (1.06 if bold else 1.0)


def _pdf_text(text: str) -> str:
    out = []
    for c in str(text):
        code = ord(c)
        if c in "\\()":
            out.append("\\" + c)
        elif 32 <= code <= 126:
            out.append(c)
        elif code in (0xB0, 0xB2, 0xB3, 0xB5, 0xB7, 0xD7, 0xE8, 0xE9, 0xFC):
            out.append(f"\\{code:03o}")
        elif c in "–—":
            out.append("-")
        elif c == "…":
            out.append("...")
        else:
            out.append("?")
    return "".join(out)


def _rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return " ".join(f"{int(h[i:i + 2], 16) / 255:.3f}" for i in (0, 2, 4))


class Document:
    def __init__(self, title: str = "WIOT report", accent: str = "#1f5fad"):
        self.title = title
        self.accent = accent
        self.pages: list[list[str]] = []
        self.y = 0.0
        self.footer = ""
        self.new_page()

    # ------------------------------------------------------------ drawing
    @property
    def ops(self) -> list[str]:
        return self.pages[-1]

    def new_page(self) -> None:
        self.pages.append([])
        self.y = PAGE_H - MARGIN

    def text(self, x: float, y: float, text: str, size: float = 10, bold: bool = False, color: str = "#1d2433") -> None:
        font = "F2" if bold else "F1"
        self.ops.append(f"BT {_rgb(color)} rg /{font} {size} Tf {x:.2f} {y:.2f} Td ({_pdf_text(text)}) Tj ET")

    def rect(self, x: float, y: float, w: float, h: float, fill: str) -> None:
        self.ops.append(f"{_rgb(fill)} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")

    def line(self, x1: float, y1: float, x2: float, y2: float, color: str = "#d3dae5", width: float = 0.6) -> None:
        self.ops.append(f"{_rgb(color)} RG {width} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def ensure(self, height: float) -> None:
        if self.y - height < MARGIN + 20:
            self.new_page()

    # ------------------------------------------------------------- blocks
    def heading(self, text: str, size: float = 16) -> None:
        self.ensure(size + 14)
        self.y -= size
        self.text(MARGIN, self.y, text, size, bold=True)
        self.y -= 10

    def paragraph(self, text: str, size: float = 9.5, color: str = "#4a5568") -> None:
        width = PAGE_W - 2 * MARGIN
        for raw in str(text).split("\n"):
            line = ""
            for word in raw.split(" "):
                trial = (line + " " + word).strip()
                if text_width(trial, size) > width and line:
                    self.ensure(size + 4)
                    self.y -= size + 3
                    self.text(MARGIN, self.y, line, size, color=color)
                    line = word
                else:
                    line = trial
            self.ensure(size + 4)
            self.y -= size + 3
            self.text(MARGIN, self.y, line, size, color=color)
        self.y -= 6

    def kpis(self, items: list[tuple[str, str]]) -> None:
        n = max(1, len(items))
        gap = 8
        w = (PAGE_W - 2 * MARGIN - gap * (n - 1)) / n
        self.ensure(56)
        top = self.y
        for i, (label, value) in enumerate(items):
            x = MARGIN + i * (w + gap)
            self.rect(x, top - 50, w, 50, "#f1f4f9")
            self.rect(x, top - 50, 3, 50, self.accent)
            self.text(x + 10, top - 18, label, 8, color="#6b778a")
            self.text(x + 10, top - 38, value, 14, bold=True)
        self.y = top - 62

    def table(self, header: list[str], rows: list[list], widths: list[float] | None = None,
              align: list[str] | None = None, size: float = 8.5) -> None:
        total = PAGE_W - 2 * MARGIN
        widths = widths or [1] * len(header)
        scale = total / sum(widths)
        cols = [w * scale for w in widths]
        align = align or ["l"] + ["r"] * (len(header) - 1)
        row_h = size + 8

        def draw_header():
            self.ensure(row_h * 2)
            self.rect(MARGIN, self.y - row_h, total, row_h, self.accent)
            x = MARGIN
            for c, h in enumerate(header):
                self._cell(x, cols[c], self.y - row_h + 5, h, size, True, align[c], "#ffffff")
                x += cols[c]
            self.y -= row_h

        draw_header()
        for i, row in enumerate(rows):
            if self.y - row_h < MARGIN + 20:
                self.new_page()
                draw_header()
            if i % 2:
                self.rect(MARGIN, self.y - row_h, total, row_h, "#f6f8fb")
            x = MARGIN
            for c, v in enumerate(row):
                self._cell(x, cols[c], self.y - row_h + 5, "" if v is None else str(v), size, False, align[c])
                x += cols[c]
            self.y -= row_h
        self.line(MARGIN, self.y, MARGIN + total, self.y)
        self.y -= 12

    def _cell(self, x, w, y, text, size, bold, al, color="#1d2433"):
        while text and text_width(text, size, bold) > w - 8:
            text = text[:-2] + "…" if len(text) > 2 else text[:-1]
        tx = x + 4 if al == "l" else x + w - 4 - text_width(text, size, bold)
        self.text(tx, y, text, size, bold, color)

    # ------------------------------------------------------------- output
    def to_bytes(self) -> bytes:
        objs: list[bytes] = []
        n_pages = len(self.pages)
        # 1 catalog, 2 pages, 3 font regular, 4 font bold, then (page, content) pairs
        page_ids = [5 + 2 * i for i in range(n_pages)]
        objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objs.append(f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {n_pages} >>".encode())
        objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        for i, ops in enumerate(self.pages):
            footer = (f"BT 0.42 0.47 0.54 rg /F1 7.5 Tf {MARGIN} 22 Td ({_pdf_text(self.footer)}) Tj ET "
                      f"BT 0.42 0.47 0.54 rg /F1 7.5 Tf {PAGE_W - MARGIN - 40:.2f} 22 Td (Page {i + 1} / {n_pages}) Tj ET")
            stream = ("\n".join(ops) + "\n" + footer).encode("latin-1")
            objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                        f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {page_ids[i] + 1} 0 R >>".encode())
            objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for num, body in enumerate(objs, start=1):
            offsets.append(len(out))
            out += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
        info = f"<< /Title ({_pdf_text(self.title)}) /Producer (WIOT Platform) >>"
        out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {info} >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)
