"""What a payroll officer needs to see before and after posting a run: who
can't be paid yet and why, and the statutory charges the run carries."""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.models import RuleVersion
from app.domain.payroll.deadlines import (
    nhf_deadline,
    nsitf_deadline,
    paye_deadline,
    pension_deadline,
)
from app.domain.payroll.nsitf import compute_nsitf
from app.models.bank_account import BankAccount
from app.models.employee import Employee
from app.models.pay_run import PayRun, PayRunStatus
from app.models.payslip import Payslip
from app.models.statutory_liability import LiabilityScheme, StatutoryLiability
from app.schemas.payroll import PayslipOut
from app.services.jurisdiction import organisation_country, rules_for_organisation, uses_engine

EMPLOYER_KINDS = frozenset({"employer_contribution", "payroll_levy"})

SCHEME_NAMES = {
    LiabilityScheme.PAYE: "PAYE (income tax)",
    LiabilityScheme.PENSION: "Pension",
    LiabilityScheme.NHF: "National Housing Fund (NHF)",
    LiabilityScheme.NSITF: "NSITF (employee compensation)",
    LiabilityScheme.ITF: "Industrial Training Fund (ITF)",
    LiabilityScheme.WHT: "Withholding tax",
}


@dataclass(frozen=True)
class ReadinessIssue:
    employee_id: uuid.UUID
    employee_number: str
    full_name: str
    code: str
    severity: str  # "blocker" stops validation; "warning" doesn't
    message: str


def pay_run_readiness(db: Session, *, pay_run: PayRun) -> list[ReadinessIssue]:
    """Each employee in the run who can't be paid yet (blocker) or whose
    payslip or payment won't reach them (warning). Validation refuses a run
    with any blocker; the warnings are for the officer to fix or accept."""
    rows = db.execute(
        select(Employee, BankAccount)
        .outerjoin(BankAccount, BankAccount.employee_id == Employee.id)
        .where(Employee.id.in_(pay_run.employee_ids))
        .order_by(Employee.employee_number)
    ).all()
    issues: list[ReadinessIssue] = []
    for employee, bank_account in rows:

        def issue(code: str, severity: str, message: str, employee: Employee = employee) -> None:
            issues.append(
                ReadinessIssue(
                    employee_id=employee.id,
                    employee_number=employee.employee_number,
                    full_name=employee.full_name,
                    code=code,
                    severity=severity,
                    message=message,
                )
            )

        if not employee.tin or not employee.tin.strip():
            issue(
                "missing_tin",
                "blocker",
                "No tax ID (TIN). Payroll can't be validated or posted until it's added.",
            )
        if not employee.email:
            issue(
                "missing_email",
                "warning",
                "No email address, so their payslip can't be emailed.",
            )
        if bank_account is None:
            issue(
                "missing_bank_account",
                "warning",
                "No bank account, so they're left out of the payment file.",
            )
        elif not bank_account.verified:
            issue(
                "unverified_bank_account",
                "warning",
                "Bank account not verified, so they're left out of the payment file.",
            )
    return issues


@dataclass(frozen=True)
class StatutoryCharge:
    scheme: str
    name: str
    state: str | None
    employee_minor: int
    employer_minor: int
    base_minor: int | None
    authority: str | None
    due_date: date | None

    @property
    def total_minor(self) -> int:
        return self.employee_minor + self.employer_minor


@dataclass(frozen=True)
class StatutoryCharges:
    basis: str  # "preview" (computed, nothing posted) or "posted" (the liabilities on record)
    charges: list[StatutoryCharge]
    note: str | None


def pay_run_statutory_charges(
    db: Session,
    *,
    org_id: uuid.UUID,
    pay_run: PayRun,
    preview: Sequence[PayslipOut] | None = None,
) -> StatutoryCharges:
    """The run's statutory charges, scheme by scheme, split into what comes
    out of employees' pay and what the employer pays on top. A posted run
    reports the liabilities it actually generated; a draft or validated run
    works them out from its preview, exactly as posting would."""
    if pay_run.status in (PayRunStatus.LOCKED, PayRunStatus.REVERSED):
        return _posted_charges(db, pay_run=pay_run)
    if preview is None:
        raise ValueError("a draft or validated run's charges are worked out from its preview")
    country = organisation_country(db, org_id)
    if uses_engine(country):
        return _engine_preview_charges(preview)
    employees = {
        employee.id: employee
        for employee in db.scalars(select(Employee).where(Employee.id.in_(pay_run.employee_ids)))
    }
    rules = rules_for_organisation(db, org_id, pay_run.period_end)
    return _nigeria_preview_charges(preview, employees=employees, rules=rules, pay_run=pay_run)


