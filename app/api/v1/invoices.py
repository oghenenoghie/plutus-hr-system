import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.membership import Role
from app.models.organisation import Organisation
from app.schemas.invoices import EmailInvoiceRequest, InvoiceCreate, InvoiceOut
from app.services.audit import record_audit_event
from app.services.document_email import email_invoice_pdf
from app.services.invoice_pdf import render_invoice_pdf
from app.services.invoices import (
    record_invoice_payment,
    register_invoice,
    send_invoice,
    void_invoice,
)

router = APIRouter(prefix="/invoices", tags=["accounting"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT)


def _get_invoice_or_404(db: Session, invoice_id: uuid.UUID) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invoice not found")
    return invoice


def _get_invoice_customer_org(
    db: Session, invoice_id: uuid.UUID
) -> tuple[Invoice, Customer, Organisation]:
    invoice = _get_invoice_or_404(db, invoice_id)
    customer = db.get(Customer, invoice.customer_id)
    organisation = db.get(Organisation, invoice.org_id)
    if customer is None or organisation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invoice not found")
    return invoice, customer, organisation


@router.post("", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def create_invoice(
    body: InvoiceCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Invoice:
    try:
        invoice = register_invoice(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="an invoice with this number already exists for this customer",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="invoice.create",
        entity_type="invoice",
        entity_id=invoice.id,
        metadata={"invoice_number": invoice.invoice_number, "amount_minor": invoice.amount_minor},
    )
    return invoice


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
    claims: TokenClaims = Depends(_MANAGE),
) -> Invoice:
    invoice = _get_invoice_or_404(db, invoice_id)
    try:
        sent = send_invoice(db, invoice)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="invoice.send",
        entity_type="invoice",
        entity_id=sent.id,
    )
    return sent


@router.post("/{invoice_id}/pay", response_model=InvoiceOut)
def pay(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Invoice:
    invoice = _get_invoice_or_404(db, invoice_id)
    try:
        paid = record_invoice_payment(db, invoice)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="invoice.pay",
        entity_type="invoice",
        entity_id=paid.id,
        metadata={"amount_minor": paid.amount_minor},
    )
    return paid


@router.post("/{invoice_id}/void", response_model=InvoiceOut)
def void(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Invoice:
    invoice = _get_invoice_or_404(db, invoice_id)
    try:
        voided = void_invoice(db, invoice)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="invoice.void",
        entity_type="invoice",
        entity_id=voided.id,
    )
    return voided


@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> Response:
    invoice, customer, organisation = _get_invoice_customer_org(db, invoice_id)
    pdf_bytes = render_invoice_pdf(organisation=organisation, invoice=invoice, customer=customer)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="invoice-{invoice.invoice_number}.pdf"'
        },
    )


@router.post("/{invoice_id}/email", status_code=status.HTTP_204_NO_CONTENT)
def email_invoice(
    invoice_id: uuid.UUID,
    body: EmailInvoiceRequest,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> None:
    invoice, customer, organisation = _get_invoice_customer_org(db, invoice_id)
    try:
        email_invoice_pdf(organisation=organisation, invoice=invoice, customer=customer, to=body.to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"email delivery failed: {exc}"
        ) from exc
