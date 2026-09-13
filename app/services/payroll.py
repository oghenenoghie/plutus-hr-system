import uuid
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.compliance.resolver import resolve_rule_version
from app.domain.payroll.loans import next_installment_amount
from app.domain.payroll.payslip import compute_payslip
from app.domain.payroll.postings import build_payslip_postings
from app.domain.payroll.tin import ensure_tin_present
from app.models.employee import Employee
from app.models.leave_encashment import LeaveEncashmentRequest, LeaveEncashmentStatus
from app.models.ledger import LedgerEntry
from app.models.loan import Loan, LoanRepayment, LoanStatus
from app.models.overtime import Overtime, OvertimeStatus
from app.models.pay_run import PayRun, PayRunStatus
from app.models.payslip import Payslip
from app.services.statutory_liability import generate_liabilities_for_pay_run

# Single-country assumption for this phase — Nigeria is the only rule set
# that exists (app/compliance/versions/). Revisit once Organisation carries
# a country once a second country's rule set lands (see the skill's
# pan-African guardrail against hardcoding Nigeria assumptions elsewhere).
_COUNTRY = "NG"


def tax_year_start(period_end: date) -> date:
    return date(period_end.year, 1, 1)


def cumulative_totals_before(
    db: Session, employee_id: uuid.UUID, year_start: date
) -> tuple[int, int, int, int, int]:
    """Shared by process_employee_payslip and the what-if simulator
    (app/services/simulation.py) — both need the same real-history figures
    to seed cumulative-annual PAYE, one persisting the result and one not.

    Only payslips under a LOCKED pay run count: a reversed run's payslip
    must not contribute to (or double-count in) year-to-date PAYE — the
    same bug class the pay-run lock lifecycle is otherwise built to avoid.
    """
    prior = db.scalars(
        select(Payslip)
        .join(PayRun, Payslip.pay_run_id == PayRun.id)
        .where(Payslip.employee_id == employee_id)
        .where(Payslip.period_end >= year_start)
        .where(PayRun.status == PayRunStatus.LOCKED)
        .order_by(Payslip.period_end)
    ).all()
    return (
        sum(p.gross_minor for p in prior),
        sum(p.pension_employee_minor for p in prior),
        sum(p.nhf_minor for p in prior),
        sum(p.paye_minor for p in prior),
        len(prior),
    )


def active_loan(db: Session, employee_id: uuid.UUID) -> Loan | None:
    """At most one active loan per employee — a service-level rule, not a
    DB constraint (a second loan can't be taken out until the first is
    paid off or cancelled)."""
    return db.scalar(
        select(Loan).where(Loan.employee_id == employee_id, Loan.status == LoanStatus.ACTIVE)
    )


def outstanding_loan_balance(db: Session, loan: Loan) -> int:
    # Postgres SUM() over a bigint column returns numeric, which comes back
    # as a Decimal — cast to int immediately so money stays integer minor
    # units throughout, never Decimal (and stays JSON-serialisable).
    #
    # LoanRepayment is append-only (can't be deleted when a pay run is
    # reversed), so a reversed run's repayment is excluded here by joining
    # through to the pay run's status instead — same reasoning as
    # cumulative_totals_before. The outer joins keep a repayment with no
    # traceable payslip/pay-run counted rather than silently dropped.
    repaid = db.scalar(
        select(func.coalesce(func.sum(LoanRepayment.amount_minor), 0))
        .select_from(LoanRepayment)
        .outerjoin(Payslip, LoanRepayment.payslip_id == Payslip.id)
        .outerjoin(PayRun, Payslip.pay_run_id == PayRun.id)
        .where(
            LoanRepayment.loan_id == loan.id,
            (PayRun.status != PayRunStatus.REVERSED) | (PayRun.id.is_(None)),
        )
    )
    return loan.principal_minor - int(repaid or 0)


