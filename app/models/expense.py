import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExpenseStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REIMBURSED = "reimbursed"


class Expense(Base):
    """An employee's out-of-pocket claim for reimbursement. category is free
    text rather than an enum — the compliance reference gives no statutory
    expense-category taxonomy to encode, and reimbursement of a genuine
    business expense carries no tax treatment of its own here (unlike a
    cash benefit, which would need one). Mutable status, same as
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
    status: Mapped[ExpenseStatus] = mapped_column(
        Enum(ExpenseStatus, name="expense_status", values_callable=lambda m: [x.value for x in m]),
        nullable=False,
        default=ExpenseStatus.PENDING,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reimbursed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
