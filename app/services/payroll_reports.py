import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.pay_run import PayRun, PayRunStatus
from app.models.payslip import Payslip
from app.models.payslip_statutory_line import PayslipStatutoryLine


@dataclass(frozen=True)
class StatutoryAmount:
    """One of an engine country's statutory lines on a report (see
    app/services/engine_payroll.py). A Nigerian payslip has none: its
    figures are its pension, NHF and PAYE columns."""

    code: str
    name: str
    kind: str
    amount_minor: int


@dataclass(frozen=True)
class PayrollRegisterLine:
    """One employee's row in a single pay run's payroll register — every
    payslip figure that's its own column plus the three deductions that
    live inside derivation["outputs"] instead (loans, benefits, union
    dues), since Payslip itself doesn't carry dedicated columns for them.
    """

    employee_id: uuid.UUID
    employee_number: str
    full_name: str
    gross_minor: int
    pension_employee_minor: int
    pension_employer_minor: int
    nhf_minor: int
    paye_minor: int
    loan_deduction_minor: int
    benefit_deduction_minor: int
    union_dues_deduction_minor: int
    net_minor: int
    statutory_lines: tuple[StatutoryAmount, ...] = ()


def _outputs(payslip: Payslip) -> dict[str, Any]:
    derivation = payslip.derivation
    outputs = derivation.get("outputs", {}) if isinstance(derivation, dict) else {}
    return outputs if isinstance(outputs, dict) else {}


def payroll_register(
    db: Session, org_id: uuid.UUID, pay_run_id: uuid.UUID
) -> list[PayrollRegisterLine]:
    rows = db.execute(
        select(Payslip, Employee.employee_number, Employee.full_name)
        .join(Employee, Payslip.employee_id == Employee.id)
        .where(Payslip.org_id == org_id, Payslip.pay_run_id == pay_run_id)
        .order_by(Employee.employee_number)
    ).all()

    lines = []
    for payslip, employee_number, full_name in rows:
        outputs = _outputs(payslip)
        lines.append(
            PayrollRegisterLine(
                employee_id=payslip.employee_id,
                employee_number=employee_number,
                full_name=full_name,
                gross_minor=payslip.gross_minor,
                pension_employee_minor=payslip.pension_employee_minor,
                pension_employer_minor=payslip.pension_employer_minor,
                nhf_minor=payslip.nhf_minor,
                paye_minor=payslip.paye_minor,
                loan_deduction_minor=int(outputs.get("loan_deduction_minor", 0)),
                benefit_deduction_minor=int(outputs.get("benefit_deduction_minor", 0)),
                union_dues_deduction_minor=int(outputs.get("union_dues_deduction_minor", 0)),
                net_minor=payslip.net_minor,
                statutory_lines=tuple(
                    StatutoryAmount(line.code, line.name, line.kind, line.amount_minor)
                    for line in payslip.statutory_lines
                ),
            )
        )
    return lines


@dataclass(frozen=True)
class PayeByStateLine:
    state_of_residence: str
    employee_count: int
    total_paye_minor: int