def process_employee_payslip(
    db: Session,
    *,
    org_id: uuid.UUID,
    pay_run: PayRun,
    employee: Employee,
    extra_other_earnings_minor: int = 0,
    full_loan_recovery: bool = False,
) -> Payslip:
    """Compute and persist one employee's payslip for a pay run, plus its
    balanced ledger postings and any loan repayment. Raises MissingTinError
    (never silently skips) if the employee has no valid TIN — the caller's
    transaction (a tenant_session) rolls back on that exception, so no
    partial run persists.

    extra_other_earnings_minor lets a caller (final settlement) add taxable
    one-off amounts like gratuity or leave payout to this period without
    mutating the employee's stored recurring pay. full_loan_recovery
    deducts the entire outstanding balance instead of the scheduled
    installment — used to close out a loan at exit.
    """
    ensure_tin_present(employee.tin)
    if extra_other_earnings_minor < 0:
        raise ValueError("extra_other_earnings_minor must not be negative")

    rules = resolve_rule_version(_COUNTRY, pay_run.period_end)
    year_start = tax_year_start(pay_run.period_end)
    (
        cumulative_gross_before,
        cumulative_pension_employee_before,
        cumulative_nhf_before,
        cumulative_paye_before,
        periods_elapsed_before,
    ) = cumulative_totals_before(db, employee.id, year_start)

    loan = active_loan(db, employee.id)
    loan_deduction_minor = 0
    outstanding_before_minor = 0
    if loan is not None:
        outstanding_before_minor = outstanding_loan_balance(db, loan)
        if outstanding_before_minor > 0:
            scheduled = outstanding_before_minor if full_loan_recovery else loan.installment_minor
            loan_deduction_minor = next_installment_amount(outstanding_before_minor, scheduled)

    # Every approved-but-unpaid overtime entry gets swept into the next pay
    # run automatically, same "request -> approval -> next-pay-run payout"
    # shape as the loan deduction above. Taxable but never pensionable
    # (nigeria-statutory-compliance.md §6 — pensionable pay is
    # basic+housing+transport only) — folded in as other_earnings, exactly
    # like final settlement's gratuity/leave payout.
    pending_overtime = list(
        db.scalars(
            select(Overtime).where(
                Overtime.employee_id == employee.id,
                Overtime.status == OvertimeStatus.APPROVED,
                Overtime.pay_run_id.is_(None),
            )
        )
    )
    overtime_minor = sum(entry.amount_minor for entry in pending_overtime)

    # Same automatic pickup for approved-but-unpaid leave encashment —
    # taxable extra earnings, same as final settlement's leave payout.
    pending_encashments = list(
        db.scalars(
            select(LeaveEncashmentRequest).where(
                LeaveEncashmentRequest.employee_id == employee.id,
                LeaveEncashmentRequest.status == LeaveEncashmentStatus.APPROVED,
                LeaveEncashmentRequest.pay_run_id.is_(None),
            )
        )
    )
    leave_encashment_minor = sum(entry.amount_minor for entry in pending_encashments)

    other_earnings_minor = (
        employee.other_earnings_minor
        + extra_other_earnings_minor
        + overtime_minor
        + leave_encashment_minor
    )

    computation = compute_payslip(
        basic_minor=employee.basic_minor,
        housing_minor=employee.housing_minor,
        transport_minor=employee.transport_minor,
        other_earnings_minor=other_earnings_minor,
        annual_rent_paid_minor=employee.annual_rent_paid_minor,
        periods_elapsed_this_year=periods_elapsed_before + 1,
        frequency=employee.pay_frequency,
        cumulative_gross_before_minor=cumulative_gross_before,
        cumulative_pension_employee_before_minor=cumulative_pension_employee_before,
        cumulative_nhf_before_minor=cumulative_nhf_before,
        cumulative_paye_withheld_before_minor=cumulative_paye_before,
        rules=rules,
        loan_deduction_minor=loan_deduction_minor,
    )

    payslip = Payslip(
        org_id=org_id,
        pay_run_id=pay_run.id,
        employee_id=employee.id,
        period_start=pay_run.period_start,
        period_end=pay_run.period_end,
        gross_minor=computation.gross_minor,
        pensionable_pay_minor=computation.pensionable_pay_minor,
        pension_employee_minor=computation.pension_employee_minor,
        pension_employer_minor=computation.pension_employer_minor,
        nhf_minor=computation.nhf_minor,
        paye_minor=computation.paye_minor,
        net_minor=computation.net_pay_minor,
        cumulative_chargeable_income_minor=computation.cumulative_chargeable_income_minor,
        rule_version_id=rules.id,
        derivation={
            "inputs": {
                "basic_minor": employee.basic_minor,
                "housing_minor": employee.housing_minor,
                "transport_minor": employee.transport_minor,
                "other_earnings_minor": other_earnings_minor,
                "extra_other_earnings_minor": extra_other_earnings_minor,
                "annual_rent_paid_minor": employee.annual_rent_paid_minor,
                "periods_elapsed_this_year": periods_elapsed_before + 1,
                "frequency": employee.pay_frequency.value,
                "cumulative_gross_before_minor": cumulative_gross_before,
                "cumulative_pension_employee_before_minor": cumulative_pension_employee_before,
                "cumulative_nhf_before_minor": cumulative_nhf_before,
                "cumulative_paye_withheld_before_minor": cumulative_paye_before,
                "loan_id": str(loan.id) if loan is not None else None,
                "outstanding_loan_before_minor": outstanding_before_minor,
                "full_loan_recovery": full_loan_recovery,
                "overtime_minor": overtime_minor,
                "overtime_entry_ids": [str(entry.id) for entry in pending_overtime],
                "leave_encashment_minor": leave_encashment_minor,
                "leave_encashment_request_ids": [str(entry.id) for entry in pending_encashments],
                "rule_version_id": rules.id,
            },
            "outputs": asdict(computation),
        },
    )
    db.add(payslip)
    db.flush()  # need payslip.id for the LoanRepayment/Overtime FKs below

    for entry in pending_overtime:
        entry.status = OvertimeStatus.PAID
        entry.pay_run_id = pay_run.id
        db.add(entry)

    for encashment in pending_encashments:
        encashment.status = LeaveEncashmentStatus.PAID
        encashment.pay_run_id = pay_run.id
        db.add(encashment)

    if loan is not None and loan_deduction_minor > 0:
        db.add(
            LoanRepayment(
                org_id=org_id,
                loan_id=loan.id,
                payslip_id=payslip.id,
                amount_minor=loan_deduction_minor,
            )
        )
        if outstanding_before_minor - loan_deduction_minor <= 0:
            loan.status = LoanStatus.PAID_OFF
            db.add(loan)
        # The session factory disables autoflush, so a caller querying the
        # repayment (e.g. final settlement summing recovered loan amounts)
        # right after this call wouldn't otherwise see it yet.
        db.flush()

    journal_entry_id = uuid.uuid4()
    for posting in build_payslip_postings(computation):
        db.add(
            LedgerEntry(
                org_id=org_id,
                journal_entry_id=journal_entry_id,
                pay_run_id=pay_run.id,
                employee_id=employee.id,
                account=posting.account,
                debit_minor=posting.debit_minor,
                credit_minor=posting.credit_minor,
                description=f"payslip for {employee.employee_number}, {pay_run.period_start}–{pay_run.period_end}",
            )
        )

    return payslip


