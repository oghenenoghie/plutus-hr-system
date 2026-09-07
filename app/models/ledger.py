import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LedgerEntry(Base):
    """Double-entry, append-only (python-engineering.md §6). Every row
    belongs to a journal_entry_id; a deferred DB trigger (see the Alembic
    migration) checks that each journal_entry_id's debits equal its
    credits at transaction commit. Reversals are compensating entries in a
    new journal_entry_id, never edits or deletes of these rows.
    """

    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint(
            "debit_minor >= 0 AND credit_minor >= 0", name="ck_ledger_entry_nonnegative"
        ),
        CheckConstraint(
            "(debit_minor > 0 AND credit_minor = 0) OR (credit_minor > 0 AND debit_minor = 0)",
            name="ck_ledger_entry_single_sided",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    journal_entry_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pay_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pay_runs.id", ondelete="CASCADE")
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE")
    )

    account: Mapped[str] = mapped_column(String(64), nullable=False)
    debit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    credit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    description: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