def paye_by_state(
    db: Session,
    org_id: uuid.UUID,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[PayeByStateLine]:
    """PAYE withheld, grouped by employee state of residence — Nigerian
    PAYE is remitted to each State Internal Revenue Service based on
    where the employee resides (nigeria-statutory-compliance.md §9), so
    this is what an org actually needs to work out what's owed to which
    state. Only LOCKED runs count, same reasoning as payroll_cost_by_department.
    """
    query = (
        select(
            Employee.state_of_residence,
            func.count(func.distinct(Payslip.employee_id)),
            func.coalesce(func.sum(Payslip.paye_minor), 0),
        )
        .select_from(Payslip)
        .join(PayRun, Payslip.pay_run_id == PayRun.id)
        .join(Employee, Payslip.employee_id == Employee.id)
        .where(Payslip.org_id == org_id, PayRun.status == PayRunStatus.LOCKED)
        .group_by(Employee.state_of_residence)
        .order_by(Employee.state_of_residence)
    )
    if from_date is not None:
        query = query.where(PayRun.period_end >= from_date)
    if to_date is not None:
        query = query.where(PayRun.period_end <= to_date)

    return [
        PayeByStateLine(
            state_of_residence=state_of_residence,
            employee_count=employee_count,
            total_paye_minor=int(total_paye_minor),
        )
        for state_of_residence, employee_count, total_paye_minor in db.execute(query).all()
    ]


@dataclass(frozen=True)
class StatutorySummaryLine:
    code: str
    name: str
    kind: str
    authority: str
    employee_count: int
    base_minor: int
    amount_minor: int


def statutory_summary(
    db: Session,
    org_id: uuid.UUID,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[StatutorySummaryLine]:
    """An engine country's statutory lines totalled by line code over LOCKED
    runs ending in the window, in the order the engine calculates them. A
    line's base is the earnings it was worked out on, summed over payslips.
    Empty for Nigeria, whose payslips carry no lines: its schedules are PAYE
    by state and the statutory liabilities."""
    query = (
        select(
            PayslipStatutoryLine.code,
            PayslipStatutoryLine.name,
            PayslipStatutoryLine.kind,
            PayslipStatutoryLine.authority,
            func.count(func.distinct(Payslip.employee_id)),
            func.coalesce(func.sum(PayslipStatutoryLine.base_minor), 0),
            func.coalesce(func.sum(PayslipStatutoryLine.amount_minor), 0),
        )
        .select_from(PayslipStatutoryLine)
        .join(Payslip, PayslipStatutoryLine.payslip_id == Payslip.id)
        .join(PayRun, PayslipStatutoryLine.pay_run_id == PayRun.id)
        .where(PayslipStatutoryLine.org_id == org_id, PayRun.status == PayRunStatus.LOCKED)
        .group_by(
            PayslipStatutoryLine.code,
            PayslipStatutoryLine.name,
            PayslipStatutoryLine.kind,
            PayslipStatutoryLine.authority,
        )
        .order_by(func.min(PayslipStatutoryLine.position), PayslipStatutoryLine.code)
    )
    if from_date is not None:
        query = query.where(PayRun.period_end >= from_date)
    if to_date is not None:
        query = query.where(PayRun.period_end <= to_date)
    return [
        StatutorySummaryLine(
            code=code,
            name=name,
            kind=kind,
            authority=authority,
            employee_count=employee_count,
            base_minor=int(base_minor),
            amount_minor=int(amount_minor),
        )
        for code, name, kind, authority, employee_count, base_minor, amount_minor in db.execute(
            query
        ).all()
    ]


@dataclass(frozen=True)
class AnnualTaxReconciliation:
    """One employee's tax year in summary — gross earned, PAYE withheld
    through cumulative payroll, and their employer pension/NHF
    contributions, across every LOCKED payslip whose period falls in the
    given year. Since PAYE here is always computed cumulatively
    (nigeria-statutory-compliance.md's year-to-date mechanism), summing
    each period's own paye_minor already gives the correct annual total —
    there's no separate year-end true-up calculation to perform.
    """

    employee_id: uuid.UUID
    employee_number: str
    full_name: str
    tin: str | None
    tax_year: int
    total_gross_minor: int
    total_pension_employee_minor: int
    total_nhf_minor: int
    total_paye_minor: int
    payslip_count: int
    # An engine country's lines totalled for the year, in calculation order.
    statutory_totals: tuple[StatutoryAmount, ...] = ()


def _annual_statutory_totals(
    db: Session, org_id: uuid.UUID, *, year_start: date, year_end: date
) -> dict[uuid.UUID, tuple[StatutoryAmount, ...]]:
    rows = db.execute(
        select(
            Payslip.employee_id,
            PayslipStatutoryLine.code,
            PayslipStatutoryLine.name,
            PayslipStatutoryLine.kind,
            func.coalesce(func.sum(PayslipStatutoryLine.amount_minor), 0),
        )
        .select_from(PayslipStatutoryLine)
        .join(Payslip, PayslipStatutoryLine.payslip_id == Payslip.id)
        .join(PayRun, PayslipStatutoryLine.pay_run_id == PayRun.id)
        .where(
            PayslipStatutoryLine.org_id == org_id,
            PayRun.status == PayRunStatus.LOCKED,
            Payslip.period_start >= year_start,
            Payslip.period_end <= year_end,
        )
        .group_by(
            Payslip.employee_id,
            PayslipStatutoryLine.code,
            PayslipStatutoryLine.name,
            PayslipStatutoryLine.kind,
        )
        .order_by(Payslip.employee_id, func.min(PayslipStatutoryLine.position))
    ).all()
    totals: dict[uuid.UUID, list[StatutoryAmount]] = defaultdict(list)
    for employee_id, code, name, kind, amount_minor in rows:
        totals[employee_id].append(StatutoryAmount(code, name, kind, int(amount_minor)))
    return {employee_id: tuple(amounts) for employee_id, amounts in totals.items()}


def annual_tax_reconciliation(
    db: Session, org_id: uuid.UUID, *, tax_year: int
) -> list[AnnualTaxReconciliation]:
    year_start = date(tax_year, 1, 1)
    year_end = date(tax_year, 12, 31)
    rows = db.execute(
        select(
            Payslip.employee_id,
            Employee.employee_number,
            Employee.full_name,
            Employee.tin,
            func.coalesce(func.sum(Payslip.gross_minor), 0),
            func.coalesce(func.sum(Payslip.pension_employee_minor), 0),
            func.coalesce(func.sum(Payslip.nhf_minor), 0),
            func.coalesce(func.sum(Payslip.paye_minor), 0),
            func.count(Payslip.id),
        )
        .select_from(Payslip)
        .join(PayRun, Payslip.pay_run_id == PayRun.id)
        .join(Employee, Payslip.employee_id == Employee.id)
        .where(
            Payslip.org_id == org_id,
            PayRun.status == PayRunStatus.LOCKED,
            Payslip.period_start >= year_start,
            Payslip.period_end <= year_end,
        )
        .group_by(Payslip.employee_id, Employee.employee_number, Employee.full_name, Employee.tin)
        .order_by(Employee.employee_number)
    ).all()
    statutory_totals = _annual_statutory_totals(
        db, org_id, year_start=year_start, year_end=year_end
    )

    return [
        AnnualTaxReconciliation(
            employee_id=employee_id,
            employee_number=employee_number,
            full_name=full_name,
            tin=tin,
            tax_year=tax_year,
            total_gross_minor=int(total_gross_minor),
            total_pension_employee_minor=int(total_pension_employee_minor),
            total_nhf_minor=int(total_nhf_minor),
            total_paye_minor=int(total_paye_minor),
            payslip_count=payslip_count,
            statutory_totals=statutory_totals.get(employee_id, ()),
        )
        for (
            employee_id,
            employee_number,
            full_name,
            tin,
            total_gross_minor,
            total_pension_employee_minor,
            total_nhf_minor,
            total_paye_minor,
            payslip_count,
        ) in rows
    ]