def run_pay_run(
    db: Session, *, org_id: uuid.UUID, pay_run: PayRun, employees: Sequence[Employee]
) -> PayRun:
    """Process every employee in a pay run and lock it. The whole run is one
    transaction (the caller's tenant_session): a single missing TIN or
    computation error rolls back every payslip and ledger entry the run
    would otherwise have created — never a partially-processed run.

    This is the one place payslips/ledger entries are actually written —
    both are append-only (see their model docstrings), so nothing about a
    pay run is genuinely permanent before this runs. The draft/validate
    steps (app/services/pay_run_lifecycle.py) only ever dry-run compute via
    simulate_payslip; lock_pay_run is what calls this for real.
    """
    payslips = [
        process_employee_payslip(db, org_id=org_id, pay_run=pay_run, employee=employee)
        for employee in employees
    ]

    pay_run.employee_count = len(payslips)
    pay_run.gross_minor = sum(p.gross_minor for p in payslips)
    pay_run.net_minor = sum(p.net_minor for p in payslips)
    pay_run.rule_version_id = payslips[0].rule_version_id if payslips else None
    pay_run.status = PayRunStatus.LOCKED
    pay_run.locked_at = datetime.now(UTC)
    db.add(pay_run)

    if payslips:
        rules = resolve_rule_version(_COUNTRY, pay_run.period_end)
        employees_by_id = {employee.id: employee for employee in employees}
        generate_liabilities_for_pay_run(
            db,
            org_id=org_id,
            pay_run=pay_run,
            payslips=payslips,
            employees_by_id=employees_by_id,
            rules=rules,
        )

    return pay_run
