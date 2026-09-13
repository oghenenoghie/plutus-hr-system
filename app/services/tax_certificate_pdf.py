import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.domain.money import Money
from app.models.organisation import Organisation
from app.services.payroll_reports import AnnualTaxReconciliation


def _money(minor: int) -> str:
    return Money(minor).display()


def render_tax_certificate_pdf(
    *, organisation: Organisation, reconciliation: AnnualTaxReconciliation
) -> bytes:
    """Renders one employee's annual tax certificate — a summary of what
    they earned and what was withheld for the year, entirely from figures
    already aggregated from LOCKED payslips (see annual_tax_reconciliation),
    never recomputed independently."""
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
    title_style = ParagraphStyle("CertTitle", parent=styles["Title"], fontSize=16)
    small_style = ParagraphStyle("CertSmall", parent=styles["Normal"], fontSize=9)

    story: list[Flowable] = [
        Paragraph(organisation.name, title_style),
        Paragraph(f"Annual Tax Certificate — {reconciliation.tax_year}", styles["Heading2"]),
        Spacer(1, 6 * mm),
    ]

    employee_table = Table(
        [
            ["Employee", reconciliation.full_name],
            ["Employee number", reconciliation.employee_number],
            ["TIN", reconciliation.tin or "-"],
            ["Tax year", str(reconciliation.tax_year)],
        ],
        colWidths=[50 * mm, 100 * mm],
    )
    employee_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
            ]
        )
    )
    story.append(employee_table)
    story.append(Spacer(1, 6 * mm))

    summary_rows = [
        ["Description", "Amount"],
        ["Total gross pay for the year", _money(reconciliation.total_gross_minor)],
        ["Total pension (employee) withheld", _money(reconciliation.total_pension_employee_minor)],
        ["Total NHF withheld", _money(reconciliation.total_nhf_minor)],
        ["Total PAYE tax withheld", _money(reconciliation.total_paye_minor)],
    ]
    summary_table = Table(summary_rows, colWidths=[100 * mm, 50 * mm])
    summary_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 10 * mm))
    story.append(
        Paragraph(f"Based on {reconciliation.payslip_count} payslip(s) for the year.", small_style)
    )

    doc.build(story)
    return buffer.getvalue()
