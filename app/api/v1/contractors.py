import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.resolver import resolve_rule_version
from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.contractor import Contractor
from app.models.contractor_invoice import ContractorInvoice
from app.models.membership import Role
from app.models.wht_payment import WhtPayment
from app.schemas.contractors import (
    ContractorCreate,
    ContractorInvoiceCreate,
    ContractorInvoiceOut,
    ContractorInvoicePayRequest,
    ContractorOut,
    ContractorUpdate,
    WhtPaymentCreate,
    WhtPaymentOut,
)
from app.services.audit import record_audit_event
from app.services.contractor_invoices import (
    InvoiceStateError,
    create_invoice,
    mark_invoice_paid,
    submit_invoice,
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
    contractor = register_contractor(db, org_id=claims.org_id, **body.model_dump())
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="contractor.create",
        entity_type="contractor",
        entity_id=contractor.id,
        metadata={"name": contractor.name},
    )
    return contractor


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
    claims: TokenClaims = Depends(_MANAGE),
) -> Contractor:
    contractor = _get_contractor_or_404(db, contractor_id)
    changed_fields = body.model_dump(exclude_unset=True)
    for field, value in changed_fields.items():
        setattr(contractor, field, value)
    db.add(contractor)
    db.flush()
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="contractor.update",
        entity_type="contractor",
        entity_id=contractor.id,
        metadata={"fields": sorted(changed_fields)},
    )
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
        payment = record_contractor_payment(
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
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="wht_payment.record",
        entity_type="wht_payment",
        entity_id=payment.id,
        metadata={
            "contractor_id": str(contractor_id),
            "category": payment.category,
            "gross_amount_minor": payment.gross_amount_minor,
            "wht_amount_minor": payment.wht_amount_minor,
        },
    )
    return payment


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


def _get_invoice_or_404(
    db: Session, contractor_id: uuid.UUID, invoice_id: uuid.UUID
) -> ContractorInvoice:
    invoice = db.get(ContractorInvoice, invoice_id)
    if invoice is None or invoice.contractor_id != contractor_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invoice not found")
    return invoice


@router.post(
    "/{contractor_id}/invoices",
    response_model=ContractorInvoiceOut,
    status_code=status.HTTP_201_CREATED,
)
def create_contractor_invoice(
    contractor_id: uuid.UUID,
    body: ContractorInvoiceCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> ContractorInvoice:
    _get_contractor_or_404(db, contractor_id)
    try:
        invoice = create_invoice(
            db, org_id=claims.org_id, contractor_id=contractor_id, **body.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="contractor_invoice.create",
        entity_type="contractor_invoice",
        entity_id=invoice.id,
        metadata={"contractor_id": str(contractor_id), "invoice_number": invoice.invoice_number},
    )
    return invoice


@router.get("/{contractor_id}/invoices", response_model=list[ContractorInvoiceOut])
def list_contractor_invoices(
    contractor_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> list[ContractorInvoice]:
    _get_contractor_or_404(db, contractor_id)
    return list(
        db.scalars(
            select(ContractorInvoice)
            .where(ContractorInvoice.contractor_id == contractor_id)
            .order_by(ContractorInvoice.invoice_date.desc())
        )
    )


@router.post("/{contractor_id}/invoices/{invoice_id}/submit", response_model=ContractorInvoiceOut)
def submit_contractor_invoice(
    contractor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> ContractorInvoice:
    invoice = _get_invoice_or_404(db, contractor_id, invoice_id)
    try:
        submit_invoice(invoice)
    except InvoiceStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.add(invoice)
    db.flush()
    return invoice


@router.post("/{contractor_id}/invoices/{invoice_id}/pay", response_model=ContractorInvoiceOut)
def pay_contractor_invoice(
    contractor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    body: ContractorInvoicePayRequest,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> ContractorInvoice:
    contractor = _get_contractor_or_404(db, contractor_id)
    invoice = _get_invoice_or_404(db, contractor_id, invoice_id)
    rules = resolve_rule_version(_COUNTRY, body.payment_date)
    try:
        invoice, payment = mark_invoice_paid(
            db,
            org_id=claims.org_id,
            invoice=invoice,
            contractor=contractor,
            category=body.category,
            payment_date=body.payment_date,
            rules=rules,
        )
    except (InvoiceStateError, MissingContractorTinError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="contractor_invoice.pay",
        entity_type="contractor_invoice",
        entity_id=invoice.id,
        metadata={"wht_payment_id": str(payment.id)},
    )
    return invoice
