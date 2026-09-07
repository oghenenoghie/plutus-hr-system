import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.branch import Branch
from app.models.membership import Role
from app.schemas.branches import BranchCreate, BranchOut, BranchUpdate
from app.services.branches import register_branch

router = APIRouter(prefix="/branches", tags=["branches"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)
_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)


def _get_branch_or_404(db: Session, branch_id: uuid.UUID) -> Branch:
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="branch not found")
    return branch


@router.post("", response_model=BranchOut, status_code=status.HTTP_201_CREATED)
def create_branch(
    body: BranchCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Branch:
    try:
        return register_branch(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a branch with this name already exists",
        ) from exc


@router.get("", response_model=list[BranchOut])
def list_branches(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_VIEW_LIST)
) -> list[Branch]:
    return list(db.scalars(select(Branch)))


@router.get("/{branch_id}", response_model=BranchOut)
def get_branch(
    branch_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW_LIST),
) -> Branch:
    return _get_branch_or_404(db, branch_id)


@router.patch("/{branch_id}", response_model=BranchOut)
def update_branch(
    branch_id: uuid.UUID,
    body: BranchUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Branch:
    branch = _get_branch_or_404(db, branch_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(branch, field, value)
    db.add(branch)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a branch with this name already exists",
        ) from exc
    return branch
