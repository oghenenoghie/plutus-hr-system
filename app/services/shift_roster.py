import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.shift_roster_entry import ShiftRosterEntry


def _dates_in_range(start_date: date, end_date: date) -> list[date]:
    days = (end_date - start_date).days
    return [start_date + timedelta(days=offset) for offset in range(days + 1)]


def register_roster_entries(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    shift_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> list[ShiftRosterEntry]:
    if end_date < start_date:
        raise ValueError("end_date must not be before start_date")
    dates = _dates_in_range(start_date, end_date)

    existing = db.scalars(
        select(ShiftRosterEntry.work_date).where(
            ShiftRosterEntry.employee_id == employee_id,
            ShiftRosterEntry.work_date.in_(dates),
        )
    ).all()
    if existing:
        clashing = ", ".join(sorted(d.isoformat() for d in existing))
        raise ValueError(f"employee is already rostered on: {clashing}")

    entries = [
        ShiftRosterEntry(
            org_id=org_id, employee_id=employee_id, shift_id=shift_id, work_date=work_date
        )
        for work_date in dates
    ]
    db.add_all(entries)
    db.flush()
    return entries
