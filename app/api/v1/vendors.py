import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.models.vendor import Vendor
from app.schemas.vendors import VendorCreate, VendorOut, VendorUpdate
from app.services.vendors import register_vendor

router = APIRouter(prefix="/vendors", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_vendor_or_404(db: Session, vendor_id: uuid.UUID) -> Vendor:
    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vendor not found")
    return vendor


@router.post("", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
def create_vendor(
    body: VendorCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Vendor:
    try:
        return register_vendor(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a vendor with this name already exists",
        ) from exc


@router.get("", response_model=list[VendorOut])
def list_vendors(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[Vendor]:
    return list(db.scalars(select(Vendor).order_by(Vendor.name)))


@router.get("/{vendor_id}", response_model=VendorOut)
def get_vendor(
    vendor_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Vendor:
    return _get_vendor_or_404(db, vendor_id)


@router.patch("/{vendor_id}", response_model=VendorOut)
def update_vendor(
    vendor_id: uuid.UUID,
    body: VendorUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Vendor:
    vendor = _get_vendor_or_404(db, vendor_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(vendor, field, value)
    db.add(vendor)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a vendor with this name already exists",
        ) from exc
    return vendor
