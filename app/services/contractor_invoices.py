import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.compliance.models import RuleVersion
from app.models.contractor import Contractor
from app.models.contractor_invoice import ContractorInvoice, ContractorInvoiceStatus
from app.models.wht_payment import WhtPayment
from app.services.wht import record_contractor_payment


class InvoiceStateError(Exception):
    """Raised when an invoice transition is attempted from the wrong
    status — draft -> submitted -> paid, in order, same one-way state
    machine shape as LeaveRequest's pending -> approved."""


def create_invoice(
    db: Session,
    *,
    org_id: uuid.UUID,
    contractor_id: uuid.UUID,
    invoice_number: str,
    amount_minor: int,
    invoice_date: date,
    description: str | None = None,
    due_date: date | None = None,
) -> ContractorInvoice:
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")
    invoice = ContractorInvoice(
        org_id=org_id,
        contractor_id=contractor_id,
        invoice_number=invoice_number,
        description=description,
        amount_minor=amount_minor,
        invoice_date=invoice_date,
        due_date=due_date,
    )
    db.add(invoice)
    db.flush()
    return invoice


def submit_invoice(invoice: ContractorInvoice) -> ContractorInvoice:
    if invoice.status != ContractorInvoiceStatus.DRAFT:
        raise InvoiceStateError(f"invoice is {invoice.status.value}, not draft")
    invoice.status = ContractorInvoiceStatus.SUBMITTED
    return invoice


def mark_invoice_paid(
    db: Session,
    *,
    org_id: uuid.UUID,
    invoice: ContractorInvoice,
    contractor: Contractor,
    category: str,
    payment_date: date,
    rules: RuleVersion,
) -> tuple[ContractorInvoice, WhtPayment]:
    """Paying an invoice records the actual withholding-tax payment for its
    amount (app.services.wht.record_contractor_payment) — same ledger
    postings and statutory liability a payment recorded without an
    invoice would get — and links the two, so a paid invoice always has
    the WHT certificate that discharged it.
    """
    if invoice.status != ContractorInvoiceStatus.SUBMITTED:
        raise InvoiceStateError(f"invoice is {invoice.status.value}, not submitted")

    payment = record_contractor_payment(
        db,
        org_id=org_id,
        contractor=contractor,
        category=category,
        gross_amount_minor=invoice.amount_minor,
        payment_date=payment_date,
        rules=rules,
    )
    invoice.status = ContractorInvoiceStatus.PAID
    invoice.wht_payment_id = payment.id
    db.add(invoice)
    db.flush()
    return invoice, payment
