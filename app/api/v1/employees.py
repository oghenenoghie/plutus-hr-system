import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.domain.nuban import NIGERIAN_BANKS
from app.models.bank_account import BankAccount
from app.models.employee import Employee
from app.models.membership import Role
from app.schemas.bank_account import BankAccountInput, BankAccountOut
from app.schemas.employees import EmployeeCreate, EmployeeOut, EmployeeUpdate, LinkAccountRequest
from app.services.audit import record_audit_event

router = APIRouter(prefix="/employees", tags=["employees"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)
_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)


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
    db.flush()
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


@router.get("/{employee_id}/bank-account", response_model=BankAccountOut | None)
def get_bank_account(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> BankAccount | None:
    _get_employee_or_404(db, employee_id)
    return db.scalar(select(BankAccount).where(BankAccount.employee_id == employee_id))


@router.put("/{employee_id}/bank-account", response_model=BankAccountOut)
def upsert_bank_account(
    employee_id: uuid.UUID,
    body: BankAccountInput,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> BankAccount:
    """One row per employee — a resubmission replaces the prior details
    rather than accumulating history, matching BankAccount's own docstring
    ('one active account per employee for this phase'). verified reflects
    only that the check digit matched a *known* bank's algorithm — never a
    live account-name lookup against the bank itself."""
    employee = _get_employee_or_404(db, employee_id)
    bank_account = db.scalar(select(BankAccount).where(BankAccount.employee_id == employee_id))
    is_known_bank = body.bank_name in NIGERIAN_BANKS
    if bank_account is None:
        bank_account = BankAccount(org_id=claims.org_id, employee_id=employee.id)
    bank_account.bank_name = body.bank_name
    bank_account.account_number = body.account_number
    bank_account.account_name = body.account_name
    bank_account.verified = is_known_bank
    db.add(bank_account)
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="employee.bank_account.update",
        entity_type="employee",
        entity_id=employee.id,
        metadata={"bank_name": body.bank_name, "verified": is_known_bank},
    )
    return bank_account
