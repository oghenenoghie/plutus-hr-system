import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.domain.money import Money
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.organisation import Organisation


def _money(minor: int) -> str:
    return Money(minor).display()


def render_invoice_pdf(
    *, organisation: Organisation, invoice: Invoice, customer: Customer
) -> bytes:
    """Renders a single invoice as a PDF, entirely from figures already
    stored on the invoice row — never recomputed, same principle as
    render_payslip_pdf."""
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
    title_style = ParagraphStyle("InvoiceTitle", parent=styles["Title"], fontSize=16)

    story: list[Flowable] = [
        Paragraph(organisation.name, title_style),
        Paragraph(f"Invoice {invoice.invoice_number}", styles["Heading2"]),
        Spacer(1, 6 * mm),
    ]

    header_table = Table(
        [
            ["Bill to", customer.name],
            ["Issue date", invoice.issue_date.isoformat()],
            ["Due date", invoice.due_date.isoformat()],
            ["Status", invoice.status.value],
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
        [invoice.description or "Services rendered", _money(invoice.amount_minor)],
        ["Total", _money(invoice.amount_minor)],
    ]
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
