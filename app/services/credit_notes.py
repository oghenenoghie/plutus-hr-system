import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.credit_note import CreditNote
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.general_ledger import JournalEntryLineCreate
from app.services.general_ledger import post_manual_journal_entry


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
    if already_credited + amount_minor > invoice.amount_minor:
        remaining = invoice.amount_minor - already_credited
        raise ValueError(f"amount_minor exceeds the invoice's remaining balance ({remaining})")

    post_manual_journal_entry(
        db,
        org_id=invoice.org_id,
        description=f"Credit note {credit_note_number} against invoice {invoice.invoice_number}",
        lines=[
            JournalEntryLineCreate(
                account_code=invoice.revenue_account_code, debit_minor=amount_minor
            ),
            JournalEntryLineCreate(account_code="accounts_receivable", credit_minor=amount_minor),
        ],
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
