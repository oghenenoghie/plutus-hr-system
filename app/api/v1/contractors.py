import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.resolver import resolve_rule_version
from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.contractor import Contractor
from app.models.membership import Role
from app.models.wht_payment import WhtPayment
from app.schemas.contractors import (
    ContractorCreate,
    ContractorOut,
    ContractorUpdate,
    WhtPaymentCreate,
    WhtPaymentOut,
)
from app.services.contractors import register_contractor
from app.services.wht import MissingContractorTinError, record_contractor_payment

# Same single-country assumption as app.services.payroll — Nigeria is the
# only rule set that exists yet.
_COUNTRY = "NG"

router = APIRouter(prefix="/contractors", tags=["contractors"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_contractor_or_404(db: Session, contractor_id: uuid.UUID) -> Contractor:
    contractor = db.get(Contractor, contractor_id)
    if contractor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="contractor not found")
    return contractor


@router.post("", response_model=ContractorOut, status_code=status.HTTP_201_CREATED)
def create_contractor(
    body: ContractorCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Contractor:
    return register_contractor(db, org_id=claims.org_id, **body.model_dump())


@router.get("", response_model=list[ContractorOut])
def list_contractors(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[Contractor]:
    return list(db.scalars(select(Contractor)))


@router.get("/{contractor_id}", response_model=ContractorOut)
def get_contractor(
    contractor_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Contractor:
    return _get_contractor_or_404(db, contractor_id)


@router.patch("/{contractor_id}", response_model=ContractorOut)
def update_contractor(
    contractor_id: uuid.UUID,
    body: ContractorUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Contractor:
    contractor = _get_contractor_or_404(db, contractor_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(contractor, field, value)
    db.add(contractor)
    db.flush()
    return contractor


@router.post(
    "/{contractor_id}/payments",
    response_model=WhtPaymentOut,
    status_code=status.HTTP_201_CREATED,
)
def record_payment(
    contractor_id: uuid.UUID,
    body: WhtPaymentCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> WhtPayment:
    contractor = _get_contractor_or_404(db, contractor_id)
    rules = resolve_rule_version(_COUNTRY, body.payment_date)
    try:
        return record_contractor_payment(
            db,
            org_id=claims.org_id,
            contractor=contractor,
            category=body.category,
            gross_amount_minor=body.gross_amount_minor,
            payment_date=body.payment_date,
            rules=rules,
        )
    except (MissingContractorTinError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{contractor_id}/payments", response_model=list[WhtPaymentOut])
def list_payments(
    contractor_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[WhtPayment]:
    _get_contractor_or_404(db, contractor_id)
    return list(
        db.scalars(
            select(WhtPayment)
            .where(WhtPayment.contractor_id == contractor_id)
            .order_by(WhtPayment.payment_date.desc())
        )
    )
