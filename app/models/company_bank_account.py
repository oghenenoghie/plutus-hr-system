import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CompanyBankAccount(Base):
    """The org's own operating bank account — distinct from BankAccount
    (an employee's account, for payroll disbursement). chart_account_code
    names which chart-of-accounts cash/asset code this account's balance
    corresponds to on the ledger (typically "cash"), so reconciliation can
    compare the bank's own statement against that account's ledger
    activity (see services/bank_reconciliation.py).
    """

    __tablename__ = "company_bank_accounts"
    __table_args__ = (
        UniqueConstraint("org_id", "account_number", name="uq_company_bank_account_org_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    bank_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_number: Mapped[str] = mapped_column(String(32), nullable=False)
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    chart_account_code: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
