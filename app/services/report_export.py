"""Shared tabular export writers: CSV, XLSX and PDF from one ReportTable.

Each report is first laid out as a ReportTable (title, metadata lines,
column headings, rows, totals) and then written out, so every format
carries exactly the figures shown on screen. Used by the inventory reports
(app/services/inventory_report_export.py) and analytics
(app/services/analytics/exports.py).

Amounts are written by the caller with money() below: in the currency's
own decimal places (two for NGN or KES, none for RWF or XOF) and without a
currency symbol, because the PDF fonts have no ₦ glyph and spreadsheets
read a bare number. The currency is named in the report's metadata or a
column instead.
"""

import csv
import io
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.domain.money import minor_units_exponent


@dataclass
class ReportTable:
    title: str
    filename: str  # without extension
    headers: list[str]
    rows: list[list[str]]
    subtitle: list[str] = field(default_factory=list)
    totals: list[list[str]] = field(default_factory=list)
    numeric: set[int] = field(default_factory=set)  # right-aligned columns


def money(minor: int | None, currency: str) -> str:
    """Integer minor units of `currency` as a plain number in its own
    decimal places: money(150_000, "NGN") is "1,500.00" and
    money(1_500, "RWF") is "1,500"."""
    if minor is None:
        return ""
    exponent = minor_units_exponent(currency)
    sign = "-" if minor < 0 else ""
    if exponent == 0:
        return f"{sign}{abs(minor):,}"
    whole, fraction = divmod(abs(minor), 10**exponent)
    return f"{sign}{whole:,}.{fraction:0{exponent}d}"


def naira(minor: int | None) -> str:
    return money(minor, "NGN")


def _is_number(text: str) -> bool:
    try:
        Decimal(text.replace(",", ""))
    except InvalidOperation:
        return False
    return True


def _csv_safe(cell: str) -> str:
    """Neutralises a cell a spreadsheet would run as a formula (CSV
    injection): text a user typed, like an item name, starting with = + -
    @ or a control character. Numbers, including negatives, are left as
    they are."""
    if cell and cell[0] in "=+-@\t\r" and not _is_number(cell):
        return "'" + cell
    return cell


# --- writers ----------------------------------------------------------------


def to_csv(table: ReportTable) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([table.title])
    for line in table.subtitle:
        writer.writerow([_csv_safe(line)])
    writer.writerow([])
    writer.writerow(table.headers)
    for row in [*table.rows, *table.totals]:
        writer.writerow([_csv_safe(cell) for cell in row])
    # A byte-order mark so Excel opens the file as UTF-8.
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def to_pdf(table: ReportTable, *, organisation_name: str) -> bytes:
    buffer = io.BytesIO()
    wide = len(table.headers) > 6
    pagesize = landscape(A4) if wide else A4
    doc = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        title=table.title,
    )
    styles = getSampleStyleSheet()
    cell = ParagraphStyle("Cell", parent=styles["Normal"], fontSize=8, leading=10)
    head = ParagraphStyle("Head", parent=cell, fontName="Helvetica-Bold")
    story: list[Flowable] = [
        Paragraph(organisation_name, ParagraphStyle("Org", parent=styles["Title"], fontSize=14)),
        Paragraph(table.title, styles["Heading2"]),
    ]
    story.extend(Paragraph(line, styles["Normal"]) for line in table.subtitle)
    story.append(Spacer(1, 4 * mm))

    def wrap(row: Sequence[str], style: ParagraphStyle) -> list[Paragraph]:
        return [
            Paragraph(
                text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
                ParagraphStyle(
                    f"{style.name}-{index}",
                    parent=style,
                    alignment=2 if index in table.numeric else 0,
                ),
            )
            for index, text in enumerate(row)
        ]

    data = [wrap(table.headers, head)]
    data.extend(wrap(row, cell) for row in table.rows)
    data.extend(wrap(row, head) for row in table.totals)
    if not table.rows:
        data.append(wrap(["Nothing to report."] + [""] * (len(table.headers) - 1), cell))
    width = pagesize[0] - doc.leftMargin - doc.rightMargin
    grid = Table(data, colWidths=[width / len(table.headers)] * len(table.headers), repeatRows=1)
    style: list[Any] = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
    ]
    if table.totals:
        style.append(
            ("LINEABOVE", (0, -len(table.totals)), (-1, -len(table.totals)), 0.6, colors.grey)
        )
    grid.setStyle(TableStyle(style))
    story.append(grid)
    doc.build(story)
    return buffer.getvalue()


# --- XLSX -------------------------------------------------------------------
# A minimal Office Open XML workbook written with the standard library: one
# sheet, inline strings, numbers as numbers. Enough for a report a reader
# opens and filters; no styles, formulas or shared strings, so no
# spreadsheet dependency to install.

_XLSX_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    "</Types>"
)
_XLSX_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="xl/workbook.xml"/>'
    "</Relationships>"
)
_XLSX_WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
    'Target="worksheets/sheet1.xml"/>'
    "</Relationships>"
)


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _xlsx_cell(ref: str, text: str, *, numeric: bool) -> str:
    if numeric and text and _is_number(text):
        return f'<c r="{ref}"><v>{Decimal(text.replace(",", ""))}</v></c>'
    # Strings are inline and never formulas, so a leading "=" stays text.
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def to_xlsx(table: ReportTable) -> bytes:
    lines: list[tuple[list[str], bool]] = [([table.title], False)]
    lines += [([line], False) for line in table.subtitle]
    lines.append(([], False))
    lines.append((table.headers, False))
    lines += [(row, True) for row in [*table.rows, *table.totals]]

    rows_xml = []
    for row_index, (cells, data_row) in enumerate(lines, start=1):
        cells_xml = "".join(
            _xlsx_cell(
                f"{_column_letter(col)}{row_index}",
                text,
                numeric=data_row and col in table.numeric,
            )
            for col, text in enumerate(cells)
        )
        rows_xml.append(f'<row r="{row_index}">{cells_xml}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(rows_xml)}</sheetData></worksheet>"
    )
    sheet_name = escape(table.title[:31].replace("/", "-").replace(":", " "))
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _XLSX_CONTENT_TYPES)
        archive.writestr("_rels/.rels", _XLSX_ROOT_RELS)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", _XLSX_WORKBOOK_RELS)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()
