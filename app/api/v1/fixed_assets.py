import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_current_employee, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.employee import Employee
from app.models.fixed_asset import FixedAsset
from app.models.fixed_asset_assignment import FixedAssetAssignment
from app.models.membership import Role
from app.schemas.fixed_assets import (
    FixedAssetAssignmentCreate,
    FixedAssetAssignmentOut,
    FixedAssetAssignmentReturn,
    FixedAssetCreate,
    FixedAssetDispose,
    FixedAssetOut,
    FixedAssetRevalueRequest,
    FixedAssetTransferRequest,
    MyFixedAssetOut,
)
from app.services.audit import record_audit_event
from app.services.fixed_assets import (
    assign_fixed_asset,
    dispose_fixed_asset,
    record_depreciation,
    register_fixed_asset,
    return_fixed_asset,
    revalue_fixed_asset,
    run_batch_depreciation,
    transfer_fixed_asset,
)

router = APIRouter(prefix="/fixed-assets", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT)


def _get_fixed_asset_or_404(db: Session, fixed_asset_id: uuid.UUID) -> FixedAsset:
    asset = db.get(FixedAsset, fixed_asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="fixed asset not found")
    return asset


def _get_assignment_or_404(db: Session, assignment_id: uuid.UUID) -> FixedAssetAssignment:
    assignment = db.get(FixedAssetAssignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment not found")
    return assignment


@router.post("", response_model=FixedAssetOut, status_code=status.HTTP_201_CREATED)
def create_fixed_asset(
    body: FixedAssetCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> FixedAsset:
    try:
        asset = register_fixed_asset(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a fixed asset with this tag already exists",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="fixed_asset.create",
        entity_type="fixed_asset",
        entity_id=asset.id,
        metadata={"asset_tag": asset.asset_tag, "name": asset.name},
    )
    return asset


@router.get("", response_model=list[FixedAssetOut])
def list_fixed_assets(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[FixedAsset]:
    return list(db.scalars(select(FixedAsset).order_by(FixedAsset.acquisition_date.desc())))


@router.get("/me", response_model=list[MyFixedAssetOut])
def list_my_assigned_fixed_assets(
    db: Session = Depends(get_tenant_db), employee: Employee = Depends(get_current_employee)
) -> list[MyFixedAssetOut]:
    """Self-service: what fixed assets I currently hold. Registered ahead
    of GET /{fixed_asset_id} so "me" isn't swallowed as a path param, same
    as the retired /company-assets/me it replaces. Deliberately not
    _MANAGE-gated like the rest of this router — any employee can see
    their own assignments — and deliberately doesn't reuse FixedAssetOut,
    which would leak cost/depreciation figures to non-finance roles.
    """
    rows = db.execute(
        select(FixedAssetAssignment, FixedAsset)
        .join(FixedAsset, FixedAsset.id == FixedAssetAssignment.fixed_asset_id)
        .where(
            FixedAssetAssignment.employee_id == employee.id,
            FixedAssetAssignment.returned_date.is_(None),
        )
    ).all()
    return [
        MyFixedAssetOut(
            assignment_id=assignment.id,
            fixed_asset_id=asset.id,
            name=asset.name,
            asset_tag=asset.asset_tag,
            category=asset.category,
            assigned_date=assignment.assigned_date,
        )
        for assignment, asset in rows
    ]


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
    claims: TokenClaims = Depends(_MANAGE),
) -> FixedAsset:
    asset = _get_fixed_asset_or_404(db, fixed_asset_id)
    try:
        depreciated = record_depreciation(db, asset)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="fixed_asset.depreciate",
        entity_type="fixed_asset",
        entity_id=depreciated.id,
    )
    return depreciated


@router.post("/{fixed_asset_id}/dispose", response_model=FixedAssetOut)
def dispose(
    fixed_asset_id: uuid.UUID,
    body: FixedAssetDispose,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> FixedAsset:
    asset = _get_fixed_asset_or_404(db, fixed_asset_id)
    try:
        disposed = dispose_fixed_asset(db, asset, proceeds_minor=body.proceeds_minor)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="fixed_asset.dispose",
        entity_type="fixed_asset",
        entity_id=disposed.id,
        metadata={"proceeds_minor": body.proceeds_minor},
    )
    return disposed


@router.post("/{fixed_asset_id}/transfer", response_model=FixedAssetOut)
def transfer(
    fixed_asset_id: uuid.UUID,
    body: FixedAssetTransferRequest,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> FixedAsset:
    asset = _get_fixed_asset_or_404(db, fixed_asset_id)
    try:
        transferred = transfer_fixed_asset(db, asset, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="fixed_asset.transfer",
        entity_type="fixed_asset",
        entity_id=transferred.id,
    )
    return transferred


@router.post("/{fixed_asset_id}/revalue", response_model=FixedAssetOut)
def revalue(
    fixed_asset_id: uuid.UUID,
    body: FixedAssetRevalueRequest,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> FixedAsset:
    asset = _get_fixed_asset_or_404(db, fixed_asset_id)
    try:
        revalued = revalue_fixed_asset(db, asset, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="fixed_asset.revalue",
        entity_type="fixed_asset",
        entity_id=revalued.id,
    )
    return revalued


@router.post("/batch-depreciation", response_model=list[FixedAssetOut])
def batch_depreciate(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_MANAGE)
) -> list[FixedAsset]:
    depreciated = run_batch_depreciation(db, claims.org_id)
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="fixed_asset.batch_depreciate",
        entity_type="fixed_asset",
        metadata={"count": len(depreciated)},
    )
    return depreciated


@router.post(
    "/{fixed_asset_id}/assignments",
    response_model=FixedAssetAssignmentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_assignment(
    fixed_asset_id: uuid.UUID,
    body: FixedAssetAssignmentCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> FixedAssetAssignment:
    asset = _get_fixed_asset_or_404(db, fixed_asset_id)
    try:
        assignment = assign_fixed_asset(db, asset, org_id=claims.org_id, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="fixed_asset.assign",
        entity_type="fixed_asset",
        entity_id=asset.id,
        metadata={"employee_id": str(body.employee_id)},
    )
    return assignment


@router.get("/{fixed_asset_id}/assignments", response_model=list[FixedAssetAssignmentOut])
def list_assignments_for_asset(
    fixed_asset_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[FixedAssetAssignment]:
    _get_fixed_asset_or_404(db, fixed_asset_id)
    return list(
        db.scalars(
            select(FixedAssetAssignment).where(
                FixedAssetAssignment.fixed_asset_id == fixed_asset_id
            )
        )
    )


@router.post("/assignments/{assignment_id}/return", response_model=FixedAssetAssignmentOut)
def return_assignment(
    assignment_id: uuid.UUID,
    body: FixedAssetAssignmentReturn,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> FixedAssetAssignment:
    assignment = _get_assignment_or_404(db, assignment_id)
    asset = _get_fixed_asset_or_404(db, assignment.fixed_asset_id)
    try:
        returned = return_fixed_asset(db, assignment, asset, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="fixed_asset.return",
        entity_type="fixed_asset",
        entity_id=asset.id,
    )
    return returned
