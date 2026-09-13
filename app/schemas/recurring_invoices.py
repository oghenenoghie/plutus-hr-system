import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.domain.recurrence import RecurrenceFrequency


class RecurringInvoiceCreate(BaseModel):
    customer_id: uuid.UUID
    invoice_number_prefix: str
    revenue_account_code: str
    amount_minor: int
    frequency: RecurrenceFrequency
    next_run_date: date
    description: str | None = None
    due_in_days: int = 30


class RecurringInvoiceUpdate(BaseModel):
    is_active: bool


class RecurringInvoiceOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    customer_id: uuid.UUID
    invoice_number_prefix: str
    revenue_account_code: str
    amount_minor: int
    description: str | None
    due_in_days: int
    frequency: RecurrenceFrequency
    next_run_date: date
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
