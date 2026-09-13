import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.recurrence import RecurrenceFrequency
from app.models.base import Base


class RecurringBill(Base):
    """A template for generating a Bill automatically on a schedule (rent,
    a subscription, a retainer). generate_due_bills() creates a real Bill
    for every template whose next_run_date has arrived, using
    bill_number_prefix + that date to build a unique bill_number, then
    advances next_run_date by frequency. is_active lets an org pause a
    recurrence without deleting its history of what it already generated.
    """

    __tablename__ = "recurring_bills"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )

    bill_number_prefix: Mapped[str] = mapped_column(String(64), nullable=False)
    expense_account_code: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vat_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    wht_category: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(500))
    due_in_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)

    frequency: Mapped[RecurrenceFrequency] = mapped_column(
        Enum(
            RecurrenceFrequency,
            name="recurring_bill_frequency",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    next_run_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
