import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExpenseStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REIMBURSED = "reimbursed"


class ExpensePaymentMethod(str, enum.Enum):
    # Paid out through the next pay run's disbursement, alongside net pay.
    REIMBURSEMENT = "reimbursement"
    # Paid directly (e.g. a one-off bank transfer), outside payroll —
    # chosen per claim, since not every reimbursable expense should wait
    # for the next pay cycle.
    DIRECT_PAYMENT = "direct_payment"


class Expense(Base):
    """An employee's out-of-pocket claim for reimbursement. category is free
    text rather than an enum — the compliance reference gives no statutory
    expense-category taxonomy to encode, and reimbursement of a genuine
    business expense carries no tax treatment of its own here (unlike a
    cash benefit, which would need one). Policy limits are still
    supportable without a fixed taxonomy: see ExpensePolicyLimit, keyed by
    the same free-text category. Mutable status, same as
    leave_requests/loans — not append-only.
    """

    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    category: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    # A link to an uploaded receipt image/PDF, same "URL reference, no file
    # storage of our own" pattern as Employee.photo_url — optional since a
    # missing receipt is a policy question for the approver, never a
    # submission blocker.
    receipt_url: Mapped[str | None] = mapped_column(String(2048))
    payment_method: Mapped[ExpensePaymentMethod] = mapped_column(
        Enum(
            ExpensePaymentMethod,
            name="expense_payment_method",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=ExpensePaymentMethod.REIMBURSEMENT,
    )
    status: Mapped[ExpenseStatus] = mapped_column(
        Enum(ExpenseStatus, name="expense_status", values_callable=lambda m: [x.value for x in m]),
        nullable=False,
        default=ExpenseStatus.PENDING,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reimbursed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExpensePolicyLimit(Base):
    """An org's optional per-category spending cap — category is the same
    free-text value Expense.category uses (see its docstring on why
    there's no fixed taxonomy), so setting a limit for "Travel" catches
    every expense claim submitted with that exact category string. No row
    for a category means no cap, not zero."""

    __tablename__ = "expense_policy_limits"
    __table_args__ = (UniqueConstraint("org_id", "category", name="uq_expense_policy_limit"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    max_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
