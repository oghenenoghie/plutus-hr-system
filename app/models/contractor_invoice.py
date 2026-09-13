import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ContractorInvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PAID = "paid"


class ContractorInvoice(Base):
    """A contractor's own invoice for work done, tracked through
    draft -> submitted -> paid — distinct from WhtPayment, which is the
    withholding-tax record of an actual payment. Paying an invoice
    (app.services.contractor_invoices.mark_invoice_paid) creates the
    WhtPayment (and its ledger postings/liability) the normal way and
    links back to it here, so invoicing sits in front of the existing
    tax-withholding machinery rather than duplicating it.
    """

    __tablename__ = "contractor_invoices"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "contractor_id", "invoice_number", name="uq_contractor_invoice_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    contractor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contractors.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable: set only once mark_invoice_paid actually records the
    # withholding-tax payment for this invoice.
    wht_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("wht_payments.id", ondelete="SET NULL")
    )

    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[ContractorInvoiceStatus] = mapped_column(
        Enum(
            ContractorInvoiceStatus,
            name="contractor_invoice_status",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=ContractorInvoiceStatus.DRAFT,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
