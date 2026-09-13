import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.credit_note import CreditNote
from app.models.invoice import Invoice
from app.models.membership import Role
from app.schemas.credit_notes import CreditNoteCreate, CreditNoteOut
from app.services.credit_notes import issue_credit_note

router = APIRouter(prefix="/invoices", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_invoice_or_404(db: Session, invoice_id: uuid.UUID) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invoice not found")
    return invoice


@router.post(
    "/{invoice_id}/credit-notes",
    response_model=CreditNoteOut,
    status_code=status.HTTP_201_CREATED,
)
def create_credit_note(
    invoice_id: uuid.UUID,
    body: CreditNoteCreate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> CreditNote:
    invoice = _get_invoice_or_404(db, invoice_id)
    try:
        return issue_credit_note(db, invoice, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{invoice_id}/credit-notes", response_model=list[CreditNoteOut])
def list_credit_notes(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[CreditNote]:
    _get_invoice_or_404(db, invoice_id)
    return list(
        db.scalars(
            select(CreditNote)
            .where(CreditNote.invoice_id == invoice_id)
            .order_by(CreditNote.created_at)
        )
    )
