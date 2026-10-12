"""CSV and PDF exports of the inventory reports (Phase 4, §16). Each report
is first laid out as a ReportTable (title, column headings, rows, totals),
then written out in either format, so both formats always carry the same
figures as the on-screen report.

Amounts are naira (two decimal places, no currency symbol: the PDF fonts
have no ₦ glyph and spreadsheets read a bare number). Quantities are in
each item's base unit.
"""

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.schemas.inventory_control import (
    ExpiryReportOut,
    MovementSummaryOut,
    OutstandingOrdersOut,
    ReorderSuggestionOut,
    StocktakeOut,
    ValuationReportOut,
    VarianceReportOut,
)


@dataclass
class ReportTable:
    title: str
    filename: str  # without extension
    headers: list[str]
    rows: list[list[str]]
    subtitle: list[str] = field(default_factory=list)
    totals: list[list[str]] = field(default_factory=list)
    numeric: set[int] = field(default_factory=set)  # right-aligned columns


def naira(minor: int | None) -> str:
    if minor is None:
        return ""
    sign = "-" if minor < 0 else ""
    whole, kobo = divmod(abs(minor), 100)
    return f"{sign}{whole:,}.{kobo:02d}"


def qty(quantity: Decimal | None) -> str:
    if quantity is None:
        return ""
    text = f"{quantity.normalize():f}"
    return "0" if text in ("-0", "0") else text


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


# --- layouts ----------------------------------------------------------------


def valuation_table(report: ValuationReportOut) -> ReportTable:
    by_wh = report.by_warehouse
    headers = ["SKU", "Item", "Category"]
    if by_wh:
        headers.append("Warehouse")
    headers += ["Unit", "Quantity", "Average cost", "Value"]
    rows = []
    for r in report.rows:
        row = [r.sku, r.item_name, r.category_name or ""]
        if by_wh:
            row.append(r.warehouse_code or "")
        row += [
            r.base_unit_code,
            qty(r.quantity),
            naira(r.average_cost_minor),
            naira(r.value_minor),
        ]
        rows.append(row)
    blank = [""] * (len(headers) - 1)
    totals = [["Total stock value", *blank[:-1], naira(report.total_value_minor)]]
    if report.gl_balance_minor is not None:
        totals.append(["Inventory account (GL)", *blank[:-1], naira(report.gl_balance_minor)])
        totals.append(["Difference", *blank[:-1], naira(report.difference_minor)])
    subtitle = [f"As at the end of {report.as_of.isoformat()}. Amounts in NGN."]
    if report.posts_to_gl and report.gl_balance_minor is None:
        subtitle.append("No GL comparison: filtered, or before inventory accounting started.")
    first = len(headers) - 3
    return ReportTable(
        title="Stock valuation",
        filename=f"stock-valuation-{report.as_of.isoformat()}",
        headers=headers,
        rows=rows,
        subtitle=subtitle,
        totals=totals,
        numeric={first, first + 1, first + 2},
    )


def movement_table(report: MovementSummaryOut, *, with_value: bool) -> ReportTable:
    headers = [
        "SKU",
        "Item",
        "Unit",
        "Opening",
        "Received",
        "Issued",
        "Transfers in",
        "Transfers out",
        "Adjusted",
        "Reversed",
        "Closing",
    ]
    if with_value:
        headers += ["Opening value", "Closing value"]
    rows = []
    for r in report.rows:
        row = [
            r.sku,
            r.item_name,
            r.base_unit_code,
            *(
                qty(v)
                for v in (
                    r.opening_quantity,
                    r.received,
                    r.issued,
                    r.transferred_in,
                    r.transferred_out,
                    r.adjusted,
                    r.reversed,
                    r.closing_quantity,
                )
            ),
        ]
        if with_value:
            row += [naira(r.opening_value_minor), naira(r.closing_value_minor)]
        rows.append(row)
    totals = []
    if with_value:
        totals.append(
            [
                "Total",
                *[""] * 10,
                naira(sum(r.opening_value_minor or 0 for r in report.rows)),
                naira(sum(r.closing_value_minor or 0 for r in report.rows)),
            ]
        )
    return ReportTable(
        title="Stock movement summary",
        filename=f"stock-movements-{report.date_from.isoformat()}-{report.date_to.isoformat()}",
        headers=headers,
        rows=rows,
        subtitle=[
            (
                f"{report.date_from.isoformat()} to {report.date_to.isoformat()}. "
                "Stock out is negative; closing = opening + the movements."
            )
        ],
        totals=totals,
        numeric=set(range(3, len(headers))),
    )


def variance_table(report: VarianceReportOut, *, with_value: bool) -> ReportTable:
    headers = ["Date", "Document", "Reason", "SKU", "Item", "Warehouse", "Lot", "Quantity"]
    if with_value:
        headers.append("Value")
    rows = []
    for r in report.rows:
        row = [
            r.entry_date.isoformat(),
            r.source_number or "",
            r.reason or r.movement_type.value.replace("_", " "),
            r.sku,
            r.item_name,
            r.warehouse_code,
            r.lot_number or "",
            f"{qty(r.quantity)} {r.base_unit_code}",
        ]
        if with_value:
            row.append(naira(r.value_minor))
        rows.append(row)
    totals = []
    if with_value:
        pad = [""] * (len(headers) - 2)
        totals = [
            ["Gains", *pad, naira(report.gain_value_minor)],
            ["Losses", *pad, naira(-(report.loss_value_minor or 0))],
            [
                "Net",
                *pad,
                naira((report.gain_value_minor or 0) - (report.loss_value_minor or 0)),
            ],
        ]
    return ReportTable(
        title="Adjustments and stocktake variances",
        filename=f"stock-variances-{report.date_from.isoformat()}-{report.date_to.isoformat()}",
        headers=headers,
        rows=rows,
        subtitle=[f"{report.date_from.isoformat()} to {report.date_to.isoformat()}."],
        totals=totals,
        numeric={7, 8} if with_value else {7},
    )


