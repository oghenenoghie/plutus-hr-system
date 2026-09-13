import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.domain.money import Money
from app.models.customer import Customer
from app.models.organisation import Organisation
from app.models.vendor import Vendor
from app.services.reports import CustomerStatementLine, VendorStatementLine


def _money(minor: int) -> str:
    return Money(minor).display()


def _period_label(from_date: date | None, to_date: date | None) -> str:
    if from_date and to_date:
        return f"{from_date.isoformat()} to {to_date.isoformat()}"
    if from_date:
        return f"From {from_date.isoformat()}"
    if to_date:
        return f"Up to {to_date.isoformat()}"
    return "All time"


def render_vendor_statement_pdf(
    *,
    organisation: Organisation,
    vendor: Vendor,
    lines: list[VendorStatementLine],
    from_date: date | None,
    to_date: date | None,
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

    story: list[Flowable] = [
        Paragraph(organisation.name, title_style),
        Paragraph(f"Statement of Account — {vendor.name}", styles["Heading2"]),
        Paragraph(_period_label(from_date, to_date), styles["Normal"]),
        Spacer(1, 6 * mm),
    ]

    rows = [["Bill #", "Date", "Amount", "Status", "Balance"]]
    rows.extend(
        [
            line.bill_number,
            line.bill_date.isoformat(),
            _money(line.amount_minor),
            line.status.value,
            _money(line.running_balance_minor),
        ]
        for line in lines
    )
    table = Table(rows, colWidths=[35 * mm, 25 * mm, 35 * mm, 30 * mm, 35 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 6 * mm))
    balance = lines[-1].running_balance_minor if lines else 0
    story.append(Paragraph(f"Balance owed: {_money(balance)}", styles["Heading3"]))

    doc.build(story)
    return buffer.getvalue()


def render_customer_statement_pdf(
    *,
    organisation: Organisation,
    customer: Customer,
    lines: list[CustomerStatementLine],
    from_date: date | None,
    to_date: date | None,
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

    story: list[Flowable] = [
        Paragraph(organisation.name, title_style),
        Paragraph(f"Statement of Account — {customer.name}", styles["Heading2"]),
        Paragraph(_period_label(from_date, to_date), styles["Normal"]),
        Spacer(1, 6 * mm),
    ]

    rows = [["Invoice #", "Date", "Amount", "Status", "Balance"]]
    rows.extend(
        [
            line.invoice_number,
            line.issue_date.isoformat(),
            _money(line.amount_minor),
            line.status.value,
            _money(line.running_balance_minor),
        ]
        for line in lines
    )
    table = Table(rows, colWidths=[35 * mm, 25 * mm, 35 * mm, 30 * mm, 35 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 6 * mm))
    balance = lines[-1].running_balance_minor if lines else 0
    story.append(Paragraph(f"Balance owed: {_money(balance)}", styles["Heading3"]))

    doc.build(story)
    return buffer.getvalue()
