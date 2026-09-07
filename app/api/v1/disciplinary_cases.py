import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.disciplinary_case import DisciplinaryCase
from app.models.employee import Employee
from app.models.membership import Role
from app.schemas.disciplinary_cases import (
    DisciplinaryCaseCreate,
    DisciplinaryCaseOut,
    DisciplinaryCaseResolve,
    DisciplinaryCaseUpdate,
)
from app.services.disciplinary_cases import register_disciplinary_case, resolve_disciplinary_case

router = APIRouter(prefix="/disciplinary-cases", tags=["employee-relations"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)
_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)
_RESOLVE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_case_or_404(db: Session, case_id: uuid.UUID) -> DisciplinaryCase:
    case = db.get(DisciplinaryCase, case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="disciplinary case not found"
        )
    return case


def _requester_can_manage(db: Session, claims: TokenClaims, case: DisciplinaryCase) -> None:
    """ADMIN/PAYROLL_MANAGER can manage any case; a MANAGER only one for
    their own direct report."""
    if claims.role in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value):
        return
    if claims.role == Role.MANAGER.value:
        manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
        employee = db.get(Employee, case.employee_id)
        if manager is not None and employee is not None and employee.manager_id == manager.id:
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="not authorised to manage this case"
    )


@router.post("", response_model=DisciplinaryCaseOut, status_code=status.HTTP_201_CREATED)
def create_disciplinary_case(
    body: DisciplinaryCaseCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> DisciplinaryCase:
    if claims.role == Role.MANAGER.value:
        manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
        employee = db.get(Employee, body.employee_id)
        if manager is None or employee is None or employee.manager_id != manager.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not authorised to open a case for this employee",
            )
    return register_disciplinary_case(db, org_id=claims.org_id, **body.model_dump())


@router.get("", response_model=list[DisciplinaryCaseOut])
def list_disciplinary_cases(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_VIEW_LIST)
) -> list[DisciplinaryCase]:
    if claims.role in (Role.ADMIN.value, Role.PAYROLL_MANAGER.value):
        return list(db.scalars(select(DisciplinaryCase)))

    manager = db.scalar(select(Employee).where(Employee.account_id == claims.account_id))
    if manager is None:
        return []
    report_ids = select(Employee.id).where(Employee.manager_id == manager.id)
    return list(
        db.scalars(select(DisciplinaryCase).where(DisciplinaryCase.employee_id.in_(report_ids)))
    )


@router.get("/{case_id}", response_model=DisciplinaryCaseOut)
def get_disciplinary_case(
    case_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_VIEW_LIST),
) -> DisciplinaryCase:
    case = _get_case_or_404(db, case_id)
    _requester_can_manage(db, claims, case)
    return case


@router.patch("/{case_id}", response_model=DisciplinaryCaseOut)
def update_disciplinary_case(
    case_id: uuid.UUID,
    body: DisciplinaryCaseUpdate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> DisciplinaryCase:
    case = _get_case_or_404(db, case_id)
    _requester_can_manage(db, claims, case)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(case, field, value)
    db.add(case)
    db.flush()
    return case


@router.post("/{case_id}/resolve", response_model=DisciplinaryCaseOut)
def resolve_case(
    case_id: uuid.UUID,
    body: DisciplinaryCaseResolve,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_RESOLVE),
) -> DisciplinaryCase:
    case = _get_case_or_404(db, case_id)
    try:
        resolve_disciplinary_case(db, case, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    return case
