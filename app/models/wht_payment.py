import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WhtPayment(Base):
    """One contractor/vendor payment with tax withheld at source
    (nigeria-statutory-compliance.md §8) — the certificate of record for
    that withholding. Append-only, same discipline as payslips: a
    correction is a new row, never an edit to this one.

    certificate_number is derived from this row's own id (WHT-<id>)
    rather than a sequential scheme — the reference gives no NRS-specified
    certificate numbering format to encode, and deriving it from the id
    guarantees uniqueness without a shared counter to race on.
    """

    __tablename__ = "wht_payments"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    contractor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contractors.id", ondelete="CASCADE"), nullable=False
    )

    category: Mapped[str] = mapped_column(String(64), nullable=False)
    gross_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    wht_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    certificate_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    rule_version_id: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
