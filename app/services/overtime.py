import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.overtime import Overtime, OvertimeStatus


def submit_overtime(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    work_date: date,
    hours: Decimal,
    rate_multiplier: Decimal,
    amount_minor: int,
) -> Overtime:
    if hours <= 0:
        raise ValueError("hours must be positive")
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")
    overtime = Overtime(
        org_id=org_id,
        employee_id=employee_id,
        work_date=work_date,
        hours=hours,
        rate_multiplier=rate_multiplier,
        amount_minor=amount_minor,
    )
    db.add(overtime)
    db.flush()
    return overtime


def decide_overtime(db: Session, overtime: Overtime, *, approve: bool) -> Overtime:
    if overtime.status != OvertimeStatus.PENDING:
        raise ValueError(f"overtime entry is {overtime.status.value}, not pending")
    overtime.status = OvertimeStatus.APPROVED if approve else OvertimeStatus.REJECTED
    overtime.decided_at = datetime.now(UTC)
    db.add(overtime)
    return overtime
