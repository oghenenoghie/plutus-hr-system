import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.attendance_record import AttendanceRecord


def clock_in(db: Session, *, org_id: uuid.UUID, employee_id: uuid.UUID) -> AttendanceRecord:
    now = datetime.now(UTC)
    today = now.date()
    record = db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.employee_id == employee_id, AttendanceRecord.work_date == today
        )
    )
    if record is not None:
        raise ValueError("already clocked in for today")
    record = AttendanceRecord(
        org_id=org_id, employee_id=employee_id, work_date=today, clock_in_at=now
    )
    db.add(record)
    db.flush()
    return record


def clock_out(db: Session, *, employee_id: uuid.UUID) -> AttendanceRecord:
    now = datetime.now(UTC)
    today = now.date()
    record = db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.employee_id == employee_id, AttendanceRecord.work_date == today
        )
    )
    if record is None:
        raise ValueError("not clocked in for today")
    if record.clock_out_at is not None:
        raise ValueError("already clocked out for today")
    record.clock_out_at = now
    db.add(record)
    return record
