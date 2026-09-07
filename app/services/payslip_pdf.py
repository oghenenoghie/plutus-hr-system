import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.domain.money import Money
from app.models.employee import Employee
from app.models.organisation import Organisation
from app.models.payslip import Payslip


def _money(minor: int) -> str:
    return Money(minor).display()


def render_payslip_pdf(
    *, organisation: Organisation, employee: Employee, payslip: Payslip
) -> bytes:
    """Renders a single payslip as a PDF, entirely from figures already
    stored on the payslip row — never recomputed, since the payslip itself
    is the authoritative append-only record of what was paid.
    """
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
    title_style = ParagraphStyle("PayslipTitle", parent=styles["Title"], fontSize=16)
    small_style = ParagraphStyle("PayslipSmall", parent=styles["Normal"], fontSize=9)

    story: list[Flowable] = [
        Paragraph(organisation.name, title_style),
        Paragraph("Payslip", styles["Heading2"]),
        Spacer(1, 4 * mm),
        Paragraph(
            f"Pay period: {payslip.period_start.isoformat()} to {payslip.period_end.isoformat()}",
            styles["Normal"],
        ),
        Spacer(1, 6 * mm),
    ]

    employee_table = Table(
        [
            ["Employee", employee.full_name],
            ["Employee number", employee.employee_number],
            ["Job title", employee.job_title or "-"],
            ["State of residence", employee.state_of_residence],
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

    breakdown_rows = [
        ["Description", "Amount"],
        ["Gross pay", _money(payslip.gross_minor)],
        ["Pensionable pay", _money(payslip.pensionable_pay_minor)],
        ["Pension (employee)", f"-{_money(payslip.pension_employee_minor)}"],
        ["National Housing Fund (NHF)", f"-{_money(payslip.nhf_minor)}"],
        ["PAYE tax", f"-{_money(payslip.paye_minor)}"],
        ["Net pay", _money(payslip.net_minor)],
    ]
    breakdown_table = Table(breakdown_rows, colWidths=[100 * mm, 50 * mm])
    breakdown_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.black),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(breakdown_table)
    story.append(Spacer(1, 10 * mm))
    story.append(
        Paragraph(
            f"Employer pension contribution: {_money(payslip.pension_employer_minor)} "
            "(not deducted from employee pay)",
            small_style,
        )
    )
    story.append(Paragraph(f"Compliance rule version: {payslip.rule_version_id}", small_style))

    doc.build(story)
    return buffer.getvalue()
