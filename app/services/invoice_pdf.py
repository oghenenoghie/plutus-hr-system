import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.domain.money import Money
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.organisation import Organisation


def _money(minor: int, currency: str) -> str:
    return Money(minor, currency).display_grouped()


def _vat_label(invoice: Invoice) -> str:
    """The VAT line's label: the rate's name as fixed on the invoice."""
    if invoice.vat_treatment is None:
        return "VAT"
    return invoice.vat_rate_name or "VAT"


def render_invoice_pdf(
    *, organisation: Organisation, invoice: Invoice, customer: Customer
) -> bytes:
    """Renders a single invoice as a PDF, entirely from figures already
    stored on the invoice row — never recomputed, same principle as
    render_payslip_pdf. The supplier's tax ID is printed at the top right,
    with the invoice's number and dates, as a tax invoice must show it."""
    currency = organisation.currency
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    name_style = ParagraphStyle(
        "InvoiceSeller", parent=styles["Heading1"], fontSize=15, spaceAfter=2
    )
    small_style = ParagraphStyle("InvoiceSmall", parent=styles["Normal"], fontSize=9, leading=12)
    right_title = ParagraphStyle(
        "InvoiceTitleRight", parent=styles["Heading1"], fontSize=18, alignment=TA_RIGHT
    )
    right_style = ParagraphStyle(
        "InvoiceRight", parent=styles["Normal"], fontSize=9, leading=13, alignment=TA_RIGHT
    )

    seller: list[Flowable] = [Paragraph(escape(organisation.name), name_style)]
    if organisation.address:
        seller.append(Paragraph(escape(organisation.address).replace("\n", "<br/>"), small_style))

    tax_id = organisation.company_tin or "Not set"
    details = [
        f"<b>TIN:</b> {escape(tax_id)}",
        *(
            [f"<b>RC number:</b> {escape(organisation.rc_number)}"]
            if organisation.rc_number
            else []
        ),
        f"<b>Invoice no.:</b> {escape(invoice.invoice_number)}",
        f"<b>Issue date:</b> {invoice.issue_date.isoformat()}",
        f"<b>Due date:</b> {invoice.due_date.isoformat()}",
    ]
    heading: list[Flowable] = [
        Paragraph("INVOICE", right_title),
        Paragraph("<br/>".join(details), right_style),
    ]
    top = Table([[seller, heading]], colWidths=[95 * mm, 75 * mm])
    top.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story: list[Flowable] = [top, Spacer(1, 8 * mm)]

    bill_to = [f"<b>{escape(customer.name)}</b>"]
    if customer.address:
        bill_to.append(escape(customer.address).replace("\n", "<br/>"))
    if customer.tin:
        bill_to.append(f"Tax ID: {escape(customer.tin)}")
    party_table = Table(
        [
            ["Bill to", Paragraph("<br/>".join(bill_to), styles["Normal"])],
            ["Status", invoice.status.value],
        ],
        colWidths=[30 * mm, 140 * mm],
    )
    party_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
            ]
        )
    )
    story.append(party_table)
    story.append(Spacer(1, 6 * mm))

    line_rows = [
        ["Description", "Amount"],
        [invoice.description or "Goods and services", _money(invoice.amount_minor, currency)],
        ["Subtotal (before VAT)", _money(invoice.amount_minor, currency)],
        [_vat_label(invoice), _money(invoice.vat_minor, currency)],
        ["Total due", _money(invoice.total_minor, currency)],
    ]
    line_table = Table(line_rows, colWidths=[120 * mm, 50 * mm])
    line_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
                ("LINEABOVE", (0, 2), (-1, 2), 0.5, colors.grey),
                ("TEXTCOLOR", (0, 2), (0, 3), colors.grey),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ]
        )
    )
    story.append(line_table)
    story.append(Spacer(1, 8 * mm))
    story.append(
        Paragraph(
            f"Please pay by {invoice.due_date.isoformat()}, quoting invoice "
            f"{escape(invoice.invoice_number)}.",
            small_style,
        )
    )

    doc.build(story)
    return buffer.getvalue()
