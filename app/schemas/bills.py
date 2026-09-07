import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.bill import BillStatus


class BillCreate(BaseModel):
    vendor_id: uuid.UUID
    bill_number: str
    bill_date: date
    due_date: date
    expense_account_code: str
    amount_minor: int
    description: str | None = None


class BillOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    vendor_id: uuid.UUID
    bill_number: str
    bill_date: date
    due_date: date
    expense_account_code: str
    amount_minor: int
    description: str | None
    status: BillStatus
    paid_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
