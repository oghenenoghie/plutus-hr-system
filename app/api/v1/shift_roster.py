import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee
from app.models.membership import Role
from app.models.shift_roster_entry import ShiftRosterEntry
from app.schemas.shift_roster import ShiftRosterEntryCreate, ShiftRosterEntryOut
from app.services.shift_roster import register_roster_entries

router = APIRouter(prefix="/shift-roster", tags=["shift-roster"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)


@router.post("", response_model=list[ShiftRosterEntryOut], status_code=status.HTTP_201_CREATED)
def create_roster_entries(
    body: ShiftRosterEntryCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[ShiftRosterEntry]:
    if claims.role == Role.MANAGER.value:
        manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
        employee = db.get(Employee, body.employee_id)
        if manager is None or employee is None or employee.manager_id != manager.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not authorised to roster this employee",
            )
    try:
        return register_roster_entries(db, org_id=claims.org_id, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[ShiftRosterEntryOut])
def list_roster_entries(
    employee_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[ShiftRosterEntry]:
    if claims.role == Role.MANAGER.value:
        manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
        employee = db.get(Employee, employee_id)
        if manager is None or employee is None or employee.manager_id != manager.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not authorised to view this employee's roster",
            )
    query = select(ShiftRosterEntry).where(ShiftRosterEntry.employee_id == employee_id)
    if start_date is not None:
        query = query.where(ShiftRosterEntry.work_date >= start_date)
    if end_date is not None:
        query = query.where(ShiftRosterEntry.work_date <= end_date)
    return list(db.scalars(query.order_by(ShiftRosterEntry.work_date)))


@router.get("/me", response_model=list[ShiftRosterEntryOut])
def list_my_roster_entries(
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
) -> list[ShiftRosterEntry]:
    query = select(ShiftRosterEntry).where(ShiftRosterEntry.employee_id == employee.id)
    if start_date is not None:
        query = query.where(ShiftRosterEntry.work_date >= start_date)
    if end_date is not None:
        query = query.where(ShiftRosterEntry.work_date <= end_date)
    return list(db.scalars(query.order_by(ShiftRosterEntry.work_date)))
