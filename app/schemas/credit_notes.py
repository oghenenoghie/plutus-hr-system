import uuid
from datetime import date, datetime

from pydantic import BaseModel


class CreditNoteCreate(BaseModel):
    credit_note_number: str
    issue_date: date
    amount_minor: int
    reason: str


class CreditNoteOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    invoice_id: uuid.UUID
    credit_note_number: str
    issue_date: date
    amount_minor: int
    reason: str
    created_at: datetime

    model_config = {"from_attributes": True}
