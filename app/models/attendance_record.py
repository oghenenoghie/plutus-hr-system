import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AttendanceRecord(Base):
    """One employee's actual clock-in/clock-out for one calendar date — what
    actually happened, as opposed to ShiftRosterEntry (what was planned) or
    LeaveRequest (an approved absence). At most one record per employee per
    date (see uq_attendance_employee_date); clock_in_at/clock_out_at are
    set by the two self-service actions in app.services.attendance, never
    directly, so their ordering (clock out only after clocking in, never
    twice) is enforced there rather than at the model.
    """

    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date", name="uq_attendance_employee_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    clock_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clock_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
