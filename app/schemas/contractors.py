import uuid
from datetime import date, datetime

from pydantic import BaseModel


class ContractorCreate(BaseModel):
    name: str
    tin: str | None = None
    bank_name: str | None = None
    account_number: str | None = None
    account_name: str | None = None


class ContractorUpdate(BaseModel):
    name: str | None = None
    tin: str | None = None
    bank_name: str | None = None
    account_number: str | None = None
    account_name: str | None = None


class ContractorOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    tin: str | None
    bank_name: str | None
    account_number: str | None
    account_name: str | None
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
