import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    VOID = "void"


class Invoice(Base):
    """An accounts-receivable invoice to a Customer — the AR counterpart to
    Bill. `revenue_account_code` names which chart-of-accounts revenue
    line this invoice's income belongs to, chosen at creation. Lifecycle
    mirrors Bill's: draft -> sent (posts the receivable/revenue) -> paid
    (clears the receivable to cash); void is only reachable from draft,
    same reasoning as Bill — voiding a sent invoice would need a
    reversing entry, left for a later pass.
    """

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("org_id", "invoice_number", name="uq_invoice_org_number"),
        CheckConstraint(
            "vat_treatment IS NULL OR vat_treatment IN ('standard', 'exempt', 'zero_rated', 'other')",
            name="ck_invoices_vat_treatment",
        ),
        CheckConstraint(
            "vat_rate_ppm BETWEEN 0 AND 1000000 AND vat_minor >= 0 "
            "AND total_minor = amount_minor + vat_minor",
            name="ck_invoices_vat_figures",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )

    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    revenue_account_code: Mapped[str] = mapped_column(String(64), nullable=False)
    # The net amount, before VAT. What the customer owes is total_minor.
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # How VAT applies (app.domain.accounting.vat.VatTreatment), the rate's
    # name as printed and the rate itself, fixed when the invoice is raised.
    # No treatment means no VAT was charged (invoices from before VAT was
    # recorded). vat_minor is worked out from amount_minor and the rate.
    vat_treatment: Mapped[str | None] = mapped_column(String(16))
    vat_rate_name: Mapped[str | None] = mapped_column(String(64))
    vat_rate_ppm: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    vat_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, name="invoice_status", values_callable=lambda m: [x.value for x in m]),
        nullable=False,
        default=InvoiceStatus.DRAFT,
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
