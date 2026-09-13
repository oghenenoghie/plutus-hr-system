import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.invoice import Invoice
from app.models.membership import Role
from app.models.recurring_invoice import RecurringInvoice
from app.schemas.invoices import InvoiceOut
from app.schemas.recurring_invoices import (
    RecurringInvoiceCreate,
    RecurringInvoiceOut,
    RecurringInvoiceUpdate,
)
from app.services.recurring_invoices import generate_due_invoices, register_recurring_invoice

router = APIRouter(prefix="/recurring-invoices", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_or_404(db: Session, template_id: uuid.UUID) -> RecurringInvoice:
    template = db.get(RecurringInvoice, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="recurring invoice not found"
        )
    return template


@router.post("", response_model=RecurringInvoiceOut, status_code=status.HTTP_201_CREATED)
def create_recurring_invoice(
    body: RecurringInvoiceCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> RecurringInvoice:
    try:
        return register_recurring_invoice(db, org_id=claims.org_id, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("", response_model=list[RecurringInvoiceOut])
def list_recurring_invoices(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[RecurringInvoice]:
    return list(db.scalars(select(RecurringInvoice)))


@router.patch("/{template_id}", response_model=RecurringInvoiceOut)
def update_recurring_invoice(
    template_id: uuid.UUID,
    body: RecurringInvoiceUpdate,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> RecurringInvoice:
    template = _get_or_404(db, template_id)
    template.is_active = body.is_active
    db.add(template)
    db.flush()
    return template


@router.post("/generate-due", response_model=list[InvoiceOut])
def generate_due(
    as_of: date | None = None,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[Invoice]:
    return generate_due_invoices(db, claims.org_id, as_of=as_of or datetime.now(UTC).date())
