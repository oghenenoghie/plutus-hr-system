import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.approval import ApprovalRequestType
from app.models.employee import Employee
from app.models.leave import LeaveRequest
from app.models.membership import Role
from app.schemas.approvals import DecisionBody
from app.schemas.leave import LeaveBalanceOut, LeaveRequestCreate, LeaveRequestOut
from app.services import approvals
from app.services.audit import record_audit_event
from app.services.leave import (
    InsufficientLeaveBalanceError,
    approve_leave_request,
    leave_balance,
    reject_leave_request,
    submit_leave_request,
)

router = APIRouter(prefix="/leave-requests", tags=["leave"])

_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)


def _get_request_or_404(db: Session, request_id: uuid.UUID) -> LeaveRequest:
    request = db.get(LeaveRequest, request_id)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="leave request not found")
    return request


@router.post("/me", response_model=LeaveRequestOut, status_code=status.HTTP_201_CREATED)
def submit_my_leave_request(
    body: LeaveRequestCreate,
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
    claims: TokenClaims = Depends(get_current_claims),
) -> LeaveRequest:
    try:
        request = submit_leave_request(
            db,
            org_id=employee.org_id,
            employee_id=employee.id,
            leave_type=body.leave_type,
            start_date=body.start_date,
            end_date=body.end_date,
            days=body.days,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    approvals.get_or_create_instance(
        db,
        org_id=employee.org_id,
        request_type=ApprovalRequestType.LEAVE_REQUEST,
        request_id=request.id,
        requester_employee_id=employee.id,
    )
    record_audit_event(
        db,
        org_id=employee.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="leave_request.submit",
        entity_type="leave_request",
        entity_id=request.id,
        metadata={"days": request.days, "leave_type": request.leave_type.value},
    )
    return request


@router.get("/me", response_model=list[LeaveRequestOut])
def list_my_leave_requests(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> list[LeaveRequest]:
    return list(
        db.scalars(
            select(LeaveRequest)
            .where(LeaveRequest.employee_id == employee.id)
            .order_by(LeaveRequest.start_date.desc())
        )
    )


@router.get("/me/balance", response_model=LeaveBalanceOut)
def get_my_leave_balance(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> LeaveBalanceOut:
    remaining = leave_balance(db, employee, datetime.now(UTC).date())
    taken = employee.annual_leave_entitlement_days - remaining
    return LeaveBalanceOut(
        entitlement_days=employee.annual_leave_entitlement_days,
        taken_days=max(0, taken),
        remaining_days=remaining,
    )


@router.get("", response_model=list[LeaveRequestOut])
def list_leave_requests(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_VIEW_LIST)
) -> list[LeaveRequest]:
    if claims.role in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value):
        return list(db.scalars(select(LeaveRequest)))

    manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
    if manager is None:
        return []
    report_ids = select(Employee.id).where(Employee.manager_id == manager.id)
    return list(db.scalars(select(LeaveRequest).where(LeaveRequest.employee_id.in_(report_ids))))


@router.post("/{request_id}/approve", response_model=LeaveRequestOut)
def approve_request(
    request_id: uuid.UUID,
    body: DecisionBody | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> LeaveRequest:
    request = _get_request_or_404(db, request_id)
    try:
        _, is_final = approvals.decide(
            db,
            claims=claims,
            request_type=ApprovalRequestType.LEAVE_REQUEST,
            request_id=request.id,
            requester_employee_id=request.employee_id,
            approve=True,
            comment=body.comment if body else None,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if is_final:
        employee = db.get(Employee, request.employee_id)
        if employee is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")
        try:
            approve_leave_request(db, employee=employee, request=request)
        except (InsufficientLeaveBalanceError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="leave_request.approve" if is_final else "leave_request.approve_step",
        entity_type="leave_request",
        entity_id=request.id,
    )
    return request


@router.post("/{request_id}/reject", response_model=LeaveRequestOut)
def reject_request(
    request_id: uuid.UUID,
    body: DecisionBody | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> LeaveRequest:
    request = _get_request_or_404(db, request_id)
    try:
        approvals.decide(
            db,
            claims=claims,
            request_type=ApprovalRequestType.LEAVE_REQUEST,
            request_id=request.id,
            requester_employee_id=request.employee_id,
            approve=False,
            comment=body.comment if body else None,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        reject_leave_request(db, request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="leave_request.reject",
        entity_type="leave_request",
        entity_id=request.id,
    )
    return request
