import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.credit_note import CreditNote
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.general_ledger import JournalEntryLineCreate
from app.services.general_ledger import post_manual_journal_entry


def credited_vat(amount_minor: int, invoice: Invoice) -> int:
    """The VAT share of a credit of amount_minor against the invoice's total,
    rounded half up; a full credit takes back exactly the invoice's VAT."""
    if not invoice.vat_minor or not invoice.total_minor:
        return 0
    if amount_minor == invoice.total_minor:
        return invoice.vat_minor
    return (amount_minor * invoice.vat_minor * 2 + invoice.total_minor) // (2 * invoice.total_minor)


def total_credited(db: Session, invoice_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(CreditNote.amount_minor), 0)).where(
                CreditNote.invoice_id == invoice_id
            )
        )
        or 0
    )


def issue_credit_note(
    db: Session,
    invoice: Invoice,
    *,
    credit_note_number: str,
    issue_date: date,
    amount_minor: int,
    reason: str,
) -> CreditNote:
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")
    if invoice.status not in (InvoiceStatus.SENT, InvoiceStatus.PAID):
        raise ValueError(
            f"can only credit a sent or paid invoice (this invoice is {invoice.status.value})"
        )
    already_credited = total_credited(db, invoice.id)
    if already_credited + amount_minor > invoice.total_minor:
        remaining = invoice.total_minor - already_credited
        raise ValueError(f"amount_minor exceeds the invoice's remaining balance ({remaining})")

    # A credit note is against what the customer owes, VAT included: it
    # takes back income and output VAT in the invoice's own proportion.
    vat_part = credited_vat(amount_minor, invoice)
    if invoice.vat_minor and already_credited + amount_minor == invoice.total_minor:
        # The credit that clears the invoice takes back whatever VAT is left,
        # so rounding on earlier partial credits never leaves a kobo behind.
        earlier = db.scalars(
            select(CreditNote.amount_minor).where(CreditNote.invoice_id == invoice.id)
        ).all()
        vat_part = invoice.vat_minor - sum(credited_vat(amount, invoice) for amount in earlier)
    lines = [
        JournalEntryLineCreate(
            account_code=invoice.revenue_account_code, debit_minor=amount_minor - vat_part
        ),
        JournalEntryLineCreate(account_code="accounts_receivable", credit_minor=amount_minor),
    ]
    if vat_part:
        lines.insert(1, JournalEntryLineCreate(account_code="vat_payable", debit_minor=vat_part))
    post_manual_journal_entry(
        db,
        org_id=invoice.org_id,
        description=f"Credit note {credit_note_number} against invoice {invoice.invoice_number}",
        lines=lines,
    )
    credit_note = CreditNote(
        org_id=invoice.org_id,
        invoice_id=invoice.id,
        credit_note_number=credit_note_number,
        issue_date=issue_date,
        amount_minor=amount_minor,
        reason=reason,
    )
    db.add(credit_note)
    db.flush()
    return credit_note
