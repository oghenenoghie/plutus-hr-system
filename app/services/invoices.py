import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chart_account import AccountType, ChartAccount
from app.models.invoice import Invoice, InvoiceStatus
from app.schemas.general_ledger import JournalEntryLineCreate
from app.services.general_ledger import post_manual_journal_entry


def _revenue_account_or_raise(db: Session, *, org_id: uuid.UUID, code: str) -> ChartAccount:
    account = db.scalar(
        select(ChartAccount).where(ChartAccount.org_id == org_id, ChartAccount.code == code)
    )
    if account is None or account.type != AccountType.REVENUE:
        raise ValueError(f"{code!r} is not a known revenue account")
    return account


def register_invoice(
    db: Session,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    invoice_number: str,
    issue_date: date,
    due_date: date,
    revenue_account_code: str,
    amount_minor: int,
    description: str | None = None,
) -> Invoice:
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")
    if due_date < issue_date:
        raise ValueError("due_date cannot be before issue_date")
    _revenue_account_or_raise(db, org_id=org_id, code=revenue_account_code)

    invoice = Invoice(
        org_id=org_id,
        customer_id=customer_id,
        invoice_number=invoice_number,
        issue_date=issue_date,
        due_date=due_date,
        revenue_account_code=revenue_account_code,
        amount_minor=amount_minor,
        description=description,
    )
    db.add(invoice)
    db.flush()
    return invoice


def send_invoice(db: Session, invoice: Invoice) -> Invoice:
    if invoice.status != InvoiceStatus.DRAFT:
        raise ValueError(
            f"only a draft invoice can be sent (this invoice is {invoice.status.value})"
        )

    post_manual_journal_entry(
        db,
        org_id=invoice.org_id,
        description=f"Invoice {invoice.invoice_number} sent",
        lines=[
            JournalEntryLineCreate(
                account_code="accounts_receivable", debit_minor=invoice.amount_minor
            ),
            JournalEntryLineCreate(
                account_code=invoice.revenue_account_code, credit_minor=invoice.amount_minor
            ),
        ],
    )
    invoice.status = InvoiceStatus.SENT
    db.add(invoice)
    db.flush()
    return invoice


def record_invoice_payment(
    db: Session, invoice: Invoice, *, cash_account_code: str = "cash"
) -> Invoice:
    if invoice.status != InvoiceStatus.SENT:
        raise ValueError(
            f"only a sent invoice can be marked paid (this invoice is {invoice.status.value})"
        )

    post_manual_journal_entry(
        db,
        org_id=invoice.org_id,
        description=f"Invoice {invoice.invoice_number} paid",
        lines=[
            JournalEntryLineCreate(
                account_code=cash_account_code, debit_minor=invoice.amount_minor
            ),
            JournalEntryLineCreate(
                account_code="accounts_receivable", credit_minor=invoice.amount_minor
            ),
        ],
    )
    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = datetime.now(UTC)
    db.add(invoice)
    db.flush()
    return invoice


def void_invoice(db: Session, invoice: Invoice) -> Invoice:
    if invoice.status != InvoiceStatus.DRAFT:
        raise ValueError(
            f"only a draft invoice can be voided (this invoice is {invoice.status.value})"
        )
    invoice.status = InvoiceStatus.VOID
    db.add(invoice)
    db.flush()
    return invoice
