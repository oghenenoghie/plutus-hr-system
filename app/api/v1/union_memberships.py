import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee
from app.models.membership import Role
from app.models.union_membership import UnionMembership
from app.schemas.union_memberships import (
    UnionMembershipCreate,
    UnionMembershipOut,
    UnionMembershipTerminate,
    UnionMembershipUpdate,
)
from app.services.union_memberships import register_union_membership, terminate_union_membership

router = APIRouter(prefix="/union-memberships", tags=["union-dues"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_membership_or_404(db: Session, membership_id: uuid.UUID) -> UnionMembership:
    membership = db.get(UnionMembership, membership_id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="union membership not found"
        )
    return membership


@router.post(
    "/employees/{employee_id}",
    response_model=UnionMembershipOut,
    status_code=status.HTTP_201_CREATED,
)
def assign_union_membership(
    employee_id: uuid.UUID,
    body: UnionMembershipCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> UnionMembership:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")

    try:
        return register_union_membership(
            db, org_id=claims.org_id, employee_id=employee_id, **body.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/employees/{employee_id}", response_model=list[UnionMembershipOut])
def list_employee_union_memberships(
    employee_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[UnionMembership]:
    return list(
        db.scalars(select(UnionMembership).where(UnionMembership.employee_id == employee_id))
    )


@router.get("/me", response_model=list[UnionMembershipOut])
def list_my_union_memberships(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> list[UnionMembership]:
    return list(
        db.scalars(select(UnionMembership).where(UnionMembership.employee_id == employee.id))
    )


@router.patch("/{membership_id}", response_model=UnionMembershipOut)
def update_union_membership(
    membership_id: uuid.UUID,
    body: UnionMembershipUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> UnionMembership:
    membership = _get_membership_or_404(db, membership_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(membership, field, value)
    db.add(membership)
    db.flush()
    return membership


@router.post("/{membership_id}/terminate", response_model=UnionMembershipOut)
def terminate_membership(
    membership_id: uuid.UUID,
    body: UnionMembershipTerminate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> UnionMembership:
    membership = _get_membership_or_404(db, membership_id)
    try:
        terminate_union_membership(db, membership, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    return membership
