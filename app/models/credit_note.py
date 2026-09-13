import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CreditNote(Base):
    """A reduction issued against a Customer's Invoice — a return, a
    billing correction, a goodwill adjustment. Only issuable against a
    SENT or PAID invoice (there's a receivable/revenue posted to reverse;
    a DRAFT invoice never posted one, and a VOID one is already dead) —
    see issue_credit_note, which also caps total credited at the
    invoice's own amount_minor. Append-only, same as every other posted
    financial event in this codebase (WhtPayment, LedgerEntry): once
    issued it's permanent, a correction is a new credit note, not an edit
    to this one.
    """

    __tablename__ = "credit_notes"
    __table_args__ = (
        UniqueConstraint("org_id", "credit_note_number", name="uq_credit_note_org_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )

    credit_note_number: Mapped[str] = mapped_column(String(64), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
