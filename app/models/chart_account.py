import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AccountType(str, enum.Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class ChartAccount(Base):
    """One line of the org's chart of accounts. `code` is the same string
    already written into ledger_entries.account by payroll/WHT postings
    (app/domain/payroll/postings.py) — this table categorizes those
    existing codes by type rather than replacing them, so no change to
    LedgerEntry or its writers is needed. General Ledger joins on `code`.
    """

    __tablename__ = "chart_accounts"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_chart_account_org_code"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[AccountType] = mapped_column(
        Enum(
            AccountType, name="chart_account_type", values_callable=lambda m: [x.value for x in m]
        ),
        nullable=False,
    )
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
