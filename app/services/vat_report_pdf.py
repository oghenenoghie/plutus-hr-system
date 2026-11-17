"""The monthly VAT report as a PDF, to print and file with the month's
records."""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.domain.money import Money
from app.models.organisation import Organisation
from app.schemas.vat_report import VatReportGroup, VatReportOut
from app.services.posting import lagos_date

_KINDS = {"invoice": "Invoice", "credit_note": "Credit note", "bill": "Bill"}


def month_title(report: VatReportOut) -> str:
    return report.period_start.strftime("%B %Y")


def _summary_table(rows: list[list[str]], *, totals: set[int], grand: int | None = None) -> Table:
    table = Table(rows, colWidths=[78 * mm, 22 * mm, 35 * mm, 35 * mm], repeatRows=1)
    style = TableStyle(
        [
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.grey),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
        ]
    )
    for index in totals:
        style.add("FONTNAME", (0, index), (-1, index), "Helvetica-Bold")
        style.add("LINEABOVE", (2, index), (-1, index), 0.5, colors.grey)
    if grand is not None:
        style.add("FONTNAME", (0, grand), (-1, grand), "Helvetica-Bold")
        style.add("LINEABOVE", (0, grand), (-1, grand), 0.75, colors.black)
        style.add("LINEBELOW", (0, grand), (-1, grand), 1.5, colors.black)
    table.setStyle(style)
    return table


def _group_rows(groups: list[VatReportGroup], currency: str) -> list[list[str]]:
    return [
        [
            group.label,
            str(group.document_count),
            Money(group.net_minor, currency).display_grouped(),
            Money(group.vat_minor, currency).display_grouped(),
        ]
        for group in groups
    ]


def render_vat_report_pdf(*, organisation: Organisation, report: VatReportOut) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        title=f"VAT report {month_title(report)}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ReportTitle", parent=styles["Title"], fontSize=16)
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8.5, textColor=colors.grey)
    currency = report.currency

    def money(minor: int) -> str:
        # A figure taken off (a credit note) in brackets, as accounts show it.
        if minor < 0:
            return f"({Money(-minor, currency).display_grouped()})"
        return Money(minor, currency).display_grouped()

    period = (
        f"{month_title(report)} · {report.period_start.strftime('%d %b %Y')} to "
        f"{report.period_end.strftime('%d %b %Y')}"
    )
    story: list[Flowable] = [Paragraph(organisation.name, title_style)]
    if organisation.company_tin:
        story.append(Paragraph(f"Tax ID: {organisation.company_tin}", styles["Normal"]))
    story += [
        Paragraph("VAT Report", styles["Heading2"]),
        Paragraph(period, styles["Normal"]),
        Spacer(1, 5 * mm),
    ]

    header = ["Output VAT: sales", "Documents", "Net", "VAT"]
    output_rows = [header, *_group_rows(report.output_groups, currency)]
    if not report.output_groups:
        output_rows.append(["No invoices sent this month", "0", money(0), money(0)])
    if report.credit_note_count:
        output_rows.append(
            [
                "Less: credit notes",
                str(report.credit_note_count),
                money(report.credit_note_net_minor),
                money(report.credit_note_vat_minor),
            ]
        )
    output_rows.append(
        [
            "Output VAT",
            "",
            money(report.sales_net_minor - report.credit_note_net_minor),
            money(report.output_vat_minor),
        ]
    )
    story += [_summary_table(output_rows, totals={len(output_rows) - 1}), Spacer(1, 5 * mm)]

    input_rows = [["Input VAT: purchases", "Documents", "Net", "VAT"]]
    input_rows += _group_rows(report.input_groups, currency)
    if not report.input_groups:
        input_rows.append(["No bills approved for this month", "0", money(0), money(0)])
    input_rows.append(
        ["Input VAT", "", money(report.purchases_net_minor), money(report.input_vat_minor)]
    )
    story += [_summary_table(input_rows, totals={len(input_rows) - 1}), Spacer(1, 5 * mm)]

    net_label = {
        "payable": "Net VAT payable",
        "refundable": "Net VAT refundable (credit)",
        "nil": "Net VAT",
    }[report.position]
    summary_rows = [
        ["Summary", "", "", ""],
        ["Output VAT", "", "", money(report.output_vat_minor)],
        ["Less: input VAT", "", "", money(report.input_vat_minor)],
        [net_label, "", "", money(abs(report.net_vat_minor))],
    ]
    story += [_summary_table(summary_rows, totals=set(), grand=3), Spacer(1, 6 * mm)]

    if report.documents:
        story.append(Paragraph("Documents", styles["Heading3"]))
        rows: list[list[str | Paragraph]] = [
            ["Date", "Type", "Number", "Customer or vendor", "Rate", "Net", "VAT"]
        ]
        for document in report.documents:
            rows.append(
                [
                    document.date.strftime("%d %b"),
                    _KINDS[document.kind],
                    Paragraph(document.number, small),
                    Paragraph(document.party_name, small),
                    Paragraph(document.rate_label, small),
                    money(document.net_minor),
                    money(document.vat_minor),
                ]
            )
        table = Table(
            rows,
            colWidths=[14 * mm, 19 * mm, 24 * mm, 38 * mm, 25 * mm, 25 * mm, 25 * mm],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ("ALIGN", (5, 0), (-1, -1), "RIGHT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.grey),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
                ]
            )
        )
        story += [table, Spacer(1, 5 * mm)]

    notes = [
        (
            "Invoices count once sent and bills once approved, each in the month of its own "
            "date; credit notes count in the month they were issued."
        ),
    ]
    if report.draft_invoice_count or report.draft_bill_count:
        notes.append(
            f"Not included: {report.draft_invoice_count} draft invoice(s) and "
            f"{report.draft_bill_count} draft bill(s) dated this month."
        )
    notes.append(
        f"Generated {lagos_date(report.generated_at).strftime('%d %b %Y')} from the records in "
        "Plutus. Check the figures against the tax authority's return before filing."
    )
    story += [Paragraph(note, small) for note in notes]

    doc.build(story)
    return buffer.getvalue()
