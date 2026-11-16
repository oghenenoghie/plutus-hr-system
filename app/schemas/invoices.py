import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field

from app.domain.accounting.vat import VatTreatment
from app.models.invoice import InvoiceStatus


class InvoiceCreate(BaseModel):
    customer_id: uuid.UUID
    # Left out or blank, the next number in the org's sequence (INV-0001, ...).
    invoice_number: str | None = None
    issue_date: date
    due_date: date
    revenue_account_code: str
    # The net amount, before VAT.
    amount_minor: int
    description: str | None = None
    # How VAT applies; left out, no VAT is charged. "other" needs the rate's
    # name and the rate (ppm: 150_000 is 15%); the others set the rate.
    vat_treatment: VatTreatment | None = None
    vat_rate_name: str | None = Field(default=None, max_length=64)
    vat_rate_ppm: int | None = Field(default=None, ge=0, le=1_000_000)


class InvoiceOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    customer_id: uuid.UUID
    invoice_number: str
    issue_date: date
    due_date: date
    revenue_account_code: str
    amount_minor: int  # net, before VAT
    vat_treatment: VatTreatment | None
    vat_rate_name: str | None
    vat_rate_ppm: int
    vat_minor: int
    total_minor: int  # what the customer owes: amount plus VAT
    description: str | None
    status: InvoiceStatus
    paid_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EmailInvoiceRequest(BaseModel):
    # Overrides the customer's contact_email on file; required if none is set.
    to: EmailStr | None = None


class NextInvoiceNumberOut(BaseModel):
    invoice_number: str


class VatOptionOut(BaseModel):
    treatment: VatTreatment
    label: str  # as shown in the dropdown and printed: "VAT 7.5%", "VAT exempt"
    rate_ppm: int | None  # None for "other": the user enters it


class VatOptionsOut(BaseModel):
    country_code: str
    options: list[VatOptionOut]
