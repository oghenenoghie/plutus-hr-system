import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.expense import Expense, ExpensePaymentMethod, ExpensePolicyLimit, ExpenseStatus


class ExpensePolicyLimitExceededError(ValueError):
    """Raised when a claim's amount exceeds its category's configured
    policy limit — always a 400, never a 500."""


def _policy_limit_for_category(
    db: Session, *, org_id: uuid.UUID, category: str
) -> ExpensePolicyLimit | None:
    return db.scalar(
        select(ExpensePolicyLimit).where(
            ExpensePolicyLimit.org_id == org_id, ExpensePolicyLimit.category == category
        )
    )


def submit_expense(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    category: str,
    description: str,
    amount_minor: int,
    expense_date: date,
    receipt_url: str | None = None,
    payment_method: ExpensePaymentMethod = ExpensePaymentMethod.REIMBURSEMENT,
) -> Expense:
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")

    limit = _policy_limit_for_category(db, org_id=org_id, category=category)
    if limit is not None and amount_minor > limit.max_amount_minor:
        raise ExpensePolicyLimitExceededError(
            f"{category} claims are capped at {limit.max_amount_minor} minor units by policy"
        )

    expense = Expense(
        org_id=org_id,
        employee_id=employee_id,
        category=category,
        description=description,
        amount_minor=amount_minor,
        expense_date=expense_date,
        receipt_url=receipt_url,
        payment_method=payment_method,
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


def set_expense_policy_limit(
    db: Session, *, org_id: uuid.UUID, category: str, max_amount_minor: int
) -> ExpensePolicyLimit:
    if max_amount_minor <= 0:
        raise ValueError("max_amount_minor must be positive")

    existing = _policy_limit_for_category(db, org_id=org_id, category=category)
    if existing is not None:
        existing.max_amount_minor = max_amount_minor
        db.add(existing)
        db.flush()
        return existing

    limit = ExpensePolicyLimit(org_id=org_id, category=category, max_amount_minor=max_amount_minor)
    db.add(limit)
    db.flush()
    return limit


def delete_expense_policy_limit(db: Session, *, org_id: uuid.UUID, category: str) -> None:
    limit = _policy_limit_for_category(db, org_id=org_id, category=category)
    if limit is None:
        raise ValueError(f"no policy limit set for category {category!r}")
    db.delete(limit)
