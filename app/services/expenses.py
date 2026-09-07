import uuid
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.expense import Expense, ExpenseStatus


def submit_expense(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    category: str,
    description: str,
    amount_minor: int,
    expense_date: date,
) -> Expense:
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")

    expense = Expense(
        org_id=org_id,
        employee_id=employee_id,
        category=category,
        description=description,
        amount_minor=amount_minor,
        expense_date=expense_date,
    )
    db.add(expense)
    db.flush()
    return expense


def decide_expense(db: Session, expense: Expense, *, approve: bool) -> Expense:
    if expense.status != ExpenseStatus.PENDING:
        raise ValueError(f"expense is {expense.status.value}, not pending")

    expense.status = ExpenseStatus.APPROVED if approve else ExpenseStatus.REJECTED
    expense.decided_at = datetime.now(UTC)
    db.add(expense)
    return expense


def mark_expense_reimbursed(db: Session, expense: Expense) -> Expense:
    """A separate step from approval — approval decides whether the claim is
    valid, reimbursement records that money actually moved (e.g. via the
    next pay run or an out-of-cycle transfer), which can lag behind."""
    if expense.status != ExpenseStatus.APPROVED:
        raise ValueError(f"expense is {expense.status.value}, not approved")

    expense.status = ExpenseStatus.REIMBURSED
    expense.reimbursed_at = datetime.now(UTC)
    db.add(expense)
    return expense