def _nigeria_preview_charges(
    payslips: Sequence[PayslipOut],
    *,
    employees: dict[uuid.UUID, Employee],
    rules: RuleVersion,
    pay_run: PayRun,
) -> StatutoryCharges:
    """Mirrors generate_liabilities_for_pay_run without writing anything."""
    charges: list[StatutoryCharge] = []
    paye_by_state: dict[str, int] = defaultdict(int)
    for payslip in payslips:
        employee = employees.get(payslip.employee_id)
        state = employee.state_of_residence if employee is not None else "Unknown"
        paye_by_state[state] += payslip.paye_minor
    for state, amount in sorted(paye_by_state.items()):
        charges.append(
            StatutoryCharge(
                scheme=LiabilityScheme.PAYE.value,
                name=SCHEME_NAMES[LiabilityScheme.PAYE],
                state=state,
                employee_minor=amount,
                employer_minor=0,
                base_minor=None,
                authority=rules.paye.authority,
                due_date=paye_deadline(pay_run.period_end, rules.paye),
            )
        )
    pensionable_base = sum(p.pensionable_pay_minor for p in payslips)
    charges.append(
        StatutoryCharge(
            scheme=LiabilityScheme.PENSION.value,
            name=SCHEME_NAMES[LiabilityScheme.PENSION],
            state=None,
            employee_minor=sum(p.pension_employee_minor for p in payslips),
            employer_minor=sum(p.pension_employer_minor for p in payslips),
            base_minor=pensionable_base,
            authority=rules.pension.authority,
            due_date=pension_deadline(pay_run.period_end, rules.pension),
        )
    )
    charges.append(
        StatutoryCharge(
            scheme=LiabilityScheme.NHF.value,
            name=SCHEME_NAMES[LiabilityScheme.NHF],
            state=None,
            employee_minor=sum(p.nhf_minor for p in payslips),
            employer_minor=0,
            base_minor=sum(
                int(p.derivation.get("inputs", {}).get("basic_minor", 0)) for p in payslips
            ),
            authority=rules.nhf.authority,
            due_date=nhf_deadline(pay_run.period_end, rules.nhf),
        )
    )
    charges.append(
        StatutoryCharge(
            scheme=LiabilityScheme.NSITF.value,
            name=SCHEME_NAMES[LiabilityScheme.NSITF],
            state=None,
            employee_minor=0,
            employer_minor=compute_nsitf(pensionable_base, rules.nsitf),
            base_minor=pensionable_base,
            authority=rules.nsitf.authority,
            due_date=nsitf_deadline(pay_run.period_end, rules.nsitf),
        )
    )
    return StatutoryCharges(
        basis="preview",
        charges=charges,
        note="ITF is charged once a year on the year's payroll, not on each run.",
    )


def _engine_preview_charges(payslips: Sequence[PayslipOut]) -> StatutoryCharges:
    employee: dict[str, int] = defaultdict(int)
    employer: dict[str, int] = defaultdict(int)
    base: dict[str, int] = defaultdict(int)
    meta: dict[str, tuple[str, str, date]] = {}
    for payslip in payslips:
        for line in payslip.statutory_lines:
            meta.setdefault(line.code, (line.name, line.authority, line.due_date))
            if line.kind in EMPLOYER_KINDS:
                employer[line.code] += line.amount_minor
            else:
                employee[line.code] += line.amount_minor
            base[line.code] += line.base_minor
    charges = [
        StatutoryCharge(
            scheme=code,
            name=name,
            state=None,
            employee_minor=employee.get(code, 0),
            employer_minor=employer.get(code, 0),
            base_minor=base.get(code),
            authority=authority,
            due_date=due_date,
        )
        for code, (name, authority, due_date) in meta.items()
    ]
    return StatutoryCharges(
        basis="preview",
        charges=charges,
        note="Levies charged on the whole payroll are worked out when the run is posted.",
    )


def _posted_charges(db: Session, *, pay_run: PayRun) -> StatutoryCharges:
    liabilities = db.scalars(
        select(StatutoryLiability)
        .where(StatutoryLiability.pay_run_id == pay_run.id)
        .order_by(StatutoryLiability.scheme, StatutoryLiability.state)
    ).all()
    payslips = db.scalars(select(Payslip).where(Payslip.pay_run_id == pay_run.id)).all()
    pension_employee = sum(p.pension_employee_minor for p in payslips)
    pension_employer = sum(p.pension_employer_minor for p in payslips)
    lines_by_code: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for payslip in payslips:
        for line in payslip.statutory_lines:
            lines_by_code[line.code].append((line.kind, line.amount_minor, line.name))

    charges: list[StatutoryCharge] = []
    for liability in liabilities:
        employee_minor, employer_minor = _split(
            liability, pension_employee, pension_employer, lines_by_code
        )
        if liability.scheme is LiabilityScheme.COUNTRY:
            codes = (liability.line_code or "").split("+")
            names = sorted({name for code in codes for _, _, name in lines_by_code.get(code, [])})
            name = " + ".join(names) if names else (liability.line_code or "Statutory charge")
            scheme = liability.line_code or LiabilityScheme.COUNTRY.value
        else:
            name = SCHEME_NAMES.get(liability.scheme, liability.scheme.value.upper())
            scheme = liability.scheme.value
        charges.append(
            StatutoryCharge(
                scheme=scheme,
                name=name,
                state=liability.state,
                employee_minor=employee_minor,
                employer_minor=employer_minor,
                base_minor=liability.base_minor,
                authority=liability.authority,
                due_date=liability.due_date,
            )
        )
    note = None
    if pay_run.status is PayRunStatus.REVERSED:
        note = "This run was reversed; only liabilities already filed or remitted remain."
    return StatutoryCharges(basis="posted", charges=charges, note=note)


def _split(
    liability: StatutoryLiability,
    pension_employee: int,
    pension_employer: int,
    lines_by_code: dict[str, list[tuple[str, int, str]]],
) -> tuple[int, int]:
    """(employee, employer) shares of one liability's amount."""
    if liability.scheme in (LiabilityScheme.PAYE, LiabilityScheme.NHF):
        return liability.amount_minor, 0
    if liability.scheme in (LiabilityScheme.NSITF, LiabilityScheme.ITF):
        return 0, liability.amount_minor
    if liability.scheme is LiabilityScheme.PENSION:
        if pension_employee + pension_employer == liability.amount_minor:
            return pension_employee, pension_employer
        return 0, liability.amount_minor
    if liability.scheme is LiabilityScheme.COUNTRY:
        codes = (liability.line_code or "").split("+")
        employee = sum(
            amount
            for code in codes
            for kind, amount, _ in lines_by_code.get(code, [])
            if kind not in EMPLOYER_KINDS
        )
        employee = min(employee, liability.amount_minor)
        return employee, liability.amount_minor - employee
    return liability.amount_minor, 0
