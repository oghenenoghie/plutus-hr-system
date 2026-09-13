import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.probation_period import ProbationPeriod, ProbationStatus


def register_probation_period(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> ProbationPeriod:
    if end_date <= start_date:
        raise ValueError("end_date must be after start_date")
    existing = db.scalar(
        select(ProbationPeriod).where(
            ProbationPeriod.employee_id == employee_id,
            ProbationPeriod.status == ProbationStatus.IN_PROGRESS,
        )
    )
    if existing is not None:
        raise ValueError("employee already has a probation period in progress")

    period = ProbationPeriod(
        org_id=org_id, employee_id=employee_id, start_date=start_date, end_date=end_date
    )
    db.add(period)
    db.flush()
    return period


def _require_in_progress(period: ProbationPeriod) -> None:
    if period.status != ProbationStatus.IN_PROGRESS:
        raise ValueError(f"probation period is already {period.status.value}")


def extend_probation(
    db: Session, period: ProbationPeriod, *, new_end_date: date, notes: str | None = None
) -> ProbationPeriod:
    _require_in_progress(period)
    if new_end_date <= period.end_date:
        raise ValueError("new_end_date must be after the current end_date")
    period.end_date = new_end_date
    period.notes = notes
    db.add(period)
    return period


def decide_probation(
    db: Session,
    period: ProbationPeriod,
    *,
    outcome: ProbationStatus,
    decided_by: uuid.UUID | None,
    notes: str | None = None,
) -> ProbationPeriod:
    if outcome == ProbationStatus.IN_PROGRESS:
        raise ValueError("outcome must be confirmed or failed")
    _require_in_progress(period)
    period.status = outcome
    period.decided_date = datetime.now(UTC).date()
    period.decided_by = decided_by
    period.notes = notes
    db.add(period)
    return period
