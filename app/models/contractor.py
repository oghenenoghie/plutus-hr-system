import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Contractor(Base):
    """A non-employee vendor/contractor paid for goods or services, subject
    to withholding tax rather than PAYE (nigeria-statutory-compliance.md
    §8). tin is nullable at registration time but must be present before
    any payment can be recorded — the reform's penalty exposure applies to
    engaging unregistered contractors too, so this gets the same TIN gate
    employees get before a payroll run, not a softer one.

    engagement_start_date/engagement_end_date are onboarding metadata only
    (when the org expects to be using this contractor) — nothing in
    payroll or WHT reads them; they don't gate or affect a payment the way
    an employee's date_of_joining does for proration.
    """

    __tablename__ = "contractors"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tin: Mapped[str | None] = mapped_column(String(64))
    bank_name: Mapped[str | None] = mapped_column(String(255))
    account_number: Mapped[str | None] = mapped_column(String(32))
    account_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    engagement_start_date: Mapped[date | None] = mapped_column(Date)
    engagement_end_date: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
