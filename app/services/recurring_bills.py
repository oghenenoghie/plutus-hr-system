import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.recurrence import RecurrenceFrequency, next_occurrence
from app.models.bill import Bill
from app.models.recurring_bill import RecurringBill
from app.services.bills import register_bill


def register_recurring_bill(
    db: Session,
    *,
    org_id: uuid.UUID,
    vendor_id: uuid.UUID,
    bill_number_prefix: str,
    expense_account_code: str,
    amount_minor: int,
    frequency: RecurrenceFrequency,
    next_run_date: date,
    vat_minor: int = 0,
    wht_category: str | None = None,
    description: str | None = None,
    due_in_days: int = 30,
) -> RecurringBill:
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")
    if due_in_days < 0:
        raise ValueError("due_in_days cannot be negative")

    template = RecurringBill(
        org_id=org_id,
        vendor_id=vendor_id,
        bill_number_prefix=bill_number_prefix,
        expense_account_code=expense_account_code,
        amount_minor=amount_minor,
        vat_minor=vat_minor,
        wht_category=wht_category,
        description=description,
        due_in_days=due_in_days,
        frequency=frequency,
        next_run_date=next_run_date,
    )
    db.add(template)
    db.flush()
    return template


def generate_due_bills(db: Session, org_id: uuid.UUID, *, as_of: date) -> list[Bill]:
    """Materializes one Bill per active RecurringBill template whose
    next_run_date has arrived, then advances that template to its next
    occurrence — so calling this again immediately with the same as_of
    generates nothing further for a template that just ran."""
    templates = db.scalars(
        select(RecurringBill).where(
            RecurringBill.org_id == org_id,
            RecurringBill.is_active.is_(True),
            RecurringBill.next_run_date <= as_of,
        )
    )
    generated = []
    for template in templates:
        bill = register_bill(
            db,
            org_id=org_id,
            vendor_id=template.vendor_id,
            bill_number=f"{template.bill_number_prefix}-{template.next_run_date.isoformat()}",
            bill_date=template.next_run_date,
            due_date=template.next_run_date + timedelta(days=template.due_in_days),
            expense_account_code=template.expense_account_code,
            amount_minor=template.amount_minor,
            vat_minor=template.vat_minor,
            wht_category=template.wht_category,
            description=template.description,
        )
        generated.append(bill)
        template.next_run_date = next_occurrence(template.next_run_date, template.frequency)
        db.add(template)
    db.flush()
    return generated
