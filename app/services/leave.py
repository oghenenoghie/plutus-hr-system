import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.payroll.leave import compute_leave_balance
from app.models.employee import Employee
from app.models.leave import LeaveRequest, LeaveStatus, LeaveType


class InsufficientLeaveBalanceError(Exception):
    """Raised when approving a request would exceed the employee's
    remaining balance for this leave year."""


def _leave_year_start(on: date) -> date:
    return date(on.year, 1, 1)


def approved_days_taken(db: Session, employee_id: uuid.UUID, on: date) -> int:
    year_start = _leave_year_start(on)
    total = db.scalar(
        select(func.coalesce(func.sum(LeaveRequest.days), 0)).where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status == LeaveStatus.APPROVED,
            LeaveRequest.start_date >= year_start,
        )
    )
    return total or 0


def leave_balance(db: Session, employee: Employee, on: date) -> int:
    taken = approved_days_taken(db, employee.id, on)
    return compute_leave_balance(employee.annual_leave_entitlement_days, taken)


def approve_leave_request(
    db: Session, *, employee: Employee, request: LeaveRequest
) -> LeaveRequest:
    """Approving is the only place balance is enforced — a pending request
    can exceed the balance (so an employee can ask), but it can't be
    approved past what's actually left."""
    if request.status != LeaveStatus.PENDING:
        raise ValueError(f"leave request is {request.status.value}, not pending")

    remaining = leave_balance(db, employee, request.start_date)
    if request.days > remaining:
        raise InsufficientLeaveBalanceError(
            f"request for {request.days} days exceeds the {remaining} remaining"
        )

    request.status = LeaveStatus.APPROVED
    request.decided_at = datetime.now(UTC)
    db.add(request)
    return request


def reject_leave_request(db: Session, request: LeaveRequest) -> LeaveRequest:
    if request.status != LeaveStatus.PENDING:
        raise ValueError(f"leave request is {request.status.value}, not pending")
    request.status = LeaveStatus.REJECTED
    request.decided_at = datetime.now(UTC)
    db.add(request)
    return request


def submit_leave_request(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    leave_type: LeaveType,
    start_date: date,
    end_date: date,
    days: int,
    reason: str | None = None,
) -> LeaveRequest:
    if days <= 0:
        raise ValueError("days must be positive")
    if end_date < start_date:
        raise ValueError("end_date must not be before start_date")

    request = LeaveRequest(
        org_id=org_id,
        employee_id=employee_id,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        days=days,
        reason=reason,
    )
    db.add(request)
    db.flush()
    return request
