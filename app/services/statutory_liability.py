import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import cast

from sqlalchemy.orm import Session

from app.compliance.models import RuleVersion
from app.domain.payroll.deadlines import (
    itf_deadline,
    nhf_deadline,
    nsitf_deadline,
    paye_deadline,
    pension_deadline,
)
from app.domain.payroll.itf import compute_itf
from app.domain.payroll.nsitf import compute_nsitf
from app.models.employee import Employee
from app.models.ledger import LedgerEntry
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.statutory_liability import LiabilityScheme, LiabilityStatus, StatutoryLiability


def _basic_minor(payslip: Payslip) -> int:
    """basic_minor isn't its own Payslip column (only pensionable_pay_minor,
    the basic+housing+transport sum, is) — recovered from the stored
    derivation trail rather than re-deriving it by dividing NHF back out,
    which would introduce rounding error."""
    inputs = cast(dict[str, object], payslip.derivation["inputs"])
    return cast(int, inputs["basic_minor"])


def generate_liabilities_for_pay_run(
    db: Session,
    *,
    org_id: uuid.UUID,
    pay_run: PayRun,
    payslips: list[Payslip],
    employees_by_id: dict[uuid.UUID, Employee],
    rules: RuleVersion,
) -> list[StatutoryLiability]:
    """One row per scheme for this pay run — PAYE split further by employee
    state of residence, since each state's IRS collects separately (§9).
    NSITF also gets a ledger posting here (Dr payroll_expense_nsitf / Cr
    nsitf_payable): PAYE/pension/NHF are already posted per-payslip in
    process_employee_payslip, but NSITF is a pay-run-level, employer-only
    figure with no natural per-employee posting.
    """
    liabilities: list[StatutoryLiability] = []

    paye_by_state: dict[str, int] = defaultdict(int)
    for payslip in payslips:
        if payslip.paye_minor > 0:
            employee = employees_by_id[payslip.employee_id]
            paye_by_state[employee.state_of_residence] += payslip.paye_minor

    for state, amount in paye_by_state.items():
        liabilities.append(
            StatutoryLiability(
                org_id=org_id,
                pay_run_id=pay_run.id,
                scheme=LiabilityScheme.PAYE,
                state=state,
                authority=rules.paye.authority,
                base_minor=amount,  # progressive — no single rate/base pair to report
                amount_minor=amount,
                period_start=pay_run.period_start,
                period_end=pay_run.period_end,
                due_date=paye_deadline(pay_run.period_end, rules.paye),
            )
        )

    pensionable_base = sum(p.pensionable_pay_minor for p in payslips)
    total_pension = sum(p.pension_employee_minor + p.pension_employer_minor for p in payslips)
    if total_pension:
        liabilities.append(
            StatutoryLiability(
                org_id=org_id,
                pay_run_id=pay_run.id,
                scheme=LiabilityScheme.PENSION,
                authority=rules.pension.authority,
                base_minor=pensionable_base,
                amount_minor=total_pension,
                period_start=pay_run.period_start,
                period_end=pay_run.period_end,
                due_date=pension_deadline(pay_run.period_end, rules.pension),
            )
        )

    basic_base = sum(_basic_minor(p) for p in payslips)
    total_nhf = sum(p.nhf_minor for p in payslips)
    if total_nhf:
        liabilities.append(
            StatutoryLiability(
                org_id=org_id,
                pay_run_id=pay_run.id,
                scheme=LiabilityScheme.NHF,
                authority=rules.nhf.authority,
                base_minor=basic_base,
                amount_minor=total_nhf,
                period_start=pay_run.period_start,
                period_end=pay_run.period_end,
                due_date=nhf_deadline(pay_run.period_end, rules.nhf),
            )
        )

    # §6: NSITF's base is total payroll excluding pension/bonus/overtime/
    # 13th-month — exactly pensionable_pay_minor, since that's basic +
    # housing + transport only and never includes other_earnings.
    nsitf_amount = compute_nsitf(pensionable_base, rules.nsitf)
    if nsitf_amount:
        liabilities.append(
            StatutoryLiability(
                org_id=org_id,
                pay_run_id=pay_run.id,
                scheme=LiabilityScheme.NSITF,
                authority=rules.nsitf.authority,
                base_minor=pensionable_base,
                amount_minor=nsitf_amount,
                period_start=pay_run.period_start,
                period_end=pay_run.period_end,
                due_date=nsitf_deadline(pay_run.period_end, rules.nsitf),
            )
        )
        journal_entry_id = uuid.uuid4()
        db.add(
            LedgerEntry(
                org_id=org_id,
                journal_entry_id=journal_entry_id,
                pay_run_id=pay_run.id,
                account="payroll_expense_nsitf",
                debit_minor=nsitf_amount,
                credit_minor=0,
                description=f"NSITF for pay run {pay_run.period_start}–{pay_run.period_end}",
            )
        )
        db.add(
            LedgerEntry(
                org_id=org_id,
                journal_entry_id=journal_entry_id,
                pay_run_id=pay_run.id,
                account="nsitf_payable",
                debit_minor=0,
                credit_minor=nsitf_amount,
                description=f"NSITF for pay run {pay_run.period_start}–{pay_run.period_end}",
            )
        )

    for liability in liabilities:
        db.add(liability)
    return liabilities


def generate_annual_itf_liability(
    db: Session,
    *,
    org_id: uuid.UUID,
    year: int,
    annual_payroll_minor: int,
    rule: RuleVersion,
    qualifies: bool,
) -> StatutoryLiability | None:
    """ITF is annual, not tied to any single pay run — the caller supplies
    the qualification decision (§7's headcount/turnover test is unconfirmed
    against a primary source; see ItfRule's docstring) and the total annual
    payroll base themselves."""
    amount = compute_itf(annual_payroll_minor, rule.itf, qualifies=qualifies)
    if amount <= 0:
        return None
    liability = StatutoryLiability(
        org_id=org_id,
        pay_run_id=None,
        scheme=LiabilityScheme.ITF,
        authority=rule.itf.authority,
        base_minor=annual_payroll_minor,
        amount_minor=amount,
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 31),
        due_date=itf_deadline(year, rule.itf),
    )
    db.add(liability)
    return liability


def mark_liability_filed(db: Session, liability: StatutoryLiability) -> StatutoryLiability:
    if liability.status != LiabilityStatus.PENDING:
        raise ValueError(f"liability is {liability.status.value}, not pending")
    liability.status = LiabilityStatus.FILED
    liability.filed_at = datetime.now(UTC)
    db.add(liability)
    return liability


def mark_liability_remitted(
    db: Session, liability: StatutoryLiability, *, reference: str | None = None
) -> StatutoryLiability:
    if liability.status == LiabilityStatus.REMITTED:
        raise ValueError("liability is already remitted")
    liability.status = LiabilityStatus.REMITTED
    liability.remitted_at = datetime.now(UTC)
    liability.remittance_reference = reference
    db.add(liability)
    return liability
