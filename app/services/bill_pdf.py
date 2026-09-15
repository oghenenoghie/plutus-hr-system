import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.domain.money import Money
from app.models.bill import Bill
from app.models.organisation import Organisation
from app.models.vendor import Vendor


def _money(minor: int) -> str:
    return Money(minor).display()


def render_bill_pdf(*, organisation: Organisation, bill: Bill, vendor: Vendor) -> bytes:
    """Renders a single bill as a PDF, entirely from figures already
    stored on the bill row — never recomputed, same principle as
    render_payslip_pdf/render_invoice_pdf."""
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
    title_style = ParagraphStyle("BillTitle", parent=styles["Title"], fontSize=16)

    story: list[Flowable] = [
        Paragraph(organisation.name, title_style),
        Paragraph(f"Bill {bill.bill_number}", styles["Heading2"]),
        Spacer(1, 6 * mm),
    ]

    header_table = Table(
        [
            ["From", vendor.name],
            ["Bill date", bill.bill_date.isoformat()],
            ["Due date", bill.due_date.isoformat()],
            ["Status", bill.status.value],
        ],
        colWidths=[40 * mm, 110 * mm],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 6 * mm))

    line_rows = [
        ["Description", "Amount"],
        [bill.description or "Goods/services received", _money(bill.amount_minor)],
    ]
    if bill.vat_minor:
        line_rows.append(["VAT", _money(bill.vat_minor)])
    if bill.wht_category is not None:
        line_rows.append(
            [f"Withholding tax ({bill.wht_category})", f"-{_money(bill.wht_amount_minor)}"]
        )
    line_rows.append(["Net payable", _money(bill.net_payable_minor)])

    line_table = Table(line_rows, colWidths=[110 * mm, 40 * mm])
    line_table.setStyle(
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
    story.append(line_table)

    doc.build(story)
    return buffer.getvalue()
