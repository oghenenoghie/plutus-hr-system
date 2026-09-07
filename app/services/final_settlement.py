import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.employee import Employee, LifecycleState
from app.models.final_settlement import FinalSettlement
from app.models.loan import LoanRepayment
from app.models.pay_run import PayRun, PayRunStatus
from app.services.payroll import process_employee_payslip


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
    pay_run.status = PayRunStatus.COMPLETED
    db.add(pay_run)

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
