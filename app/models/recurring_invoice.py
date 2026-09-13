import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.recurrence import RecurrenceFrequency
from app.models.base import Base


class RecurringInvoice(Base):
    """The AR counterpart to RecurringBill — a template for generating an
    Invoice automatically on a schedule (a subscription customers pay,
    a retainer). See generate_due_invoices()."""

    __tablename__ = "recurring_invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )

    invoice_number_prefix: Mapped[str] = mapped_column(String(64), nullable=False)
    revenue_account_code: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    due_in_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    frequency: Mapped[RecurrenceFrequency] = mapped_column(
        Enum(
            RecurrenceFrequency,
            name="recurring_invoice_frequency",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    next_run_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
