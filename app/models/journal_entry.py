import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class JournalSourceType(str, enum.Enum):
    """What business event produced a journal. The full set from
    ACCOUNTING_IMPLEMENTATION_AUDIT.md §19.2 is declared up front so adding
    a posting site later never needs an enum migration; only the values
    marked "wired" below are written by code today."""

    PAYROLL = "payroll"  # wired: one journal per payslip at pay-run lock
    PAYROLL_DISBURSEMENT = "payroll_disbursement"
    STATUTORY_ACCRUAL = "statutory_accrual"  # wired: NSITF, per pay run
    STATUTORY_REMITTANCE = "statutory_remittance"  # wired: liability marked remitted
    EXPENSE_CLAIM = "expense_claim"
    EXPENSE_REIMBURSEMENT = "expense_reimbursement"
    EXPENDITURE = "expenditure"
    BILL = "bill"
    VENDOR_PAYMENT = "vendor_payment"
    CONTRACTOR_PAYMENT = "contractor_payment"
    INVOICE = "invoice"
    CUSTOMER_PAYMENT = "customer_payment"
    CREDIT_NOTE = "credit_note"
    RECEIPT = "receipt"
    LOAN_DISBURSEMENT = "loan_disbursement"
    FIXED_ASSET = "fixed_asset"
    BANK_TRANSACTION = "bank_transaction"
    MANUAL_JOURNAL = "manual_journal"
    OPENING_BALANCE = "opening_balance"
    REVERSAL = "reversal"  # wired: pay-run reversal, via reverse_journal
    YEAR_END_CLOSE = "year_end_close"
    LEGACY = "legacy"  # wired: header adopted for a journal that pre-dates this table


class JournalEntry(Base):
    """Header for one balanced set of ledger_entries lines. Its id *is* the
    ledger_entries.journal_entry_id every line already carries, so no
    historical row is rewritten — a journal that pre-dates this table gets
    a LEGACY header lazily, the first time something needs one (see
    app/services/posting.py ensure_journal_header).

    Append-only, like the lines: a database trigger forbids UPDATE/DELETE.
    "Is this journal reversed?" is therefore derived (does a journal exist
    with reversal_of_id = this.id), never a flag flipped on the header; a
    unique index on reversal_of_id makes a double reversal structurally
    impossible. A second unique index on (org, source_type, source_id,
    source_event) makes posting the same business event twice impossible.

    entry_date is the *accounting* date. Reports still filter on
    ledger_entries.created_at today (audit P7) — switching them to
    entry_date is a separate, later change.
    """

    __tablename__ = "journal_entries"
    __table_args__ = (
        CheckConstraint(
            "reversal_of_id IS NULL OR reversal_reason IS NOT NULL",
            name="ck_journal_reversal_has_reason",
        ),
        Index("uq_journal_reversal_of", "reversal_of_id", unique=True),
        Index(
            "uq_journal_source_event",
            "org_id",
            "source_type",
            "source_id",
            "source_event",
            unique=True,
            postgresql_where=text("source_id IS NOT NULL"),
        ),
        Index("ix_journal_entries_org_entry_date", "org_id", "entry_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False
    )

    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_type: Mapped[JournalSourceType] = mapped_column(
        Enum(
            JournalSourceType,
            name="journal_source_type",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    # Polymorphic pointer at the originating document (payslip, pay run,
    # statutory liability, ...) — deliberately no FK, since it can point at
    # several different tables; the posting service validates it instead.
    source_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_event: Mapped[str] = mapped_column(String(64), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")

    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    reversal_reason: Mapped[str | None] = mapped_column(String(500))

    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
