import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ShiftRosterEntry(Base):
    """One employee rostered onto one Shift for one calendar date — the
    day-by-day schedule Shift itself doesn't carry (Shift is just a
    definition; Employee.shift_id is a single standing assignment with no
    notion of "which days"). An employee has at most one entry per date
    (see uq_roster_employee_date) — register_roster_entries rejects a
    range that would double-book any date rather than silently
    overwriting a prior assignment.
    """

    __tablename__ = "shift_roster_entries"
    __table_args__ = (UniqueConstraint("employee_id", "work_date", name="uq_roster_employee_date"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    shift_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
