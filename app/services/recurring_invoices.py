import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.recurrence import RecurrenceFrequency, next_occurrence
from app.models.invoice import Invoice
from app.models.recurring_invoice import RecurringInvoice
from app.services.invoices import register_invoice


def register_recurring_invoice(
    db: Session,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    invoice_number_prefix: str,
    revenue_account_code: str,
    amount_minor: int,
    frequency: RecurrenceFrequency,
    next_run_date: date,
    description: str | None = None,
    due_in_days: int = 30,
) -> RecurringInvoice:
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")
    if due_in_days < 0:
        raise ValueError("due_in_days cannot be negative")

    template = RecurringInvoice(
        org_id=org_id,
        customer_id=customer_id,
        invoice_number_prefix=invoice_number_prefix,
        revenue_account_code=revenue_account_code,
        amount_minor=amount_minor,
        description=description,
        due_in_days=due_in_days,
        frequency=frequency,
        next_run_date=next_run_date,
    )
    db.add(template)
    db.flush()
    return template


def generate_due_invoices(db: Session, org_id: uuid.UUID, *, as_of: date) -> list[Invoice]:
    templates = db.scalars(
        select(RecurringInvoice).where(
            RecurringInvoice.org_id == org_id,
            RecurringInvoice.is_active.is_(True),
            RecurringInvoice.next_run_date <= as_of,
        )
    )
    generated = []
    for template in templates:
        invoice = register_invoice(
            db,
            org_id=org_id,
            customer_id=template.customer_id,
            invoice_number=f"{template.invoice_number_prefix}-{template.next_run_date.isoformat()}",
            issue_date=template.next_run_date,
            due_date=template.next_run_date + timedelta(days=template.due_in_days),
            revenue_account_code=template.revenue_account_code,
            amount_minor=template.amount_minor,
            description=template.description,
        )
        generated.append(invoice)
        template.next_run_date = next_occurrence(template.next_run_date, template.frequency)
        db.add(template)
    db.flush()
    return generated
