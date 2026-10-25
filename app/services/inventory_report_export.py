"""CSV, XLSX and PDF exports of the inventory reports (Phase 4, §16). Each
report is first laid out as a ReportTable (title, column headings, rows,
totals); the writers in app/services/report_export.py then write it out,
so every format carries the same figures as the on-screen report.

Amounts are in the organisation's currency, in its own decimal places and
without a symbol (see money() in app/services/report_export.py). Quantities
are in each item's base unit.
"""

from decimal import Decimal

from app.schemas.inventory_control import (
    ExpiryReportOut,
    MovementSummaryOut,
    OutstandingOrdersOut,
    ReorderSuggestionOut,
    StocktakeOut,
    ValuationReportOut,
    VarianceReportOut,
)

# The writers moved to app/services/report_export.py; re-exported (__all__)
# so the inventory API and tests keep their imports.
from app.services.report_export import (
    ReportTable,
    _csv_safe,
    money,
    naira,
    to_csv,
    to_pdf,
    to_xlsx,
)

__all__ = ["ReportTable", "_csv_safe", "money", "naira", "qty", "to_csv", "to_pdf", "to_xlsx"]


def qty(quantity: Decimal | None) -> str:
    if quantity is None:
        return ""
    text = f"{quantity.normalize():f}"
    return "0" if text in ("-0", "0") else text


# --- layouts ----------------------------------------------------------------


def valuation_table(report: ValuationReportOut, *, currency: str) -> ReportTable:
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
            money(r.average_cost_minor, currency),
            money(r.value_minor, currency),
        ]
        rows.append(row)
    blank = [""] * (len(headers) - 1)
    totals = [["Total stock value", *blank[:-1], money(report.total_value_minor, currency)]]
    if report.gl_balance_minor is not None:
        totals.append(
            ["Inventory account (GL)", *blank[:-1], money(report.gl_balance_minor, currency)]
        )
        totals.append(["Difference", *blank[:-1], money(report.difference_minor, currency)])
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


def movement_table(report: MovementSummaryOut, *, with_value: bool, currency: str) -> ReportTable:
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
            row += [money(r.opening_value_minor, currency), money(r.closing_value_minor, currency)]
        rows.append(row)
    totals = []
    if with_value:
        totals.append(
            [
                "Total",
                *[""] * 10,
                money(sum(r.opening_value_minor or 0 for r in report.rows), currency),
                money(sum(r.closing_value_minor or 0 for r in report.rows), currency),
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


def variance_table(report: VarianceReportOut, *, with_value: bool, currency: str) -> ReportTable:
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
            row.append(money(r.value_minor, currency))
        rows.append(row)
    totals = []
    if with_value:
        pad = [""] * (len(headers) - 2)
        totals = [
            ["Gains", *pad, money(report.gain_value_minor, currency)],
            ["Losses", *pad, money(-(report.loss_value_minor or 0), currency)],
            [
                "Net",
                *pad,
                money((report.gain_value_minor or 0) - (report.loss_value_minor or 0), currency),
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


def expiry_table(report: ExpiryReportOut, *, with_value: bool, currency: str) -> ReportTable:
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
            row.append(money(r.value_minor, currency))
        rows.append(row)
    totals = []
    if with_value:
        pad = [""] * (len(headers) - 2)
        totals = [
            ["Expired", *pad, money(report.expired_value_minor, currency)],
            ["Expiring", *pad, money(report.expiring_value_minor, currency)],
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


def outstanding_table(report: OutstandingOrdersOut, *, currency: str) -> ReportTable:
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
            money(r.outstanding_value_minor, currency),
        ]
        for r in report.rows
    ]
    return ReportTable(
        title="Purchase orders outstanding",
        filename="purchase-orders-outstanding",
        headers=headers,
        rows=rows,
        subtitle=["Issued orders not yet fully received, at net price before tax. NGN."],
        totals=[["Total", *[""] * 8, money(report.total_value_minor, currency)]],
        numeric={6, 7, 8, 9},
    )


def reorder_table(
    rows_in: list[ReorderSuggestionOut], *, with_value: bool, currency: str
) -> ReportTable:
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
            row += [
                money(r.last_unit_cost_minor, currency),
                money(r.estimated_cost_minor, currency),
            ]
        rows.append(row)
    totals = []
    if with_value:
        totals = [
            [
                "Total",
                *[""] * (len(headers) - 2),
                money(sum(r.estimated_cost_minor or 0 for r in rows_in), currency),
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


def stocktake_table(stocktake: StocktakeOut, *, with_value: bool, currency: str) -> ReportTable:
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
            row.append(money(line.variance_value_minor, currency))
        rows.append(row)
    totals = []
    if with_value:
        pad = [""] * (len(headers) - 2)
        totals = [
            ["Found", *pad, money(stocktake.gain_value_minor, currency)],
            ["Missing", *pad, money(-(stocktake.loss_value_minor or 0), currency)],
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
