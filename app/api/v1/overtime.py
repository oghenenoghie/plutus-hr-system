import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee
from app.models.membership import Role
from app.models.overtime import Overtime
from app.schemas.overtime import OvertimeCreate, OvertimeOut
from app.services.audit import record_audit_event
from app.services.overtime import decide_overtime, submit_overtime

router = APIRouter(prefix="/overtime", tags=["overtime"])

_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)


def _get_or_404(db: Session, overtime_id: uuid.UUID) -> Overtime:
    overtime = db.get(Overtime, overtime_id)
    if overtime is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="overtime entry not found"
        )
    return overtime


def _requester_can_decide(db: Session, claims: TokenClaims, overtime: Overtime) -> None:
    if claims.role in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value):
        return
    if claims.role == Role.MANAGER.value:
        employee = db.get(Employee, overtime.employee_id)
        manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
        if employee is not None and manager is not None and employee.manager_id == manager.id:
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="not authorised to decide this overtime entry"
    )


@router.post("/me", response_model=OvertimeOut, status_code=status.HTTP_201_CREATED)
def submit_my_overtime(
    body: OvertimeCreate,
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
    claims: TokenClaims = Depends(get_current_claims),
) -> Overtime:
    try:
        overtime = submit_overtime(
            db,
            org_id=employee.org_id,
            employee_id=employee.id,
            work_date=body.work_date,
            hours=body.hours,
            rate_multiplier=body.rate_multiplier,
            amount_minor=body.amount_minor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=employee.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="overtime.submit",
        entity_type="overtime",
        entity_id=overtime.id,
        metadata={"amount_minor": overtime.amount_minor},
    )
    return overtime


@router.get("/me", response_model=list[OvertimeOut])
def list_my_overtime(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> list[Overtime]:
    return list(
        db.scalars(
            select(Overtime)
            .where(Overtime.employee_id == employee.id)
            .order_by(Overtime.work_date.desc())
        )
    )


@router.get("", response_model=list[OvertimeOut])
def list_overtime(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_VIEW_LIST)
) -> list[Overtime]:
    if claims.role in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value):
        return list(db.scalars(select(Overtime)))

    manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
    if manager is None:
        return []
    report_ids = select(Employee.id).where(Employee.manager_id == manager.id)
    return list(db.scalars(select(Overtime).where(Overtime.employee_id.in_(report_ids))))


@router.post("/{overtime_id}/approve", response_model=OvertimeOut)
def approve_overtime(
    overtime_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> Overtime:
    overtime = _get_or_404(db, overtime_id)
    _requester_can_decide(db, claims, overtime)
    try:
        decide_overtime(db, overtime, approve=True)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="overtime.approve",
        entity_type="overtime",
        entity_id=overtime.id,
    )
    return overtime


@router.post("/{overtime_id}/reject", response_model=OvertimeOut)
def reject_overtime(
    overtime_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> Overtime:
    overtime = _get_or_404(db, overtime_id)
    _requester_can_decide(db, claims, overtime)
    try:
        decide_overtime(db, overtime, approve=False)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="overtime.reject",
        entity_type="overtime",
        entity_id=overtime.id,
    )
    return overtime
