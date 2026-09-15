import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PublicHoliday(Base):
    """One org-observed public holiday date, excluded from working-days
    proration (app.domain.payroll.proration) alongside weekends. Org-scoped
    rather than a shared national calendar, since a holiday roster is
    something an org must actually maintain — most Nigerian public
    holidays are federally fixed by date (New Year's Day, Workers' Day,
    Democracy Day, Independence Day, Christmas, Boxing Day; see
    seed_default_public_holidays), but the Islamic and Easter-based ones
    shift every year and this app has no calendar authority to compute
    them from — an admin adds those for the years they need.
    """

    __tablename__ = "public_holidays"
    __table_args__ = (
        UniqueConstraint("org_id", "holiday_date", name="uq_public_holiday_org_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
