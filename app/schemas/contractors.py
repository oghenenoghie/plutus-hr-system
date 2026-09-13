import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.contractor_invoice import ContractorInvoiceStatus


class ContractorCreate(BaseModel):
    name: str
    tin: str | None = None
    bank_name: str | None = None
    account_number: str | None = None
    account_name: str | None = None
    email: str | None = None
    phone: str | None = None
    engagement_start_date: date | None = None
    engagement_end_date: date | None = None


class ContractorUpdate(BaseModel):
    name: str | None = None
    tin: str | None = None
    bank_name: str | None = None
    account_number: str | None = None
    account_name: str | None = None
    email: str | None = None
    phone: str | None = None
    engagement_start_date: date | None = None
    engagement_end_date: date | None = None


class ContractorOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    tin: str | None
    bank_name: str | None
    account_number: str | None
    account_name: str | None
    email: str | None
    phone: str | None
    engagement_start_date: date | None
    engagement_end_date: date | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContractorInvoiceCreate(BaseModel):
    invoice_number: str
    amount_minor: int
    invoice_date: date
    description: str | None = None
    due_date: date | None = None


class ContractorInvoicePayRequest(BaseModel):
    category: str
    payment_date: date


class ContractorInvoiceOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    contractor_id: uuid.UUID
    wht_payment_id: uuid.UUID | None
    invoice_number: str
    description: str | None
    amount_minor: int
    invoice_date: date
    due_date: date | None
    status: ContractorInvoiceStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class WhtPaymentCreate(BaseModel):
    category: str
    gross_amount_minor: int
    payment_date: date


class WhtPaymentOut(BaseModel):
    id: uuid.UUID
    contractor_id: uuid.UUID
    category: str
    gross_amount_minor: int
    wht_amount_minor: int
    net_amount_minor: int
    payment_date: date
    due_date: date
    certificate_number: str
    rule_version_id: str
    created_at: datetime

    model_config = {"from_attributes": True}
