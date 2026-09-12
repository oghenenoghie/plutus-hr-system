import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims, generate_login_code
from app.models.employee import Employee
from app.models.employee_login_code import EmployeeLoginCode
from app.models.membership import Role
from app.schemas.employees import EmployeeCreate, EmployeeOut, EmployeeUpdate, LinkAccountRequest
from app.services.audit import record_audit_event

router = APIRouter(prefix="/employees", tags=["employees"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)
_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)

_LOGIN_CODE_MAX_ATTEMPTS = 5


def _assign_unique_login_code(db: Session, employee: Employee) -> None:
    """login_code is unique across every org, not just this one, so a
    within-org RLS-scoped SELECT can't reliably check it for collisions —
    the Postgres unique index enforces uniqueness across the whole table
    regardless of RLS, so this attempts the insert and retries on the rare
    collision instead of pre-checking. A savepoint keeps a failed attempt
    from poisoning the outer transaction (the audit event insert right
    after this call still needs to succeed).
    """
    for _ in range(_LOGIN_CODE_MAX_ATTEMPTS):
        employee.login_code = generate_login_code()
        try:
            with db.begin_nested():
                db.flush()
            return
        except IntegrityError:
            continue
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="could not assign a unique login code — try again",
    )


def _get_employee_or_404(db: Session, employee_id: uuid.UUID) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")
    return employee


def _require_visible(db: Session, claims: TokenClaims, employee: Employee) -> Employee:
    """ADMIN/PAYROLL_MANAGER can see anyone; MANAGER only their own direct
    reports; anyone else (EMPLOYEE) gets 404 rather than a 403 that would
    confirm the record exists."""
    if claims.role in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value):
        return employee
    if claims.role == Role.MANAGER.value:
        manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
        if manager is not None and employee.manager_id == manager.id:
            return employee
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
def create_employee(
    body: EmployeeCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Employee:
    employee = Employee(org_id=claims.org_id, **body.model_dump())
    db.add(employee)
    _assign_unique_login_code(db, employee)
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="employee.create",
        entity_type="employee",
        entity_id=employee.id,
        metadata={"employee_number": employee.employee_number},
    )
    return employee


@router.get("", response_model=list[EmployeeOut])
def list_employees(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_VIEW_LIST)
) -> list[Employee]:
    if claims.role in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value):
        return list(db.scalars(select(Employee)))

    manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
    if manager is None:
        return []
    return list(db.scalars(select(Employee).where(Employee.manager_id == manager.id)))


@router.get("/me", response_model=EmployeeOut)
def get_my_employee_record(employee: Employee = Depends(get_current_employee)) -> Employee:
    return employee


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> Employee:
    employee = _get_employee_or_404(db, employee_id)
    return _require_visible(db, claims, employee)


@router.patch("/{employee_id}", response_model=EmployeeOut)
def update_employee(
    employee_id: uuid.UUID,
    body: EmployeeUpdate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Employee:
    employee = _get_employee_or_404(db, employee_id)
    changed_fields = body.model_dump(exclude_unset=True)
    for field, value in changed_fields.items():
        setattr(employee, field, value)
    db.add(employee)
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="employee.update",
        entity_type="employee",
        entity_id=employee.id,
        metadata={"fields": sorted(changed_fields)},
    )
    return employee


@router.post("/{employee_id}/link-account", response_model=EmployeeOut)
def link_account(
    employee_id: uuid.UUID,
    body: LinkAccountRequest,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Employee:
    employee = _get_employee_or_404(db, employee_id)
    existing = db.scalar(select(Employee).where(Employee.account_id == body.account_id))
    if existing is not None and existing.id != employee.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="that account is already linked to another employee",
        )
    employee.account_id = body.account_id
    db.add(employee)
    if employee.login_code is not None:
        # employee_login_codes has no RLS (see its model docstring) so
        # /auth/login can resolve a code to an account pre-tenant-session;
        # keep it in sync with employees.account_id whenever that link
        # changes.
        login_code_row = db.scalar(
            select(EmployeeLoginCode).where(EmployeeLoginCode.employee_id == employee.id)
        )
        if login_code_row is None:
            login_code_row = EmployeeLoginCode(
                login_code=employee.login_code, employee_id=employee.id
            )
        login_code_row.account_id = body.account_id
        db.add(login_code_row)
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="employee.link_account",
        entity_type="employee",
        entity_id=employee.id,
        metadata={"linked_account_id": str(body.account_id)},
    )
    return employee
