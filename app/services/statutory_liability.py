import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import cast

from sqlalchemy.orm import Session

from app.compliance.models import RuleVersion
from app.domain.accounting.posting_rules import (
    CASH_ACCOUNT,
    PostingLine,
    build_statutory_remittance_postings,
)
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
from app.models.journal_entry import JournalSourceType
from app.models.pay_run import PayRun
from app.models.payslip import Payslip
from app.models.statutory_liability import LiabilityScheme, LiabilityStatus, StatutoryLiability
from app.services.accounting_settings import remittance_posting_enabled
from app.services.posting import lagos_date, post_journal


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
        description = f"NSITF for pay run {pay_run.period_start}–{pay_run.period_end}"
        post_journal(
            db,
            org_id=org_id,
            entry_date=pay_run.period_end,
            source_type=JournalSourceType.STATUTORY_ACCRUAL,
            source_id=pay_run.id,
            source_event="nsitf.accrued",
            description=description,
            lines=[
                PostingLine(
                    "payroll_expense_nsitf",
                    debit_minor=nsitf_amount,
                    description=description,
                    pay_run_id=pay_run.id,
                ),
                PostingLine(
                    "nsitf_payable",
                    credit_minor=nsitf_amount,
                    description=description,
                    pay_run_id=pay_run.id,
                ),
            ],
            # Same reason as the payslip postings: this has always posted
            # without consulting the chart (audit P3).
            validate_chart=False,
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


def liability_label(liability: StatutoryLiability) -> str:
    """The scheme's name, or for a country's own obligation its line codes."""
    if liability.scheme is LiabilityScheme.COUNTRY and liability.line_code:
        return liability.line_code
    return liability.scheme.value.upper()


def _remittance_description(liability: StatutoryLiability) -> str:
    where = f" ({liability.state})" if liability.state else ""
    return (
        f"{liability_label(liability)} remittance to {liability.authority}{where}, "
        f"{liability.period_start}–{liability.period_end}"
    )


def _remittance_lines(
    liability: StatutoryLiability, description: str
) -> tuple[PostingLine, ...] | None:
    if liability.scheme is LiabilityScheme.COUNTRY:
        if not liability.liability_account:
            raise ValueError("a country liability needs its payable account")
        return (
            PostingLine(
                liability.liability_account,
                debit_minor=liability.amount_minor,
                description=description,
            ),
            PostingLine(CASH_ACCOUNT, credit_minor=liability.amount_minor, description=description),
        )
    return build_statutory_remittance_postings(
        liability.scheme.value, liability.amount_minor, description=description
    )


def mark_liability_remitted(
    db: Session,
    liability: StatutoryLiability,
    *,
    reference: str | None = None,
    actor_account_id: uuid.UUID | None = None,
) -> StatutoryLiability:
    """Records that the money has gone to the authority. When the org has
    switched remittance posting on (AccountingSettings), also posts the
    journal that clears the liability — Dr <scheme>_payable / Cr cash — and
    links it through remittance_journal_id.

    The journal is posted before any field on the liability changes, so a
    posting that is rejected (an account missing from the chart, say) leaves
    the liability exactly as it was.
    """
    if liability.status == LiabilityStatus.REMITTED:
        raise ValueError("liability is already remitted")

    remitted_at = datetime.now(UTC)
    remittance_journal_id: uuid.UUID | None = None
    if remittance_posting_enabled(db, org_id=liability.org_id):
        description = _remittance_description(liability)
        lines = _remittance_lines(liability, description)
        if lines is not None:
            journal = post_journal(
                db,
                org_id=liability.org_id,
                entry_date=lagos_date(remitted_at),
                source_type=JournalSourceType.STATUTORY_REMITTANCE,
                source_id=liability.id,
                source_event="liability.remitted",
                description=description,
                lines=lines,
                reference=reference,
                actor_account_id=actor_account_id,
            )
            remittance_journal_id = journal.id

    liability.status = LiabilityStatus.REMITTED
    liability.remitted_at = remitted_at
    liability.remittance_reference = reference
    liability.remittance_journal_id = remittance_journal_id
    db.add(liability)
    return liability
