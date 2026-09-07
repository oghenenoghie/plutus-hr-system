import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.models.statutory_liability import StatutoryLiability
from app.schemas.statutory_liabilities import RemitRequest, StatutoryLiabilityOut
from app.services.statutory_liability import mark_liability_filed, mark_liability_remitted

router = APIRouter(prefix="/statutory-liabilities", tags=["statutory-liabilities"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_or_404(db: Session, liability_id: uuid.UUID) -> StatutoryLiability:
    liability = db.get(StatutoryLiability, liability_id)
    if liability is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="liability not found")
    return liability


@router.get("", response_model=list[StatutoryLiabilityOut])
def list_liabilities(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[StatutoryLiability]:
    return list(db.scalars(select(StatutoryLiability).order_by(StatutoryLiability.due_date)))


@router.post("/{liability_id}/file", response_model=StatutoryLiabilityOut)
def file_liability(
    liability_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> StatutoryLiability:
    liability = _get_or_404(db, liability_id)
    try:
        mark_liability_filed(db, liability)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    return liability


@router.post("/{liability_id}/remit", response_model=StatutoryLiabilityOut)
def remit_liability(
    liability_id: uuid.UUID,
    body: RemitRequest,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> StatutoryLiability:
    liability = _get_or_404(db, liability_id)
    try:
        mark_liability_remitted(db, liability, reference=body.reference)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    return liability
