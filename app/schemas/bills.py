import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field

from app.domain.accounting.vat import VatTreatment
from app.models.bill import BillStatus


class BillCreate(BaseModel):
    vendor_id: uuid.UUID
    bill_number: str
    bill_date: date
    due_date: date
    expense_account_code: str
    amount_minor: int
    # How VAT applies, as on an invoice; the VAT is then worked out from the
    # rate. Left out, the bill carries vat_minor as entered (none by default).
    vat_treatment: VatTreatment | None = None
    vat_rate_name: str | None = Field(default=None, max_length=64)
    vat_rate_ppm: int | None = Field(default=None, ge=0, le=1_000_000)
    vat_minor: int = 0
    wht_category: str | None = None
    description: str | None = None
    # D2: the goods receipt this bill invoices; approving the bill clears
    # the receipt's goods-received-not-invoiced accrual.
    goods_receipt_id: uuid.UUID | None = None


class BillOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    vendor_id: uuid.UUID
    bill_number: str
    bill_date: date
    due_date: date
    expense_account_code: str
    amount_minor: int
    vat_treatment: VatTreatment | None
    vat_rate_name: str | None
    vat_rate_ppm: int
    vat_minor: int
    total_minor: int
    wht_category: str | None
    wht_amount_minor: int
    net_payable_minor: int
    description: str | None
    goods_receipt_id: uuid.UUID | None
    status: BillStatus
    paid_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EmailBillRequest(BaseModel):
    # Overrides the vendor's contact_email on file; required if none is set.
    to: EmailStr | None = None
