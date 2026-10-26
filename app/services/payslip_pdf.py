import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.compliance.engine.calculate import LineKind
from app.domain.money import Money
from app.models.employee import Employee
from app.models.organisation import Organisation
from app.models.payslip import Payslip
from app.services.engine_payroll import is_engine_payslip

# What comes off an engine payslip's net pay after its statutory lines, as
# recorded in its derivation outputs.
_OTHER_DEDUCTIONS = (
    ("loan_deduction_minor", "Loan repayment"),
    ("benefit_deduction_minor", "Benefit deductions"),
    ("union_dues_deduction_minor", "Union dues"),
)


def _money(minor: int, currency: str) -> str:
    return Money(minor, currency).display()


def _nigerian_rows(payslip: Payslip, currency: str) -> list[list[str]]:
    return [
        ["Gross pay", _money(payslip.gross_minor, currency)],
        ["Pensionable pay", _money(payslip.pensionable_pay_minor, currency)],
        ["Pension (employee)", f"-{_money(payslip.pension_employee_minor, currency)}"],
        ["National Housing Fund (NHF)", f"-{_money(payslip.nhf_minor, currency)}"],
        ["PAYE tax", f"-{_money(payslip.paye_minor, currency)}"],
    ]


def _engine_rows(payslip: Payslip, currency: str) -> list[list[str]]:
    """Gross pay, then everything that came off it: the employee's statutory
    lines in calculation order, then loans, benefits and union dues."""
    rows = [["Gross pay", _money(payslip.gross_minor, currency)]]
    rows += [
        [line.name, f"-{_money(line.amount_minor, currency)}"]
        for line in payslip.statutory_lines
        if line.kind != LineKind.EMPLOYER_CONTRIBUTION.value
    ]
    outputs = payslip.derivation.get("outputs")
    outputs = outputs if isinstance(outputs, dict) else {}
    rows += [
        [label, f"-{_money(int(outputs[key]), currency)}"]
        for key, label in _OTHER_DEDUCTIONS
        if int(outputs.get(key, 0))
    ]
    return rows


def _employer_note(payslip: Payslip, currency: str) -> str:
    if not is_engine_payslip(payslip):
        return (
            f"Employer pension contribution: {_money(payslip.pension_employer_minor, currency)} "
            "(not deducted from employee pay)"
        )
    employer = [
        f"{line.name} {_money(line.amount_minor, currency)}"
        for line in payslip.statutory_lines
        if line.kind == LineKind.EMPLOYER_CONTRIBUTION.value
    ]
    if not employer:
        return "No employer contributions this period."
    return f"Employer contributions (not deducted from employee pay): {'; '.join(employer)}"


def render_payslip_pdf(
    *, organisation: Organisation, employee: Employee, payslip: Payslip
) -> bytes:
    """Renders a single payslip as a PDF, entirely from figures already
    stored on the payslip row — never recomputed, since the payslip itself
    is the authoritative append-only record of what was paid. Amounts are in
    the organisation's currency. A Nigerian payslip shows its pension, NHF
    and PAYE; an engine payslip shows its country's own statutory lines.
    """
    currency = organisation.currency
    engine = is_engine_payslip(payslip)
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
    address_style = ParagraphStyle(
        "PayslipAddress", parent=small_style, alignment=TA_CENTER, textColor=colors.grey
    )

    story: list[Flowable] = [
        Paragraph(organisation.name, title_style),
        *([Paragraph(escape(organisation.address), address_style)] if organisation.address else []),
        Paragraph("Payslip", styles["Heading2"]),
        Spacer(1, 4 * mm),
        Paragraph(
            f"Pay period: {payslip.period_start.isoformat()} to {payslip.period_end.isoformat()}",
            styles["Normal"],
        ),
        Spacer(1, 6 * mm),
    ]

    employee_rows = [
        ["Employee", employee.full_name],
        ["Employee number", employee.employee_number],
        ["Job title", employee.job_title or "-"],
    ]
    if not engine:
        # Nigerian PAYE goes to the state of residence's revenue service.
        employee_rows.append(["State of residence", employee.state_of_residence])
    employee_table = Table(
        employee_rows,
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
        *(_engine_rows(payslip, currency) if engine else _nigerian_rows(payslip, currency)),
        ["Net pay", _money(payslip.net_minor, currency)],
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
    story.append(Paragraph(escape(_employer_note(payslip, currency)), small_style))
    rule_label = "Country rule set" if engine else "Compliance rule version"
    story.append(Paragraph(f"{rule_label}: {escape(payslip.rule_version_id)}", small_style))

    doc.build(story)
    return buffer.getvalue()
