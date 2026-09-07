import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.asset_assignment import AssetAssignment
from app.models.company_asset import CompanyAsset
from app.models.employee import Employee
from app.models.membership import Role
from app.schemas.asset_assignments import (
    AssetAssignmentCreate,
    AssetAssignmentOut,
    AssetAssignmentReturn,
)
from app.schemas.company_assets import CompanyAssetCreate, CompanyAssetOut, CompanyAssetUpdate
from app.services.asset_assignments import assign_asset, return_asset
from app.services.company_assets import register_company_asset

router = APIRouter(prefix="/company-assets", tags=["assets"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)
_VIEW_LIST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER)
_VIEW_CATALOG = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.MANAGER, Role.EMPLOYEE)


def _get_asset_or_404(db: Session, asset_id: uuid.UUID) -> CompanyAsset:
    asset = db.get(CompanyAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
    return asset


def _get_assignment_or_404(db: Session, assignment_id: uuid.UUID) -> AssetAssignment:
    assignment = db.get(AssetAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment not found")
    return assignment


@router.post("", response_model=CompanyAssetOut, status_code=status.HTTP_201_CREATED)
def create_company_asset(
    body: CompanyAssetCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> CompanyAsset:
    try:
        return register_company_asset(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="an asset with this tag already exists",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[CompanyAssetOut])
def list_company_assets(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_VIEW_CATALOG)
) -> list[CompanyAsset]:
    return list(db.scalars(select(CompanyAsset)))


@router.get("/me", response_model=list[AssetAssignmentOut])
def list_my_assigned_assets(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> list[AssetAssignment]:
    return list(
        db.scalars(
            select(AssetAssignment).where(
                AssetAssignment.employee_id == employee.id,
                AssetAssignment.returned_date.is_(None),
            )
        )
    )


@router.get("/{asset_id}", response_model=CompanyAssetOut)
def get_company_asset(
    asset_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW_CATALOG),
) -> CompanyAsset:
    return _get_asset_or_404(db, asset_id)


@router.patch("/{asset_id}", response_model=CompanyAssetOut)
def update_company_asset(
    asset_id: uuid.UUID,
    body: CompanyAssetUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> CompanyAsset:
    asset = _get_asset_or_404(db, asset_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(asset, field, value)
    db.add(asset)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="an asset with this tag already exists",
        ) from exc
    return asset


@router.post(
    "/{asset_id}/assignments",
    response_model=AssetAssignmentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_assignment(
    asset_id: uuid.UUID,
    body: AssetAssignmentCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> AssetAssignment:
    asset = _get_asset_or_404(db, asset_id)
    try:
        return assign_asset(db, asset, org_id=claims.org_id, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{asset_id}/assignments", response_model=list[AssetAssignmentOut])
def list_assignments_for_asset(
    asset_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_VIEW_LIST),
) -> list[AssetAssignment]:
    _get_asset_or_404(db, asset_id)
    return list(db.scalars(select(AssetAssignment).where(AssetAssignment.asset_id == asset_id)))


@router.post("/assignments/{assignment_id}/return", response_model=AssetAssignmentOut)
def return_assignment(
    assignment_id: uuid.UUID,
    body: AssetAssignmentReturn,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> AssetAssignment:
    assignment = _get_assignment_or_404(db, assignment_id)
    asset = _get_asset_or_404(db, assignment.asset_id)
    try:
        return return_asset(db, assignment, asset, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
