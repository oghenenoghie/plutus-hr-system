import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BankStatementLine(Base):
    """One line from a CompanyBankAccount's actual bank statement, entered
    or imported for reconciliation against the ledger. amount_minor is
    signed: positive for money in, negative for money out — a statement
    line isn't a double-entry posting, just what the bank says happened.
    matched_ledger_entry_id is set once a user confirms this line
    corresponds to a specific LedgerEntry on the account's
    chart_account_code (see services/bank_reconciliation.py::match_line);
    left null, it's an outstanding item still to account for.
    """

    __tablename__ = "bank_statement_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("company_bank_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    matched_ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ledger_entries.id", ondelete="SET NULL"), unique=True
    )

    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
