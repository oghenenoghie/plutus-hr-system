import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.invoice import Invoice
from app.models.membership import Role
from app.schemas.invoices import InvoiceCreate, InvoiceOut
from app.services.invoices import (
    record_invoice_payment,
    register_invoice,
    send_invoice,
    void_invoice,
)

router = APIRouter(prefix="/invoices", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_invoice_or_404(db: Session, invoice_id: uuid.UUID) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invoice not found")
    return invoice


@router.post("", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def create_invoice(
    body: InvoiceCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Invoice:
    try:
        return register_invoice(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="an invoice with this number already exists for this customer",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[InvoiceOut])
def list_invoices(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[Invoice]:
    return list(db.scalars(select(Invoice).order_by(Invoice.issue_date.desc())))


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Invoice:
    return _get_invoice_or_404(db, invoice_id)


@router.post("/{invoice_id}/send", response_model=InvoiceOut)
def send(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Invoice:
    invoice = _get_invoice_or_404(db, invoice_id)
    try:
        return send_invoice(db, invoice)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{invoice_id}/pay", response_model=InvoiceOut)
def pay(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Invoice:
    invoice = _get_invoice_or_404(db, invoice_id)
    try:
        return record_invoice_payment(db, invoice)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{invoice_id}/void", response_model=InvoiceOut)
def void(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Invoice:
    invoice = _get_invoice_or_404(db, invoice_id)
    try:
        return void_invoice(db, invoice)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
