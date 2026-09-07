import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Budget(Base):
    """A planning target for a period — one or more BudgetLine rows, each
    naming a revenue/expense chart-of-accounts code and a budgeted amount.
    Unlike Bill/Invoice/FixedAsset, a budget never posts to the ledger: it
    is compared against actual ledger activity for its period on read
    (see services/budgets.py::budget_vs_actual), not recorded as a
    transaction itself. department_id is optional — a budget can be
    org-wide or scoped to one department.
    """

    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_budget_org_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL")
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BudgetLine(Base):
    """One budgeted amount for one account within a Budget. Deleted and
    recreated wholesale on update (see services/budgets.py::update_budget)
    rather than diffed, matching how small a typical budget's line count is.
    """

    __tablename__ = "budget_lines"
    __table_args__ = (UniqueConstraint("budget_id", "account_code", name="uq_budget_line_account"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    budget_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False
    )

    account_code: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
