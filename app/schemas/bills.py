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
    vat_minor: int = 0
    wht_category: str | None = None
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
    vat_minor: int
    wht_category: str | None
    wht_amount_minor: int
    net_payable_minor: int
    description: str | None
    status: BillStatus
    paid_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
