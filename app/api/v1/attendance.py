import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.attendance_record import AttendanceRecord
from app.models.employee import Employee
from app.models.membership import Role
from app.schemas.attendance import AttendanceRecordOut
from app.services.attendance import clock_in, clock_out

router = APIRouter(prefix="/attendance", tags=["attendance"])

_VIEW = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)


@router.post("/clock-in", response_model=AttendanceRecordOut, status_code=status.HTTP_201_CREATED)
def clock_in_endpoint(
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
) -> AttendanceRecord:
    try:
        return clock_in(db, org_id=employee.org_id, employee_id=employee.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/clock-out", response_model=AttendanceRecordOut)
def clock_out_endpoint(
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
) -> AttendanceRecord:
    try:
        return clock_out(db, employee_id=employee.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/me", response_model=list[AttendanceRecordOut])
def list_my_attendance(
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    employee: Employee = Depends(get_current_employee),
) -> list[AttendanceRecord]:
    query = select(AttendanceRecord).where(AttendanceRecord.employee_id == employee.id)
    if start_date is not None:
        query = query.where(AttendanceRecord.work_date >= start_date)
    if end_date is not None:
        query = query.where(AttendanceRecord.work_date <= end_date)
    return list(db.scalars(query.order_by(AttendanceRecord.work_date)))


@router.get("/employees/{employee_id}", response_model=list[AttendanceRecordOut])
def list_attendance_for_employee(
    employee_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_VIEW),
) -> list[AttendanceRecord]:
    if claims.role == Role.MANAGER.value:
        manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
        target = db.get(Employee, employee_id)
        if manager is None or target is None or target.manager_id != manager.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not authorised to view this employee's attendance",
            )
    query = select(AttendanceRecord).where(AttendanceRecord.employee_id == employee_id)
    if start_date is not None:
        query = query.where(AttendanceRecord.work_date >= start_date)
    if end_date is not None:
        query = query.where(AttendanceRecord.work_date <= end_date)
    return list(db.scalars(query.order_by(AttendanceRecord.work_date)))
