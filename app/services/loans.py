import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.domain.payroll.frequency import periods_per_year
from app.domain.payroll.loans import (
    apply_flat_interest_minor,
    check_loan_eligibility,
    compute_equal_installments,
)
from app.models.employee import Employee
from app.models.loan import Loan, LoanStatus
from app.services.payroll import active_loan


class ActiveLoanExistsError(Exception):
    """Raised when an employee already has an active loan — at most one at
    a time (see app.services.payroll.active_loan)."""


def request_loan(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee: Employee,
    principal_minor: int,
    num_installments: int,
    start_date: date,
    interest_rate_bps: int = 0,
) -> Loan:
    if active_loan(db, employee.id) is not None:
        raise ActiveLoanExistsError("employee already has an active loan")

    period_pay_minor = employee.basic_minor + employee.housing_minor + employee.transport_minor
    monthly_pay_minor = period_pay_minor * periods_per_year(employee.pay_frequency) // 12
    check_loan_eligibility(
        hire_date=employee.date_of_joining,
        start_date=start_date,
        principal_minor=principal_minor,
        monthly_pay_minor=monthly_pay_minor,
    )

    total_repayable_minor = apply_flat_interest_minor(principal_minor, interest_rate_bps)
    # The regular per-period deduction is the equal-installment base amount;
    # the final installment shrinks to whatever's actually left via
    # next_installment_amount, so the rounding remainder is absorbed there
    # instead of front-loaded onto the first installment.
    installment_minor = compute_equal_installments(total_repayable_minor, num_installments)[0]

    loan = Loan(
        org_id=org_id,
        employee_id=employee.id,
        principal_minor=principal_minor,
        interest_rate_bps=interest_rate_bps,
        total_repayable_minor=total_repayable_minor,
        num_installments=num_installments,
        installment_minor=installment_minor,
        start_date=start_date,
    )
    db.add(loan)
    db.flush()
    return loan


def cancel_loan(db: Session, loan: Loan) -> Loan:
    if loan.status != LoanStatus.ACTIVE:
        raise ValueError(f"loan is {loan.status.value}, not active")
    loan.status = LoanStatus.CANCELLED
    db.add(loan)
    return loan
