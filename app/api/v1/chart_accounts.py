import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.chart_account import ChartAccount
from app.models.membership import Role
from app.schemas.chart_accounts import ChartAccountCreate, ChartAccountOut, ChartAccountUpdate
from app.services.chart_accounts import register_chart_account, seed_default_chart_of_accounts

router = APIRouter(prefix="/chart-of-accounts", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_account_or_404(db: Session, account_id: uuid.UUID) -> ChartAccount:
    account = db.get(ChartAccount, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found")
    return account


@router.post("", response_model=ChartAccountOut, status_code=status.HTTP_201_CREATED)
def create_chart_account(
    body: ChartAccountCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> ChartAccount:
    try:
        return register_chart_account(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="an account with this code already exists",
        ) from exc


@router.post("/seed-defaults", response_model=list[ChartAccountOut])
def seed_defaults(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_MANAGE)
) -> list[ChartAccount]:
    return seed_default_chart_of_accounts(db, org_id=claims.org_id)


@router.get("", response_model=list[ChartAccountOut])
def list_chart_accounts(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[ChartAccount]:
    return list(db.scalars(select(ChartAccount).order_by(ChartAccount.code)))


@router.get("/{account_id}", response_model=ChartAccountOut)
def get_chart_account(
    account_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> ChartAccount:
    return _get_account_or_404(db, account_id)


@router.patch("/{account_id}", response_model=ChartAccountOut)
def update_chart_account(
    account_id: uuid.UUID,
    body: ChartAccountUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> ChartAccount:
    account = _get_account_or_404(db, account_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    db.add(account)
    db.flush()
    return account
