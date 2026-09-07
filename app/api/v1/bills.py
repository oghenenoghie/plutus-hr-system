import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.bill import Bill
from app.models.membership import Role
from app.schemas.bills import BillCreate, BillOut
from app.services.bills import approve_bill, pay_bill, register_bill, void_bill

router = APIRouter(prefix="/bills", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_bill_or_404(db: Session, bill_id: uuid.UUID) -> Bill:
    bill = db.get(Bill, bill_id)
    if bill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bill not found")
    return bill


@router.post("", response_model=BillOut, status_code=status.HTTP_201_CREATED)
def create_bill(
    body: BillCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Bill:
    try:
        return register_bill(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a bill with this number already exists for this vendor",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[BillOut])
def list_bills(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[Bill]:
    return list(db.scalars(select(Bill).order_by(Bill.bill_date.desc())))


@router.get("/{bill_id}", response_model=BillOut)
def get_bill(
    bill_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Bill:
    return _get_bill_or_404(db, bill_id)


@router.post("/{bill_id}/approve", response_model=BillOut)
def approve(
    bill_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Bill:
    bill = _get_bill_or_404(db, bill_id)
    try:
        return approve_bill(db, bill)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{bill_id}/pay", response_model=BillOut)
def pay(
    bill_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Bill:
    bill = _get_bill_or_404(db, bill_id)
    try:
        return pay_bill(db, bill)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{bill_id}/void", response_model=BillOut)
def void(
    bill_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Bill:
    bill = _get_bill_or_404(db, bill_id)
    try:
        return void_bill(db, bill)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
