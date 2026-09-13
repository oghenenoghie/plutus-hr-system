import uuid
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.leave_encashment import LeaveEncashmentRequest, LeaveEncashmentStatus
from app.services.leave import InsufficientLeaveBalanceError, leave_balance


def submit_leave_encashment(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    requested_date: date,
    days: int,
    amount_minor: int,
) -> LeaveEncashmentRequest:
    if days <= 0:
        raise ValueError("days must be positive")
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")
    request = LeaveEncashmentRequest(
        org_id=org_id,
        employee_id=employee_id,
        requested_date=requested_date,
        days=days,
        amount_minor=amount_minor,
    )
    db.add(request)
    db.flush()
    return request


def approve_leave_encashment(
    db: Session, *, employee: Employee, request: LeaveEncashmentRequest
) -> LeaveEncashmentRequest:
    """Same balance-at-approval-time discipline as approve_leave_request: a
    pending request can exceed the balance (so an employee can ask), but it
    can't be approved past what's actually left."""
    if request.status != LeaveEncashmentStatus.PENDING:
        raise ValueError(f"leave encashment request is {request.status.value}, not pending")

    remaining = leave_balance(db, employee, request.requested_date)
    if request.days > remaining:
        raise InsufficientLeaveBalanceError(
            f"encashment of {request.days} days exceeds the {remaining} remaining"
        )

    request.status = LeaveEncashmentStatus.APPROVED
    request.decided_at = datetime.now(UTC)
    db.add(request)
    return request


def reject_leave_encashment(db: Session, request: LeaveEncashmentRequest) -> LeaveEncashmentRequest:
    if request.status != LeaveEncashmentStatus.PENDING:
        raise ValueError(f"leave encashment request is {request.status.value}, not pending")
    request.status = LeaveEncashmentStatus.REJECTED
    request.decided_at = datetime.now(UTC)
    db.add(request)
    return request
