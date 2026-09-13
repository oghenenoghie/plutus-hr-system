import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.domain.money import Money
from app.models.organisation import Organisation
from app.schemas.financial_statements import BalanceSheetOut, IncomeStatementOut, StatementLine


def _money(minor: int) -> str:
    return Money(minor).display()


def _section_table(lines: list[StatementLine], total_label: str, total_minor: int) -> Table:
    rows = [["Account", "Balance"]]
    rows.extend([line.account_name, _money(line.balance_minor)] for line in lines)
    rows.append([total_label, _money(total_minor)])
    table = Table(rows, colWidths=[120 * mm, 40 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
                ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ]
        )
    )
    return table


def render_balance_sheet_pdf(*, organisation: Organisation, statement: BalanceSheetOut) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("StatementTitle", parent=styles["Title"], fontSize=16)

    story: list[Flowable] = [
        Paragraph(organisation.name, title_style),
        Paragraph("Balance Sheet", styles["Heading2"]),
        Paragraph(
            f"As of {statement.as_of.isoformat()}" if statement.as_of else "All time",
            styles["Normal"],
        ),
        Spacer(1, 6 * mm),
        Paragraph("Assets", styles["Heading3"]),
        _section_table(statement.assets, "Total assets", statement.total_assets_minor),
        Spacer(1, 6 * mm),
        Paragraph("Liabilities", styles["Heading3"]),
        _section_table(
            statement.liabilities, "Total liabilities", statement.total_liabilities_minor
        ),
        Spacer(1, 6 * mm),
        Paragraph("Equity", styles["Heading3"]),
        _section_table(statement.equity, "Total equity", statement.total_equity_minor),
    ]

    doc.build(story)
    return buffer.getvalue()


def render_income_statement_pdf(
    *, organisation: Organisation, statement: IncomeStatementOut
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("StatementTitle", parent=styles["Title"], fontSize=16)

    period = "All time"
    if statement.from_date and statement.to_date:
        period = f"{statement.from_date.isoformat()} to {statement.to_date.isoformat()}"
    elif statement.from_date:
        period = f"From {statement.from_date.isoformat()}"
    elif statement.to_date:
        period = f"Up to {statement.to_date.isoformat()}"

    story: list[Flowable] = [
        Paragraph(organisation.name, title_style),
        Paragraph("Income Statement", styles["Heading2"]),
        Paragraph(period, styles["Normal"]),
        Spacer(1, 6 * mm),
        Paragraph("Revenue", styles["Heading3"]),
        _section_table(statement.revenue, "Total revenue", statement.total_revenue_minor),
        Spacer(1, 6 * mm),
        Paragraph("Expenses", styles["Heading3"]),
        _section_table(statement.expenses, "Total expenses", statement.total_expenses_minor),
        Spacer(1, 6 * mm),
        Paragraph(f"Net income: {_money(statement.net_income_minor)}", styles["Heading3"]),
    ]

    doc.build(story)
    return buffer.getvalue()
