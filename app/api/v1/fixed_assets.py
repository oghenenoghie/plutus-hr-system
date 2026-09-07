import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.fixed_asset import FixedAsset
from app.models.membership import Role
from app.schemas.fixed_assets import FixedAssetCreate, FixedAssetDispose, FixedAssetOut
from app.services.fixed_assets import dispose_fixed_asset, record_depreciation, register_fixed_asset

router = APIRouter(prefix="/fixed-assets", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_fixed_asset_or_404(db: Session, fixed_asset_id: uuid.UUID) -> FixedAsset:
    asset = db.get(FixedAsset, fixed_asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="fixed asset not found")
    return asset


@router.post("", response_model=FixedAssetOut, status_code=status.HTTP_201_CREATED)
def create_fixed_asset(
    body: FixedAssetCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> FixedAsset:
    try:
        return register_fixed_asset(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a fixed asset with this tag already exists",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[FixedAssetOut])
def list_fixed_assets(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[FixedAsset]:
    return list(db.scalars(select(FixedAsset).order_by(FixedAsset.acquisition_date.desc())))


@router.get("/{fixed_asset_id}", response_model=FixedAssetOut)
def get_fixed_asset(
    fixed_asset_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> FixedAsset:
    return _get_fixed_asset_or_404(db, fixed_asset_id)


@router.post("/{fixed_asset_id}/depreciate", response_model=FixedAssetOut)
def depreciate(
    fixed_asset_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> FixedAsset:
    asset = _get_fixed_asset_or_404(db, fixed_asset_id)
    try:
        return record_depreciation(db, asset)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{fixed_asset_id}/dispose", response_model=FixedAssetOut)
def dispose(
    fixed_asset_id: uuid.UUID,
    body: FixedAssetDispose,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> FixedAsset:
    asset = _get_fixed_asset_or_404(db, fixed_asset_id)
    try:
        return dispose_fixed_asset(db, asset, proceeds_minor=body.proceeds_minor)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
