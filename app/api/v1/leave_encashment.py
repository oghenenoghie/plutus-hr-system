import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee
from app.models.leave_encashment import LeaveEncashmentRequest
from app.models.membership import Role
from app.schemas.leave_encashment import LeaveEncashmentCreate, LeaveEncashmentOut
from app.services.audit import record_audit_event
from app.services.leave import InsufficientLeaveBalanceError
from app.services.leave_encashment import (
    approve_leave_encashment,
    reject_leave_encashment,
    submit_leave_encashment,
)

router = APIRouter(prefix="/leave-encashment", tags=["leave"])

_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)


def _get_or_404(db: Session, request_id: uuid.UUID) -> LeaveEncashmentRequest:
    request = db.get(LeaveEncashmentRequest, request_id)
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="leave encashment request not found"
        )
    return request


def _requester_can_decide(
    db: Session, claims: TokenClaims, request: LeaveEncashmentRequest
) -> Employee:
    employee = db.get(Employee, request.employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")

    if claims.role in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value):
        return employee
    if claims.role == Role.MANAGER.value:
        manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
        if manager is not None and employee.manager_id == manager.id:
            return employee
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="not authorised to decide this request"
    )


@router.post("/me", response_model=LeaveEncashmentOut, status_code=status.HTTP_201_CREATED)
def submit_my_leave_encashment(
    body: LeaveEncashmentCreate,
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
    claims: TokenClaims = Depends(get_current_claims),
) -> LeaveEncashmentRequest:
    try:
        request = submit_leave_encashment(
            db,
            org_id=employee.org_id,
            employee_id=employee.id,
            requested_date=body.requested_date,
            days=body.days,
            amount_minor=body.amount_minor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=employee.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="leave_encashment.submit",
        entity_type="leave_encashment_request",
        entity_id=request.id,
        metadata={"days": request.days, "amount_minor": request.amount_minor},
    )
    return request


@router.get("/me", response_model=list[LeaveEncashmentOut])
def list_my_leave_encashment(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> list[LeaveEncashmentRequest]:
    return list(
        db.scalars(
            select(LeaveEncashmentRequest)
            .where(LeaveEncashmentRequest.employee_id == employee.id)
            .order_by(LeaveEncashmentRequest.requested_date.desc())
        )
    )


@router.get("", response_model=list[LeaveEncashmentOut])
def list_leave_encashment(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_VIEW_LIST)
) -> list[LeaveEncashmentRequest]:
    if claims.role in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value):
        return list(db.scalars(select(LeaveEncashmentRequest)))

    manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
    if manager is None:
        return []
    report_ids = select(Employee.id).where(Employee.manager_id == manager.id)
    return list(
        db.scalars(
            select(LeaveEncashmentRequest).where(LeaveEncashmentRequest.employee_id.in_(report_ids))
        )
    )


@router.post("/{request_id}/approve", response_model=LeaveEncashmentOut)
def approve_request(
    request_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> LeaveEncashmentRequest:
    request = _get_or_404(db, request_id)
    employee = _requester_can_decide(db, claims, request)
    try:
        approve_leave_encashment(db, employee=employee, request=request)
    except (InsufficientLeaveBalanceError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="leave_encashment.approve",
        entity_type="leave_encashment_request",
        entity_id=request.id,
    )
    return request


@router.post("/{request_id}/reject", response_model=LeaveEncashmentOut)
def reject_request(
    request_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> LeaveEncashmentRequest:
    request = _get_or_404(db, request_id)
    _requester_can_decide(db, claims, request)
    try:
        reject_leave_encashment(db, request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="leave_encashment.reject",
        entity_type="leave_encashment_request",
        entity_id=request.id,
    )
    return request
