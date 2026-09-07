import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.domain.payroll.loans import compute_equal_installments
from app.models.loan import Loan, LoanStatus
from app.services.payroll import active_loan


class ActiveLoanExistsError(Exception):
    """Raised when an employee already has an active loan — at most one at
    a time (see app.services.payroll.active_loan)."""


def request_loan(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    principal_minor: int,
    num_installments: int,
    start_date: date,
) -> Loan:
    if active_loan(db, employee_id) is not None:
        raise ActiveLoanExistsError("employee already has an active loan")

    # The regular per-period deduction is the equal-installment base amount;
    # the final installment shrinks to whatever's actually left via
    # next_installment_amount, so the rounding remainder is absorbed there
    # instead of front-loaded onto the first installment.
    installment_minor = compute_equal_installments(principal_minor, num_installments)[0]

    loan = Loan(
        org_id=org_id,
        employee_id=employee_id,
        principal_minor=principal_minor,
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
