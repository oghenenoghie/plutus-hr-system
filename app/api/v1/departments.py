import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.department import Department
from app.models.membership import Role
from app.schemas.departments import DepartmentCreate, DepartmentOut, DepartmentUpdate
from app.services.departments import register_department

router = APIRouter(prefix="/departments", tags=["departments"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)
_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)


def _get_department_or_404(db: Session, department_id: uuid.UUID) -> Department:
    department = db.get(Department, department_id)
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="department not found")
    return department


@router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(
    body: DepartmentCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Department:
    try:
        return register_department(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a department with this name already exists",
        ) from exc


@router.get("", response_model=list[DepartmentOut])
def list_departments(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_VIEW_LIST)
) -> list[Department]:
    return list(db.scalars(select(Department)))


@router.get("/{department_id}", response_model=DepartmentOut)
def get_department(
    department_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW_LIST),
) -> Department:
    return _get_department_or_404(db, department_id)


@router.patch("/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: uuid.UUID,
    body: DepartmentUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Department:
    department = _get_department_or_404(db, department_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(department, field, value)
    db.add(department)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a department with this name already exists",
        ) from exc
    return department
