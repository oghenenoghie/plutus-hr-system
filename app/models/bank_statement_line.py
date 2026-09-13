import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BankStatementLine(Base):
    """One line from an external bank statement, entered manually (this app
    has no live bank feed) against one of the org's cash-type ledger
    accounts (account_code, a free-text tag matching LedgerEntry.account —
    "cash" by default, but an org can reconcile more than one bank account
    if it uses more than one cash-type ChartAccount code). amount_minor is
    signed the same way a cash-account ledger contribution is: positive
    for a deposit (an inflow, debit to cash), negative for a withdrawal.
    Matching it to a LedgerEntry (see match_statement_line) is the
    reconciliation act; unmatching just clears the link — mutable, not
    append-only, since a wrong match needs to be undone rather than
    superseded by a new row.
    """

    __tablename__ = "bank_statement_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    account_code: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(255))

    matched_ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ledger_entries.id", ondelete="SET NULL")
    )
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    matched_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