def expiry_table(report: ExpiryReportOut, *, with_value: bool) -> ReportTable:
    headers = ["Expiry", "Days", "SKU", "Item", "Lot", "Warehouse", "Quantity"]
    if with_value:
        headers.append("Value")
    rows = []
    for r in report.rows:
        row = [
            r.expiry_date.isoformat() if r.expiry_date else "",
            "expired" if r.expired else str(r.days_to_expiry),
            r.sku,
            r.item_name,
            r.lot_number,
            r.warehouse_code,
            f"{qty(r.quantity)} {r.base_unit_code}",
        ]
        if with_value:
            row.append(naira(r.value_minor))
        rows.append(row)
    totals = []
    if with_value:
        pad = [""] * (len(headers) - 2)
        totals = [
            ["Expired", *pad, naira(report.expired_value_minor)],
            ["Expiring", *pad, naira(report.expiring_value_minor)],
        ]
    return ReportTable(
        title="Expiring stock",
        filename=f"expiring-stock-{report.as_of.isoformat()}",
        headers=headers,
        rows=rows,
        subtitle=[
            (
                f"Lots expired or expiring within {report.within_days} days of "
                f"{report.as_of.isoformat()}."
            )
        ],
        totals=totals,
        numeric={1, 6, 7} if with_value else {1, 6},
    )


def outstanding_table(report: OutstandingOrdersOut) -> ReportTable:
    headers = [
        "Order",
        "Vendor",
        "Ordered on",
        "Expected",
        "SKU",
        "Item",
        "Ordered",
        "Received",
        "Outstanding",
        "Value",
    ]
    rows = [
        [
            r.po_number,
            r.vendor_name,
            r.order_date.isoformat(),
            r.expected_date.isoformat() if r.expected_date else "",
            r.sku,
            r.item_name,
            qty(r.ordered),
            qty(r.received),
            f"{qty(r.outstanding)} {r.base_unit_code}",
            naira(r.outstanding_value_minor),
        ]
        for r in report.rows
    ]
    return ReportTable(
        title="Purchase orders outstanding",
        filename="purchase-orders-outstanding",
        headers=headers,
        rows=rows,
        subtitle=["Issued orders not yet fully received, at net price before tax. NGN."],
        totals=[["Total", *[""] * 8, naira(report.total_value_minor)]],
        numeric={6, 7, 8, 9},
    )


def reorder_table(rows_in: list[ReorderSuggestionOut], *, with_value: bool) -> ReportTable:
    headers = [
        "SKU",
        "Item",
        "Vendor",
        "Reorder level",
        "On hand",
        "Expired",
        "On order",
        "Suggested",
    ]
    if with_value:
        headers += ["Unit cost", "Estimated cost"]
    rows = []
    for r in rows_in:
        row = [
            r.sku,
            r.item_name,
            r.preferred_vendor_name or "",
            qty(r.reorder_level),
            qty(r.on_hand),
            qty(r.expired),
            qty(r.on_order),
            f"{qty(r.suggested_quantity)} {r.base_unit_code}",
        ]
        if with_value:
            row += [naira(r.last_unit_cost_minor), naira(r.estimated_cost_minor)]
        rows.append(row)
    totals = []
    if with_value:
        totals = [
            [
                "Total",
                *[""] * (len(headers) - 2),
                naira(sum(r.estimated_cost_minor or 0 for r in rows_in)),
            ]
        ]
    return ReportTable(
        title="Reorder suggestions",
        filename="reorder-suggestions",
        headers=headers,
        rows=rows,
        subtitle=["Items at or below their reorder level, counting what's on order."],
        totals=totals,
        numeric=set(range(3, len(headers))),
    )


def stocktake_table(stocktake: StocktakeOut, *, with_value: bool) -> ReportTable:
    """The count sheet (before counting) or the variance sheet (after)."""
    headers = ["#", "SKU", "Item", "Lot", "Expiry", "Unit", "Expected", "Counted", "Variance"]
    if with_value:
        headers.append("Value")
    rows = []
    for line in stocktake.lines or []:
        row = [
            str(line.line_no),
            line.sku,
            line.item_name,
            line.lot_number or "",
            line.expiry_date.isoformat() if line.expiry_date else "",
            line.base_unit_code,
            qty(line.expected_quantity),
            qty(line.counted_quantity),
            qty(line.variance),
        ]
        if with_value:
            row.append(naira(line.variance_value_minor))
        rows.append(row)
    totals = []
    if with_value:
        pad = [""] * (len(headers) - 2)
        totals = [
            ["Found", *pad, naira(stocktake.gain_value_minor)],
            ["Missing", *pad, naira(-(stocktake.loss_value_minor or 0))],
        ]
    cutoff = (
        stocktake.cutoff_at.isoformat(timespec="minutes") if stocktake.cutoff_at else "not started"
    )
    scope = f", {stocktake.category_name} only" if stocktake.category_name else ""
    return ReportTable(
        title=f"Stocktake {stocktake.stocktake_number}",
        filename=f"stocktake-{stocktake.stocktake_number}",
        headers=headers,
        rows=rows,
        subtitle=[
            (
                f"{stocktake.warehouse_code} ({stocktake.warehouse_name}){scope}. "
                f"Count date {stocktake.count_date.isoformat()}; cutoff {cutoff}; "
                f"status {stocktake.status.value.replace('_', ' ')}."
            )
        ],
        totals=totals,
        numeric={0, 6, 7, 8, 9} if with_value else {0, 6, 7, 8},
    )
