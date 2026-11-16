import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.domain.money import Money
from app.models.organisation import Organisation
from app.schemas.financial_statements import (
    BalanceSheetOut,
    IncomeStatementOut,
    StatementLine,
    StatementSection,
)
from app.services.financial_statements import FIXED_ASSETS_WRITTEN_OFF


def _money(minor: int, currency: str) -> str:
    return Money(minor, currency).display()


# The fixed assets block is already a summary (the statement service rolls
# every fixed asset account into one figure at cost and one written off):
# at cost, less accumulated depreciation and amortisation (a contra-asset
# carried with a credit, i.e. negative, balance), then net fixed assets. The
# same rows as the Balance Sheet screen.
def _asset_rows(lines: list[StatementLine]) -> list[tuple[str, int | None, str]]:
    return [
        (
            f"Less: {_label(line)}" if line.account == FIXED_ASSETS_WRITTEN_OFF else _label(line),
            line.balance_minor,
            "line",
        )
        for line in lines
    ]


def _document(buffer: io.BytesIO) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
    )


# A row of a vertical statement: (label, figure or None, kind). Kinds:
# "heading" a section's name, "line" an account, "total" a section's total,
# "result" a figure the statement works out (net current assets, net
# assets), "grand" the line the statement ends on.
_Row = tuple[str, int | None, str]


def _section_rows(section: StatementSection, *, less: bool = False, total_label: str) -> list[_Row]:
    """A section's heading, lines and total; nothing at all for a section
    with nothing in it, as a statement leaves out what it doesn't hold."""
    if not section.lines:
        return []
    rows: list[_Row] = [((f"Less: {section.label}" if less else section.label), None, "heading")]
    if section.category == "non_current_asset":
        rows.extend(_asset_rows(section.lines))
    else:
        rows.extend((_label(line), line.balance_minor, "line") for line in section.lines)
    rows.append((total_label, section.total_minor, "total"))
    return rows


def _label(line: StatementLine) -> str:
    """An account by its name: a statement is read without the account
    numbers, which belong to the chart and the ledger."""
    return line.account_name


def _vertical_table(rows: list[_Row], currency: str) -> Table:
    data = [
        [label, "" if figure is None else _money(figure, currency)] for label, figure, _k in rows
    ]
    style = TableStyle(
        [
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ]
    )
    for index, (_label, _figure, kind) in enumerate(rows):
        if kind == "heading":
            style.add("FONTNAME", (0, index), (-1, index), "Helvetica-Bold")
            style.add("TOPPADDING", (0, index), (-1, index), 8)
        elif kind == "line":
            style.add("LEFTPADDING", (0, index), (0, index), 14)
        elif kind == "total":
            style.add("FONTNAME", (0, index), (-1, index), "Helvetica-Bold")
            style.add("LINEABOVE", (1, index), (1, index), 0.5, colors.grey)
        elif kind == "result":
            style.add("FONTNAME", (0, index), (-1, index), "Helvetica-Bold")
            style.add("LINEABOVE", (0, index), (-1, index), 0.5, colors.black)
        elif kind == "grand":
            style.add("FONTNAME", (0, index), (-1, index), "Helvetica-Bold")
            style.add("LINEABOVE", (0, index), (-1, index), 0.75, colors.black)
            style.add("LINEBELOW", (0, index), (-1, index), 1.5, colors.black)
    table = Table(data, colWidths=[120 * mm, 50 * mm])
    table.setStyle(style)
    return table


def render_balance_sheet_pdf(*, organisation: Organisation, statement: BalanceSheetOut) -> bytes:
    """The vertical form: fixed assets first, then current assets, current
    liabilities, and capital and reserves, which equal net assets."""
    buffer = io.BytesIO()
    doc = _document(buffer)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("StatementTitle", parent=styles["Title"], fontSize=16)
    currency = organisation.currency

    rows: list[_Row] = []
    rows += _section_rows(statement.non_current_assets, total_label="Net fixed assets")
    rows += _section_rows(statement.current_assets, total_label="Total current assets")
    rows += _section_rows(
        statement.current_liabilities, less=True, total_label="Total current liabilities"
    )
    rows.append(("Net current assets", statement.net_current_assets_minor, "result"))
    rows.append(
        (
            "Total assets less current liabilities",
            statement.total_assets_less_current_liabilities_minor,
            "result",
        )
    )
    rows += _section_rows(
        statement.non_current_liabilities,
        less=True,
        total_label="Total long-term liabilities",
    )
    rows.append(("Net assets", statement.net_assets_minor, "grand"))
    rows += _section_rows(statement.capital_and_reserves, total_label="Total capital and reserves")
    rows[-1] = (rows[-1][0], rows[-1][1], "grand")

    story: list[Flowable] = [
        Paragraph(organisation.name, title_style),
        Paragraph("Balance Sheet", styles["Heading2"]),
        Paragraph(
            f"As at {statement.as_of.isoformat()}" if statement.as_of else "All time",
            styles["Normal"],
        ),
        Spacer(1, 4 * mm),
        _vertical_table(rows, currency),
    ]
    if statement.unclassified_accounts:
        story += [
            Spacer(1, 4 * mm),
            Paragraph(
                "Postings to accounts not in the chart of accounts ("
                + ", ".join(statement.unclassified_accounts)
                + ") are shown as one line; add them to the chart to report them in place.",
                styles["Italic"],
            ),
        ]
    if not statement.balanced:
        story.append(
            Paragraph(
                "Net assets and capital and reserves differ: the ledger holds an unbalanced entry.",
                styles["Italic"],
            )
        )

    doc.build(story)
    return buffer.getvalue()


def render_income_statement_pdf(
    *, organisation: Organisation, statement: IncomeStatementOut
) -> bytes:
    buffer = io.BytesIO()
    doc = _document(buffer)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("StatementTitle", parent=styles["Title"], fontSize=16)
    currency = organisation.currency

    period = "All time"
    if statement.from_date and statement.to_date:
        period = f"{statement.from_date.isoformat()} to {statement.to_date.isoformat()}"
    elif statement.from_date:
        period = f"From {statement.from_date.isoformat()}"
    elif statement.to_date:
        period = f"Up to {statement.to_date.isoformat()}"

    rows: list[_Row] = []
    rows += _section_rows(statement.sales, total_label="Total sales")
    rows += _section_rows(statement.cost_of_sales, less=True, total_label="Total cost of sales")
    rows.append(("Gross profit", statement.gross_profit_minor, "result"))
    if statement.other_income.lines:
        rows += _section_rows(statement.other_income, total_label="Total other income")
    rows += _section_rows(statement.overheads, less=True, total_label="Total overheads")
    rows.append(
        (
            "Net profit" if statement.net_income_minor >= 0 else "Net loss",
            statement.net_income_minor,
            "grand",
        )
    )

    story: list[Flowable] = [
        Paragraph(organisation.name, title_style),
        Paragraph("Profit and Loss Account", styles["Heading2"]),
        Paragraph(period, styles["Normal"]),
        Spacer(1, 4 * mm),
        _vertical_table(rows, currency),
    ]

    doc.build(story)
    return buffer.getvalue()
