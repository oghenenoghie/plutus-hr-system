import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.compliance.resolver import resolve_rule_version
from app.models.employee import Employee, LifecycleState
from app.models.final_settlement import FinalSettlement
from app.models.loan import LoanRepayment
from app.models.pay_run import PayRun, PayRunStatus
from app.services.payroll import process_employee_payslip
from app.services.statutory_liability import generate_liabilities_for_pay_run

# Same single-country assumption as app.services.payroll — Nigeria is the
# only rule set that exists yet.
_COUNTRY = "NG"


def process_final_settlement(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee: Employee,
    termination_date: date,
    gratuity_minor: int,
    leave_days_paid_out: int,
    leave_payout_minor: int,
) -> FinalSettlement:
    """Exit payroll. Leave payout and gratuity are taxed through the same
    cumulative-PAYE machinery as a normal payslip — gratuity is taxable
    per nigeria-statutory-compliance.md §1 — as this period's extra
    taxable earnings, and any outstanding loan is recovered in full
    (full_loan_recovery) rather than at its usual installment.

    leave_days_paid_out, leave_payout_minor and gratuity_minor are the
    caller's own figures: converting unused leave days or a gratuity
    award into naira is an employer policy question with no statutory
    formula in the reference to encode here.
    """
    if gratuity_minor < 0 or leave_payout_minor < 0:
        raise ValueError("gratuity_minor and leave_payout_minor must not be negative")
    if leave_days_paid_out < 0:
        raise ValueError("leave_days_paid_out must not be negative")

    pay_run = PayRun(
        org_id=org_id,
        period_start=termination_date,
        period_end=termination_date,
        frequency=employee.pay_frequency,
        employee_ids=[employee.id],
        status=PayRunStatus.DRAFT,
    )
    db.add(pay_run)
    db.flush()

    payslip = process_employee_payslip(
        db,
        org_id=org_id,
        pay_run=pay_run,
        employee=employee,
        extra_other_earnings_minor=gratuity_minor + leave_payout_minor,
        full_loan_recovery=True,
    )

    pay_run.employee_count = 1
    pay_run.gross_minor = payslip.gross_minor
    pay_run.net_minor = payslip.net_minor
    pay_run.rule_version_id = payslip.rule_version_id
    # Final settlement is deliberately excluded from the draft/validate/lock
    # gate (it's an off-cycle, one-employee exit run computed and finalized
    # in a single call) — it locks immediately rather than sitting in draft.
    pay_run.status = PayRunStatus.LOCKED
    pay_run.locked_at = datetime.now(UTC)
    db.add(pay_run)

    # A settlement's PAYE/pension/NHF are real statutory liabilities too —
    # generate them the same way a normal run_pay_run would, since this
    # path calls process_employee_payslip directly rather than run_pay_run.
    rules = resolve_rule_version(_COUNTRY, pay_run.period_end)
    generate_liabilities_for_pay_run(
        db,
        org_id=org_id,
        pay_run=pay_run,
        payslips=[payslip],
        employees_by_id={employee.id: employee},
        rules=rules,
    )

    # Cast to int: Postgres SUM() over bigint returns numeric (-> Decimal).
    outstanding_loan_recovered_minor = int(
        db.scalar(
            select(func.coalesce(func.sum(LoanRepayment.amount_minor), 0)).where(
                LoanRepayment.payslip_id == payslip.id
            )
        )
        or 0
    )

    employee.lifecycle_state = LifecycleState.TERMINATED
    db.add(employee)

    settlement = FinalSettlement(
        org_id=org_id,
        employee_id=employee.id,
        payslip_id=payslip.id,
        termination_date=termination_date,
        leave_days_paid_out=leave_days_paid_out,
        leave_payout_minor=leave_payout_minor,
        gratuity_minor=gratuity_minor,
        outstanding_loan_recovered_minor=outstanding_loan_recovered_minor,
        net_settlement_minor=payslip.net_minor,
    )
    db.add(settlement)
    db.flush()  # populate settlement.id for callers that need it before commit
    return settlement
