import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.domain.recurrence import RecurrenceFrequency


class RecurringBillCreate(BaseModel):
    vendor_id: uuid.UUID
    bill_number_prefix: str
    expense_account_code: str
    amount_minor: int
    frequency: RecurrenceFrequency
    next_run_date: date
    vat_minor: int = 0
    wht_category: str | None = None
    description: str | None = None
    due_in_days: int = 30


class RecurringBillUpdate(BaseModel):
    is_active: bool


class RecurringBillOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    vendor_id: uuid.UUID
    bill_number_prefix: str
    expense_account_code: str
    amount_minor: int
    vat_minor: int
    wht_category: str | None
    description: str | None
    due_in_days: int
    frequency: RecurrenceFrequency
    next_run_date: date
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
