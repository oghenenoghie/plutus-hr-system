import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.models.policy import Policy
from app.schemas.policies import PolicyCreate, PolicyOut, PolicyUpdate
from app.services.policies import register_policy

router = APIRouter(prefix="/policies", tags=["policies"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)
_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER, Role.EMPLOYEE)


def _get_policy_or_404(db: Session, policy_id: uuid.UUID) -> Policy:
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="policy not found")
    return policy


@router.post("", response_model=PolicyOut, status_code=status.HTTP_201_CREATED)
def create_policy(
    body: PolicyCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Policy:
    try:
        return register_policy(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a policy with this title already exists",
        ) from exc


@router.get("", response_model=list[PolicyOut])
def list_policies(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_VIEW_LIST)
) -> list[Policy]:
    return list(db.scalars(select(Policy)))


@router.get("/{policy_id}", response_model=PolicyOut)
def get_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW_LIST),
) -> Policy:
    return _get_policy_or_404(db, policy_id)


@router.patch("/{policy_id}", response_model=PolicyOut)
def update_policy(
    policy_id: uuid.UUID,
    body: PolicyUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Policy:
    policy = _get_policy_or_404(db, policy_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(policy, field, value)
    db.add(policy)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a policy with this title already exists",
        ) from exc
    return policy
