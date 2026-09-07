import uuid
from datetime import datetime, time

from sqlalchemy import DateTime, ForeignKey, String, Time, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Shift(Base):
    """A work-shift definition (e.g. "Morning", "Night") employees can be
    assigned to — independent of Department/Branch/JobGrade. start_time/
    end_time are wall-clock times with no date component; a shift crossing
    midnight (end_time < start_time) is valid and means "overnight."
    """

    __tablename__ = "shifts"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_shift_org_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
