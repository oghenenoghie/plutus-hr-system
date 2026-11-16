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
    return Money(minor, currency).display_grouped()


def _deduction(minor: int, currency: str) -> str:
    """A deduction as a negative amount; nothing deducted reads as 0, not -0."""
    return f"-{_money(minor, currency)}" if minor else _money(0, currency)


def _percent(part: int, whole: int) -> str:
    """part as a percentage of whole, to one decimal place ("8%", "2.5%")."""
    if not whole:
        return ""
    tenths = (part * 1000 + whole // 2) // whole
    whole_part, fraction = divmod(tenths, 10)
    return f"{whole_part}%" if not fraction else f"{whole_part}.{fraction}%"


def _outputs(payslip: Payslip) -> dict[str, object]:
    outputs = payslip.derivation.get("outputs")
    return outputs if isinstance(outputs, dict) else {}


def _inputs(payslip: Payslip) -> dict[str, object]:
    inputs = payslip.derivation.get("inputs")
    return inputs if isinstance(inputs, dict) else {}


def _int(mapping: dict[str, object], key: str) -> int:
    value = mapping.get(key, 0)
    return value if isinstance(value, int) else 0


def _other_deduction_rows(payslip: Payslip, currency: str) -> list[list[str]]:
    outputs = _outputs(payslip)
    return [
        [label, _deduction(_int(outputs, key), currency)]
        for key, label in _OTHER_DEDUCTIONS
        if _int(outputs, key)
    ]


def _nigerian_rows(payslip: Payslip, currency: str) -> list[list[str]]:
    basic = _int(_inputs(payslip), "basic_minor")
    pension_rate = _percent(payslip.pension_employee_minor, payslip.pensionable_pay_minor)
    nhf_rate = _percent(payslip.nhf_minor, basic)
    return [
        ["Gross pay", _money(payslip.gross_minor, currency)],
        [
            (
                f"Pension, employee {pension_rate} of pensionable pay "
                f"({_money(payslip.pensionable_pay_minor, currency)})"
            ),
            _deduction(payslip.pension_employee_minor, currency),
        ],
        [
            f"National Housing Fund (NHF) {nhf_rate} of basic ({_money(basic, currency)})"
            if basic
            else "National Housing Fund (NHF)",
            _deduction(payslip.nhf_minor, currency),
        ],
        ["PAYE (income tax)", _deduction(payslip.paye_minor, currency)],
        *_other_deduction_rows(payslip, currency),
    ]


def _year_to_date_rows(payslip: Payslip, currency: str) -> list[list[str]]:
    """Gross pay and PAYE for the tax year so far, this period included."""
    inputs = _inputs(payslip)
    return [
        [
            "Gross pay this year",
            _money(_int(inputs, "cumulative_gross_before_minor") + payslip.gross_minor, currency),
        ],
        [
            "Chargeable income this year",
            _money(payslip.cumulative_chargeable_income_minor, currency),
        ],
        [
            "PAYE withheld this year",
            _money(
                _int(inputs, "cumulative_paye_withheld_before_minor") + payslip.paye_minor,
                currency,
            ),
        ],
    ]


def _paye_note(payslip: Payslip, currency: str) -> str | None:
    """Why PAYE is what it is, when that isn't obvious: PAYE is worked out on
    the year's chargeable income so far, less what was already withheld."""
    working = payslip.derivation.get("paye_working")
    if not isinstance(working, dict):
        return None
    ceiling = working.get("first_band_ceiling_minor")
    rate = working.get("first_band_rate_ppm")
    to_date = working.get("chargeable_income_to_date_minor")
    if (
        payslip.paye_minor == 0
        and isinstance(ceiling, int)
        and isinstance(to_date, int)
        and rate == 0
        and to_date <= ceiling
    ):
        return (
            f"No PAYE this period: chargeable income for the year so far "
            f"({_money(to_date, currency)}) is within the first {_money(ceiling, currency)} "
            "of the year, which is taxed at 0%. PAYE is worked out on the year's income to "
            "date, so it starts once that is passed."
        )
    due = working.get("tax_due_to_date_minor")
    before = working.get("withheld_before_minor")
    if isinstance(due, int) and isinstance(before, int) and before:
        return (
            f"PAYE: {_money(due, currency)} due on the year's chargeable income so far, "
            f"less {_money(before, currency)} already withheld this year."
        )
    return None


def _engine_rows(payslip: Payslip, currency: str) -> list[list[str]]:
    """Gross pay, then everything that came off it: the employee's statutory
    lines in calculation order, then loans, benefits and union dues."""
    rows = [["Gross pay", _money(payslip.gross_minor, currency)]]
    rows += [
        [line.name, _deduction(line.amount_minor, currency)]
        for line in payslip.statutory_lines
        if line.kind != LineKind.EMPLOYER_CONTRIBUTION.value
    ]
    rows += _other_deduction_rows(payslip, currency)
    return rows


def _employer_note(payslip: Payslip, currency: str) -> str:
    if not is_engine_payslip(payslip):
        rate = _percent(payslip.pension_employer_minor, payslip.pensionable_pay_minor)
        return (
            f"Paid by the employer on top of gross pay (not deducted from it): pension "
            f"{rate} of pensionable pay, {_money(payslip.pension_employer_minor, currency)}."
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
    employee_rows.append(["TIN" if not engine else "Tax ID", employee.tin or "Not recorded"])
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
    if not engine:
        story.append(Spacer(1, 6 * mm))
        year_table = Table(_year_to_date_rows(payslip, currency), colWidths=[100 * mm, 50 * mm])
        year_table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(year_table)
        paye_note = _paye_note(payslip, currency)
        if paye_note:
            story.append(Spacer(1, 3 * mm))
            story.append(Paragraph(escape(paye_note), small_style))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(escape(_employer_note(payslip, currency)), small_style))
    rule_label = "Country rule set" if engine else "Compliance rule version"
    story.append(Paragraph(f"{rule_label}: {escape(payslip.rule_version_id)}", small_style))

    doc.build(story)
    return buffer.getvalue()
