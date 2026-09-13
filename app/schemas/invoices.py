import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr

from app.models.invoice import InvoiceStatus


class InvoiceCreate(BaseModel):
    customer_id: uuid.UUID
    invoice_number: str
    issue_date: date
    due_date: date
    revenue_account_code: str
    amount_minor: int
    description: str | None = None


class InvoiceOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    customer_id: uuid.UUID
    invoice_number: str
    issue_date: date
    due_date: date
    revenue_account_code: str
    amount_minor: int
    description: str | None
    status: InvoiceStatus
    paid_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EmailInvoiceRequest(BaseModel):
    # Overrides the customer's contact_email on file; required if none is set.
    to: EmailStr | None = None
