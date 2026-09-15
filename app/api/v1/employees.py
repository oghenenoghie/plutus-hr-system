import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.domain.nuban import NIGERIAN_BANKS
from app.domain.salary_masking import mask_compensation
from app.models.bank_account import BankAccount
from app.models.department import Department
from app.models.employee import Employee
from app.models.employee_history_event import EmployeeHistoryEvent
from app.models.employee_login_code import EmployeeLoginCode
from app.models.membership import Role
from app.schemas.bank_account import BankAccountInput, BankAccountOut
from app.schemas.employees import (
    EmployeeBulkImportRequest,
    EmployeeBulkImportResult,
    EmployeeBulkImportRowError,
    EmployeeCreate,
    EmployeeHistoryEventOut,
    EmployeeOut,
    EmployeeUpdate,
    LinkAccountRequest,
)
from app.services.audit import record_audit_event
from app.services.employee_history import record_compensation_change
from app.services.employee_import import bulk_import_employees
from app.services.employee_provisioning import assign_unique_login_code

router = APIRouter(prefix="/employees", tags=["employees"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT)
_VIEW_LIST = require_roles(
    Role.ADMIN,
    Role.PAYROLL_MANAGER,
    Role.ACCOUNTANT,
    Role.MANAGER,
    Role.HR_MANAGER,
    Role.DEPARTMENT_MANAGER,
    Role.AUDITOR,
)
# Roles that can see any employee's record (not just their own direct
# reports) but never their compensation figures — HR Manager owns
# onboarding/records, not pay; Auditor is read-only everywhere. Kept
# separate from MASKED-for-a-direct-report (below), which is conditional
# on that employee's own salary_masked flag rather than unconditional.
_ALWAYS_MASKED_ROLES = frozenset({Role.HR_MANAGER.value, Role.AUDITOR.value})


def _assign_unique_login_code(db: Session, employee: Employee) -> None:
    if not assign_unique_login_code(db, employee):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="could not assign a unique login code — try again",
        )


def _get_employee_or_404(db: Session, employee_id: uuid.UUID) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")
    return employee


def _department_ids_headed_by(db: Session, employee_id: uuid.UUID) -> list[uuid.UUID]:
    return list(db.scalars(select(Department.id).where(Department.manager_id == employee_id)))


def _require_visible(db: Session, claims: TokenClaims, employee: Employee) -> Employee:
    """ADMIN/PAYROLL_MANAGER/ACCOUNTANT/HR_MANAGER/AUDITOR can see anyone
    (compensation masking is decided separately, in _serialize); MANAGER
    only their own direct reports; DEPARTMENT_MANAGER only employees in the
    department(s) they head; anyone else (EMPLOYEE) gets 404 rather than a
    403 that would confirm the record exists."""
    if claims.role in (
        Role.ADMIN.value,
        Role.PAYROLL_MANAGER.value,
        Role.ACCOUNTANT.value,
        Role.HR_MANAGER.value,
        Role.AUDITOR.value,
    ):
        return employee
    if claims.role == Role.MANAGER.value:
        manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
        if manager is not None and employee.manager_id == manager.id:
            return employee
    if claims.role == Role.DEPARTMENT_MANAGER.value:
        head = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
        if (
            head is not None
            and employee.department_id is not None
            and employee.department_id in _department_ids_headed_by(db, head.id)
        ):
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


@router.post("/bulk-import", response_model=EmployeeBulkImportResult)
def bulk_import(
    body: EmployeeBulkImportRequest,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> EmployeeBulkImportResult:
    result = bulk_import_employees(db, org_id=claims.org_id, csv_content=body.csv_content)
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="employee.bulk_import",
        entity_type="employee",
        metadata={"created": len(result.created), "row_errors": len(result.row_errors)},
    )
    return EmployeeBulkImportResult(
        created=[_serialize(e, mask=False) for e in result.created],
        row_errors=[
            EmployeeBulkImportRowError(row=e.row, employee_number=e.employee_number, error=e.error)
            for e in result.row_errors
        ],
    )


def _serialize(employee: Employee, *, mask: bool) -> EmployeeOut:
    """Masking hides compensation from *other* viewers, never from
    ADMIN/PAYROLL_MANAGER (who manage pay) or from the employee's own
    self-service view — only a MANAGER looking at someone else's record
    (their direct report, and only when that employee opted into masking)
    via list/get ever sees nulled-out figures. The caller decides mask."""
    out = EmployeeOut.model_validate(employee)
    return out.model_copy(update=mask_compensation(out.model_dump(), mask=mask))


@router.get("", response_model=list[EmployeeOut])
def list_employees(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_VIEW_LIST)
) -> list[EmployeeOut]:
    if claims.role in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value, Role.ACCOUNTANT.value):
        return [_serialize(e, mask=False) for e in db.scalars(select(Employee))]

    if claims.role in _ALWAYS_MASKED_ROLES:
        # HR Manager / Auditor: org-wide visibility, compensation always
        # masked — never conditional on the employee's own salary_masked
        # flag, unlike the MANAGER case below.
        return [_serialize(e, mask=True) for e in db.scalars(select(Employee))]

    self_employee = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
    if self_employee is None:
        return []

    if claims.role == Role.DEPARTMENT_MANAGER.value:
        dept_ids = _department_ids_headed_by(db, self_employee.id)
        if not dept_ids:
            return []
        scoped = db.scalars(select(Employee).where(Employee.department_id.in_(dept_ids)))
        return [_serialize(e, mask=True) for e in scoped]

    reports = db.scalars(select(Employee).where(Employee.manager_id == self_employee.id))
    # A MANAGER sees that a report exists, their title, department, etc.,
    # but not the exact pay figures for a report who opted into masking —
    # those stay ADMIN/PAYROLL_MANAGER (or the employee's own /me) only.
    return [_serialize(e, mask=e.salary_masked) for e in reports]


@router.get("/me", response_model=EmployeeOut)
def get_my_employee_record(employee: Employee = Depends(get_current_employee)) -> EmployeeOut:
    return _serialize(employee, mask=False)


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> EmployeeOut:
    employee = _get_employee_or_404(db, employee_id)
    employee = _require_visible(db, claims, employee)
    always_masked = claims.role in _ALWAYS_MASKED_ROLES or claims.role == Role.DEPARTMENT_MANAGER.value
    mask = always_masked or (employee.salary_masked and claims.role == Role.MANAGER.value)
    return _serialize(employee, mask=mask)


@router.patch("/{employee_id}", response_model=EmployeeOut)
def update_employee(
    employee_id: uuid.UUID,
    body: EmployeeUpdate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Employee:
    employee = _get_employee_or_404(db, employee_id)
    changed_fields = body.model_dump(exclude_unset=True)
    before = {field: getattr(employee, field) for field in changed_fields}
    for field, value in changed_fields.items():
        setattr(employee, field, value)
    if "contract_end_date" in changed_fields and changed_fields["contract_end_date"] != before.get(
        "contract_end_date"
    ):
        # A changed end date (e.g. a renewal) is a new expiry to alert on —
        # restart app.services.reminders' once-per-date alert cycle.
        employee.contract_expiry_notified = False
    db.add(employee)
    record_compensation_change(
        db,
        org_id=claims.org_id,
        employee_id=employee.id,
        before=before,
        after=changed_fields,
        effective_date=datetime.now(UTC).date(),
        recorded_by=claims.account_id,
    )
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


@router.get("/{employee_id}/history", response_model=list[EmployeeHistoryEventOut])
def get_employee_history(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> list[EmployeeHistoryEvent]:
    employee = _get_employee_or_404(db, employee_id)
    _require_visible(db, claims, employee)
    return list(
        db.scalars(
            select(EmployeeHistoryEvent)
            .where(EmployeeHistoryEvent.employee_id == employee_id)
            .order_by(EmployeeHistoryEvent.created_at)
        )
    )


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
